"""Entry point for running ANPR processor as module."""

from src.ingestion.anpr_processor import main
import asyncio
import logging

logging.basicConfig(level=logging.INFO)
asyncio.run(main())
