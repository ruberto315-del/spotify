#!/usr/bin/env python3
"""
Скрипт запуску Spotify Music Bot
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

def check_requirements():
    """Перевіряє наявність необхідних файлів та залежностей"""
    required_files = ['main.py', 'utils.py', 'requirements.txt']
    
    for file in required_files:
        if not Path(file).exists():
            print(f"❌ Файл {file} не знайдено!")
            return False
    
    # Проверяем переменные окружения
    if not os.getenv('TELEGRAM_TOKEN'):
        print("❌ TELEGRAM_TOKEN не встановлено!")
        print("Створіть файл .env та додайте токен бота")
        return False
    
    return True

def setup_logging():
    """Налаштовує логування"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def main():
    """Основна функція"""
    print("🎵 Spotify Music Bot")
    print("=" * 50)
    
    # Перевіряємо вимоги
    if not check_requirements():
        print("\n❌ Перевірка не пройдена. Переконайтеся, що всі файли на місці.")
        sys.exit(1)
    
    # Налаштовуємо логування
    setup_logging()
    
    # Створюємо папку для завантажень
    os.makedirs("downloads", exist_ok=True)
    
    print("✅ Всі перевірки пройдені")
    print("🚀 Запускаю бота...")
    
    try:
        # Импортируем и запускаем бота
        from main import main as bot_main
        asyncio.run(bot_main())
    except KeyboardInterrupt:
        print("\n👋 Бот зупинено користувачем")
    except Exception as e:
        print(f"\n❌ Помилка при запуску бота: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
