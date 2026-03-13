"""
Instant Notification Service - Dubai-Style Real-Time Alerts.

This is the final stage of the pipeline. When a violation is detected,
this service sends an immediate SMS to the registered vehicle keeper,
just like Dubai's traffic violation system.

Pipeline: ANPR Read → Violation Detection → DVLA Lookup → SMS Sent
Target: Under 10 seconds end-to-end.

Channels:
1. SMS (primary - like Dubai) - via Twilio
2. Email (secondary) - via SendGrid
3. Push notification (future) - via FCM
4. Webhook (for third-party integrations)
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import httpx
import redis.asyncio as redis
from sqlalchemy import update

from src.models.database import get_session
from src.models.orm import AlertLogORM, ViolationORM, AlertChannel, AlertStatus

logger = logging.getLogger(__name__)

NOTIFICATION_STREAM = "notifications"
CONSUMER_GROUP = "notification_senders"


class TwilioSMSClient:
    """Twilio SMS client for sending instant violation notifications."""

    def __init__(self):
        self.account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
        self.auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                auth=(self.account_sid, self.auth_token),
                timeout=30.0,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @property
    def is_configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_number)

    async def send_sms(self, to_number: str, message: str) -> dict:
        """
        Send an SMS via Twilio.

        Returns dict with 'success', 'message_sid', 'error' keys.
        """
        if not self.is_configured:
            logger.warning("Twilio not configured, SMS not sent to %s", to_number)
            return {"success": False, "message_sid": None, "error": "Twilio not configured"}

        client = await self._get_client()
        url = (
            f"https://api.twilio.com/2010-04-01"
            f"/Accounts/{self.account_sid}/Messages.json"
        )

        try:
            resp = await client.post(
                url,
                data={
                    "To": to_number,
                    "From": self.from_number,
                    "Body": message,
                },
            )
            data = resp.json()

            if resp.status_code in (200, 201):
                return {
                    "success": True,
                    "message_sid": data.get("sid"),
                    "error": None,
                }
            else:
                return {
                    "success": False,
                    "message_sid": None,
                    "error": data.get("message", f"HTTP {resp.status_code}"),
                }
        except httpx.HTTPError as e:
            return {"success": False, "message_sid": None, "error": str(e)}


class SendGridEmailClient:
    """SendGrid client for sending violation notification emails."""

    def __init__(self):
        self.api_key = os.environ.get("SENDGRID_API_KEY", "")
        self.from_email = os.environ.get(
            "ALERT_FROM_EMAIL", "alerts@vans-uk.gov.uk"
        )
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def send_email(
        self, to_email: str, subject: str, html_body: str
    ) -> dict:
        """Send an email via SendGrid."""
        if not self.is_configured:
            return {"success": False, "error": "SendGrid not configured"}

        client = await self._get_client()
        try:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json={
                    "personalizations": [{"to": [{"email": to_email}]}],
                    "from": {"email": self.from_email, "name": "VANS UK"},
                    "subject": subject,
                    "content": [{"type": "text/html", "value": html_body}],
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code in (200, 201, 202):
                return {"success": True, "error": None}
            return {"success": False, "error": f"HTTP {resp.status_code}"}
        except httpx.HTTPError as e:
            return {"success": False, "error": str(e)}


def format_sms_message(data: dict) -> str:
    """
    Format a violation notification SMS.

    Modeled after Dubai's RTA violation SMS format:
    concise, includes reference number, violation details, and fine.
    """
    ref = data.get("reference_number", "N/A")
    v_type = data.get("violation_type", "UNKNOWN")
    road = data.get("road", "Unknown road")
    description = data.get("description", "")
    fine_pence = int(data.get("fine_amount_pence", 0))
    fine_pounds = fine_pence / 100
    points = data.get("points", "0")
    timestamp = data.get("timestamp", "")

    # Truncate timestamp to readable format
    try:
        dt = datetime.fromisoformat(timestamp)
        time_str = dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        time_str = timestamp

    message = (
        f"VANS UK Traffic Violation Notice\n"
        f"Ref: {ref}\n"
        f"Violation: {v_type} on {road}\n"
        f"{description}\n"
        f"Fine: £{fine_pounds:.2f}"
    )
    if int(points) > 0:
        message += f" | {points} points"
    message += (
        f"\nDate: {time_str}\n"
        f"Pay or appeal within 28 days at vans-uk.gov.uk/pay\n"
        f"Do not reply to this message."
    )
    return message


def format_violation_email_html(data: dict) -> tuple[str, str]:
    """Format a violation notification email with subject and HTML body."""
    ref = data.get("reference_number", "N/A")
    v_type = data.get("violation_type", "UNKNOWN")
    severity = data.get("severity", "UNKNOWN")
    plate = data.get("vehicle_plate", "")
    road = data.get("road", "Unknown road")
    description = data.get("description", "")
    fine_pence = int(data.get("fine_amount_pence", 0))
    fine_pounds = fine_pence / 100
    points = data.get("points", "0")
    keeper_name = data.get("keeper_name", "Vehicle Keeper")
    timestamp = data.get("timestamp", "")

    subject = f"Traffic Violation Notice - Ref: {ref}"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background: #1d4ed8; color: white; padding: 20px; text-align: center;">
        <h1 style="margin: 0; font-size: 24px;">VANS UK</h1>
        <p style="margin: 5px 0 0;">Vehicle Alert Notification System</p>
    </div>

    <div style="padding: 20px; border: 1px solid #e5e7eb;">
        <h2 style="color: #dc2626;">Traffic Violation Notice</h2>
        <p>Dear {keeper_name},</p>
        <p>A traffic violation has been recorded against vehicle <strong>{plate}</strong>.</p>

        <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 8px; font-weight: bold;">Reference Number</td>
                <td style="padding: 8px;">{ref}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 8px; font-weight: bold;">Violation Type</td>
                <td style="padding: 8px;">{v_type}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 8px; font-weight: bold;">Location</td>
                <td style="padding: 8px;">{road}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 8px; font-weight: bold;">Details</td>
                <td style="padding: 8px;">{description}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 8px; font-weight: bold;">Date & Time</td>
                <td style="padding: 8px;">{timestamp}</td>
            </tr>
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 8px; font-weight: bold;">Fine Amount</td>
                <td style="padding: 8px; color: #dc2626; font-weight: bold;">
                    &pound;{fine_pounds:.2f}
                </td>
            </tr>
            <tr>
                <td style="padding: 8px; font-weight: bold;">Penalty Points</td>
                <td style="padding: 8px;">{points}</td>
            </tr>
        </table>

        <div style="background: #fef3c7; padding: 15px; border-radius: 5px; margin: 20px 0;">
            <strong>Important:</strong> You have 28 days to pay or appeal this notice.
            Failure to respond may result in increased penalties.
        </div>

        <p>
            <a href="https://vans-uk.gov.uk/pay/{ref}"
               style="display: inline-block; background: #1d4ed8; color: white;
                      padding: 12px 24px; text-decoration: none; border-radius: 5px;">
                Pay Fine Online
            </a>
            &nbsp;&nbsp;
            <a href="https://vans-uk.gov.uk/appeal/{ref}"
               style="display: inline-block; background: #6b7280; color: white;
                      padding: 12px 24px; text-decoration: none; border-radius: 5px;">
                Submit Appeal
            </a>
        </p>
    </div>

    <div style="padding: 15px; background: #f3f4f6; font-size: 12px; color: #6b7280;">
        <p>This is an automated notification from the Vehicle Alert Notification System (VANS UK).
        For queries, contact support@vans-uk.gov.uk or call 0300 123 VANS.</p>
        <p>DVLA | Driver and Vehicle Licensing Agency | Swansea SA6 7JL</p>
    </div>
</body>
</html>"""
    return subject, html


