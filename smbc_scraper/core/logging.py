# smbc_scraper/core/logging.py

import sys

from loguru import logger


def setup_logging(level: str = "INFO"):
    """Configures Loguru for console output."""
    logger.remove()  # Remove default handler
    logger.add(
        sys.stderr,
        level=level.upper(),
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )
    logger.info(f"Logging configured at level: {level}")
