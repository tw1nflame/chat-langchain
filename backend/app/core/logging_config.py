"""Configuration for application logging.
Writes logs to STDOUT/STDERR instead of files for container-friendly behavior.
"""

import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path

def setup_logging():
    """
    Настройка логгирования с ротацией файлов
    """
    # Основной логгер
    logger = logging.getLogger("chat_app")
    logger.setLevel(logging.INFO)
    
    # Убираем существующие хендлеры
    logger.handlers.clear()

    # Формат логов
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler for stdout (general info/debug)
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    logger.addHandler(console_handler)

    # Логгер для webhook'ов -> stdout as well
    webhook_logger = logging.getLogger("webhook")
    webhook_logger.setLevel(logging.DEBUG)
    webhook_logger.handlers.clear()
    webhook_console = logging.StreamHandler(stream=sys.stdout)
    webhook_console.setFormatter(formatter)
    webhook_console.setLevel(logging.DEBUG)
    webhook_logger.addHandler(webhook_console)

    # Логгер для ошибок -> stderr
    error_logger = logging.getLogger("errors")
    error_logger.setLevel(logging.ERROR)
    error_logger.handlers.clear()
    error_console = logging.StreamHandler(stream=sys.stderr)
    error_console.setFormatter(formatter)
    error_console.setLevel(logging.ERROR)
    error_logger.addHandler(error_console)

    return logger, webhook_logger, error_logger

# Инициализация логгеров
app_logger, webhook_logger, error_logger = setup_logging()
