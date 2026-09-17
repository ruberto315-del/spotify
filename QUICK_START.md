# Быстрый запуск Spotify Music Bot

## Шаг 1: Установка зависимостей
```bash
pip install -r requirements.txt
```

## Шаг 2: Настройка токена
Создайте файл `.env` в корне проекта:
```
TELEGRAM_TOKEN=your_bot_token_from_botfather
```

## Шаг 3: Запуск бота
```bash
python main.py
```

Или используйте удобный скрипт:
```bash
python run.py
```

## Готово! 🎉

Бот готов к работе. Отправьте ему команду `/start` в Telegram.

## Дополнительная настройка (опционально)

Для получения полной информации о треках Spotify:
1. Перейдите на https://developer.spotify.com/dashboard
2. Создайте приложение
3. Получите Client ID и Client Secret
4. Добавьте их в `.env`:
```
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
```

## Тестирование

Отправьте боту ссылку на трек Spotify:
```
https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh
```

Бот должен найти и отправить MP3 файл!