class NotificationService:
    """
    Core notification service that consumes violation events and
    sends instant notifications via SMS and email.

    Runs as a Redis Streams consumer group for horizontal scaling.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        worker_id: str = "notifier-1",
    ):
        self.redis = redis_client
        self.worker_id = worker_id
        self.sms_client = TwilioSMSClient()
        self.email_client = SendGridEmailClient()
        self._running = False
        self._stats = {
            "sms_sent": 0,
            "sms_failed": 0,
            "email_sent": 0,
            "email_failed": 0,
            "avg_latency_ms": 0,
        }

    async def start(self):
        """Start the notification processing loop."""
        await self._ensure_consumer_group()
        self._running = True
        logger.info("Notification Service %s started", self.worker_id)

        while self._running:
            try:
                await self._process_batch()
            except Exception:
                logger.exception("Error in notification service loop")
                await asyncio.sleep(1)

    async def stop(self):
        """Gracefully stop the service."""
        self._running = False
        await self.sms_client.close()
        await self.email_client.close()
        logger.info(
            "Notification Service %s stopped. Stats: %s",
            self.worker_id,
            self._stats,
        )

    async def _ensure_consumer_group(self):
        try:
            await self.redis.xgroup_create(
                NOTIFICATION_STREAM, CONSUMER_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def _process_batch(self):
        results = await self.redis.xreadgroup(
            CONSUMER_GROUP,
            self.worker_id,
            {NOTIFICATION_STREAM: ">"},
            count=20,
            block=5000,
        )

        if not results:
            return

        for stream_name, messages in results:
            for msg_id, data in messages:
                try:
                    await self._send_notification(data)
                    await self.redis.xack(
                        NOTIFICATION_STREAM, CONSUMER_GROUP, msg_id
                    )
                except Exception:
                    logger.exception(
                        "Failed to send notification for %s", msg_id
                    )

    async def _send_notification(self, data: dict):
        """Send instant notification for a violation. SMS first (Dubai-style)."""
        violation_id = data.get("violation_id")
        keeper_phone = data.get("keeper_phone", "")
        start_time = time.monotonic()

        # 1. Send SMS (primary channel - like Dubai)
        if keeper_phone:
            sms_message = format_sms_message(data)
            result = await self.sms_client.send_sms(keeper_phone, sms_message)
            latency_ms = int((time.monotonic() - start_time) * 1000)

            async with get_session() as session:
                alert = AlertLogORM(
                    violation_id=int(violation_id) if violation_id else None,
                    channel=AlertChannel.SMS.value,
                    recipient=keeper_phone,
                    status=(
                        AlertStatus.SENT.value
                        if result["success"]
                        else AlertStatus.FAILED.value
                    ),
                    message_sid=result.get("message_sid"),
                    latency_ms=latency_ms,
                    error_message=result.get("error"),
                    sent_at=datetime.now(timezone.utc) if result["success"] else None,
                )
                session.add(alert)

                # Update violation record
                if violation_id and result["success"]:
                    await session.execute(
                        update(ViolationORM)
                        .where(ViolationORM.id == int(violation_id))
                        .values(
                            notification_sent=True,
                            notification_sent_at=datetime.now(timezone.utc),
                        )
                    )

            if result["success"]:
                self._stats["sms_sent"] += 1
                logger.info(
                    "SMS sent to %s for violation %s [%dms]",
                    keeper_phone,
                    data.get("reference_number"),
                    latency_ms,
                )
            else:
                self._stats["sms_failed"] += 1
                logger.error(
                    "SMS failed to %s: %s", keeper_phone, result.get("error")
                )
        else:
            logger.warning(
                "No phone number for violation %s, skipping SMS",
                data.get("reference_number"),
            )

    @property
    def stats(self) -> dict:
        return self._stats.copy()


async def main():
    """Run notification service as standalone worker."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    worker_id = os.environ.get("WORKER_ID", "notifier-1")

    r = redis.from_url(redis_url)
    service = NotificationService(r, worker_id)

    try:
        await service.start()
    except KeyboardInterrupt:
        await service.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
