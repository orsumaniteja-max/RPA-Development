from loguru import logger
import os

os.makedirs("reports/logs", exist_ok=True)

logger.add(
    "reports/logs/execution.log",
    rotation="10 MB",
    retention="10 days",
    level="INFO",
    format="{time} | {level} | {message}"
)