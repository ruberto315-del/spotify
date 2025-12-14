#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работоспособности Spotify Music Bot
"""

import os
import sys
from pathlib import Path

def test_imports():
    """Тестирует импорт всех модулей"""
    print("🔍 Проверяю импорты...")
    
    try:
        import aiogram
        print("✅ aiogram импортирован")
    except ImportError as e:
        print(f"❌ Ошибка импорта aiogram: {e}")
        return False
    
    try:
        import spotipy
        print("✅ spotipy импортирован")
    except ImportError as e:
        print(f"❌ Ошибка импорта spotipy: {e}")
        return False
    
    try:
        import yt_dlp
        print("✅ yt-dlp импортирован")
    except ImportError as e:
        print(f"❌ Ошибка импорта yt-dlp: {e}")
        return False
    
    try:
        from dotenv import load_dotenv
        print("✅ python-dotenv импортирован")
    except ImportError as e:
        print(f"❌ Ошибка импорта python-dotenv: {e}")
        return False
    
    return True

def test_files():
    """Проверяет наличие всех необходимых файлов"""
    print("\n📁 Проверяю файлы...")
    
    required_files = [
        'main.py',
        'utils.py', 
        'requirements.txt',
        'README.md'
    ]
    
    all_exist = True
    for file in required_files:
        if Path(file).exists():
            print(f"✅ {file} найден")
        else:
            print(f"❌ {file} не найден")
            all_exist = False
    
    return all_exist

def test_spotify_parser():
    """Тестирует парсер Spotify"""
    print("\n🎵 Тестирую парсер Spotify...")
    
    try:
        from utils import EnhancedSpotifyParser
        
        parser = EnhancedSpotifyParser()
        
        # Тестовые ссылки
        test_urls = [
            "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "https://open.spotify.com/album/1A2GTWGtFfWp7KSQTwWOyo"
        ]
        
        for url in test_urls:
            ids = parser.extract_ids_from_url(url)
            if any(ids.values()):
                print(f"✅ Парсинг {url} - OK")
            else:
                print(f"❌ Парсинг {url} - FAILED")
                return False
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка тестирования парсера: {e}")
        return False

def test_environment():
    """Проверяет переменные окружения"""
    print("\n🔧 Проверяю переменные окружения...")
    
    # Загружаем .env если есть
    if Path('.env').exists():
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Файл .env загружен")
    else:
        print("⚠️ Файл .env не найден")
    
    # Проверяем токен
    token = os.getenv('TELEGRAM_TOKEN')
    if token:
        print("✅ TELEGRAM_TOKEN установлен")
    else:
        print("❌ TELEGRAM_TOKEN не установлен")
        return False
    
    # Проверяем Spotify API (опционально)
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')
    
    if client_id and client_secret:
        print("✅ Spotify API настроен")
    else:
        print("⚠️ Spotify API не настроен (опционально)")
    
    return True

def main():
    """Основная функция тестирования"""
    print("🧪 Тестирование Spotify Music Bot")
    print("=" * 50)
    
    tests = [
        ("Импорты", test_imports),
        ("Файлы", test_files),
        ("Парсер Spotify", test_spotify_parser),
        ("Переменные окружения", test_environment)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n🔍 {test_name}:")
        if test_func():
            passed += 1
            print(f"✅ {test_name} - ПРОЙДЕН")
        else:
            print(f"❌ {test_name} - НЕ ПРОЙДЕН")
    
    print("\n" + "=" * 50)
    print(f"📊 Результат: {passed}/{total} тестов пройдено")
    
    if passed == total:
        print("🎉 Все тесты пройдены! Бот готов к запуску.")
        return True
    else:
        print("⚠️ Некоторые тесты не пройдены. Проверьте ошибки выше.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
