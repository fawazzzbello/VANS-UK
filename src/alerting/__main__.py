"""Entry point for running notification service as module."""

from src.alerting.notification_service import main
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
asyncio.run(main())
