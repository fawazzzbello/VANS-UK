"""Entry point for running violation engine as module."""

from src.processing.violation_engine import main
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
asyncio.run(main())
