# Directive: Send Alerts

## Goal
Deliver real-time violation alerts and traffic notifications to subscribers via multiple channels.

## Alert Channels

| Channel | Use Case | Library/Service |
|---------|----------|----------------|
| Email | Official notices, daily digests | SendGrid / AWS SES |
| SMS | Urgent alerts to authorities | Twilio |
| Push Notification | Mobile app users | Firebase Cloud Messaging |
| Webhook | Third-party integrations | HTTP POST with HMAC signing |
| Dashboard | Real-time web UI | WebSocket via FastAPI |

## Inputs
- Violation records from `violations` Redis Stream
- Subscriber preferences from PostgreSQL (`subscribers` table)
- Alert templates from `config/templates/`

## Execution Scripts
- `execution/send_email_alert.py` - Format and send email notifications
- `execution/send_sms_alert.py` - Send SMS via Twilio
- `execution/send_webhook.py` - Dispatch webhooks to registered endpoints
- `execution/build_daily_digest.py` - Compile and send daily summary reports

## Output
- Alert delivery receipts logged to `alert_log` table
- Failed deliveries queued for retry

## Edge Cases
- **Channel failure**: Retry 3x with exponential backoff, then fall back to next preferred channel
- **Rate limiting**: Respect per-channel rate limits; queue excess alerts
- **Subscriber opt-out**: Check opt-out status before every send; honor immediately
- **Batch alerts**: If >10 violations for same subscriber in 5 minutes, batch into single digest
- **Quiet hours**: Respect subscriber timezone and quiet hour preferences (default: 22:00-07:00 for non-urgent)

## Alert Priority Levels
1. **Critical** - No insurance, stolen vehicle match → immediate SMS + email
2. **High** - Speeding >20mph over, red light running → within 60 seconds
3. **Medium** - Bus lane, congestion charge → within 5 minutes
4. **Low** - Minor speeding, informational → daily digest only
