import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logger(name: str = "discord_bot") -> logging.Logger:
    """Configure and return the application logger."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = os.getenv("LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    if logger.handlers:
        return logger

    log_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(log_format)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "bot.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(log_format)

    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.propagate = False

    logger.debug("Logger initialized", extra={"log_level": log_level})
    return logger
