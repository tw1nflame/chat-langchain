"""
Конфигурация логгирования для приложения
"""

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

# Создаем директорию для логов
LOGS_DIR = Path(__file__).parent.parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

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
    
    # Хендлер для ротации файлов (хранение за 7 дней)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOGS_DIR / "chat_app.log",
        when='D',  # Ротация каждый день
        interval=1,  # Интервал в 1 день
        backupCount=7,  # Хранить файлы за 7 дней
        encoding='utf-8',
        utc=False
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    
    # Хендлер для консоли (отключен для продакшена)
    # console_handler = logging.StreamHandler()
    # console_handler.setFormatter(formatter)
    # console_handler.setLevel(logging.INFO)
    
    # Добавляем хендлеры
    logger.addHandler(file_handler)
    # logger.addHandler(console_handler)  # Отключаем консольный вывод
    
    # Логгер для webhook'ов
    webhook_logger = logging.getLogger("webhook")
    webhook_logger.setLevel(logging.DEBUG)
    
    # Отдельный файл для webhook логов
    webhook_file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOGS_DIR / "webhook.log",
        when='D',
        interval=1,
        backupCount=7,
        encoding='utf-8',
        utc=False
    )
    webhook_file_handler.setFormatter(formatter)
    webhook_file_handler.setLevel(logging.DEBUG)
    
    webhook_logger.addHandler(webhook_file_handler)
    # webhook_logger.addHandler(console_handler)  # Отключаем консольный вывод
    
    # Логгер для ошибок
    error_logger = logging.getLogger("errors")
    error_logger.setLevel(logging.ERROR)
    
    # Отдельный файл для ошибок
    error_file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=LOGS_DIR / "errors.log",
        when='D',
        interval=1,
        backupCount=7,
        encoding='utf-8',
        utc=False
    )
    error_file_handler.setFormatter(formatter)
    error_file_handler.setLevel(logging.ERROR)
    
    error_logger.addHandler(error_file_handler)
    # error_logger.addHandler(console_handler)  # Отключаем консольный вывод
    
    return logger, webhook_logger, error_logger

# Инициализация логгеров
app_logger, webhook_logger, error_logger = setup_logging()
