# Copyright (c) 2026 Belloite Ltd. All rights reserved.
# VANS UK — Proprietary and confidential. Unauthorised use is prohibited. See LICENSE.
"""
Send email alerts for detected violations.

Consumes from the violations Redis Stream and sends formatted email
notifications to relevant subscribers based on their preferences.

Usage:
    python execution/send_email_alert.py

Env vars required:
    REDIS_URL - Redis connection string
    DATABASE_URL - PostgreSQL connection string
    SENDGRID_API_KEY - SendGrid API key
    ALERT_FROM_EMAIL - Sender email address
"""

import asyncio
import logging
import os
import sys

import httpx
import redis.asyncio as redis

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"
MAX_RETRIES = 3
RETRY_DELAYS = [2, 4, 8]  # exponential backoff in seconds


async def get_subscribers_for_violation(violation_data: dict) -> list[dict]:
    """
    Query subscribers interested in this violation type and location.

    In production, queries PostgreSQL for subscribers whose preferences
    match the violation type, location radius, and alert channel = email.
    """
    # TODO: Implement PostgreSQL subscriber lookup
    return []


async def send_email(
    client: httpx.AsyncClient,
    api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    html_content: str,
) -> bool:
    """Send a single email via SendGrid with retry logic."""
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_content}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.post(
                SENDGRID_API_URL,
                json=payload,
                headers=headers,
                timeout=30.0,
            )
            if resp.status_code in (200, 201, 202):
                return True
            logger.warning(
                "SendGrid returned %d on attempt %d", resp.status_code, attempt + 1
            )
        except httpx.HTTPError as e:
            logger.warning("HTTP error on attempt %d: %s", attempt + 1, e)

        if attempt < MAX_RETRIES - 1:
            await asyncio.sleep(RETRY_DELAYS[attempt])

    return False


def format_violation_email(violation_data: dict) -> tuple[str, str]:
    """Format violation data into email subject and HTML body."""
    v_type = violation_data.get("violation_type", "UNKNOWN")
    road = violation_data.get("road", "Unknown road")
    description = violation_data.get("description", "")
    severity = violation_data.get("severity", "UNKNOWN")
    timestamp = violation_data.get("timestamp", "")

    subject = f"[VANS UK] {severity} {v_type} Alert - {road}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px;">
        <h2 style="color: #d32f2f;">VANS UK - Violation Alert</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr><td><strong>Type:</strong></td><td>{v_type}</td></tr>
            <tr><td><strong>Severity:</strong></td><td>{severity}</td></tr>
            <tr><td><strong>Road:</strong></td><td>{road}</td></tr>
            <tr><td><strong>Description:</strong></td><td>{description}</td></tr>
            <tr><td><strong>Time:</strong></td><td>{timestamp}</td></tr>
        </table>
        <p style="color: #666; font-size: 12px; margin-top: 20px;">
            This is an automated alert from VANS UK.
            To manage your preferences, visit your dashboard.
        </p>
    </div>
    """
    return subject, html


async def main():
    """Main consumer loop for email alerts."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    api_key = os.environ.get("SENDGRID_API_KEY")
    from_email = os.environ.get("ALERT_FROM_EMAIL", "alerts@vans-uk.example.com")

    if not api_key:
        logger.error("SENDGRID_API_KEY not set")
        sys.exit(1)

    r = redis.from_url(redis_url)
    last_id = "0-0"
    logger.info("Email alert sender started")

    async with httpx.AsyncClient() as client:
        while True:
            try:
                results = await r.xread(
                    {"violations": last_id}, count=50, block=5000
                )
                for stream_name, messages in results:
                    for msg_id, data in messages:
                        last_id = msg_id
                        subscribers = await get_subscribers_for_violation(data)
                        subject, html = format_violation_email(data)
                        for sub in subscribers:
                            success = await send_email(
                                client, api_key, from_email,
                                sub["email"], subject, html,
                            )
                            if not success:
                                logger.error(
                                    "Failed to send alert to %s", sub["email"]
                                )
            except Exception:
                logger.exception("Error in email alert loop")
                await asyncio.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
