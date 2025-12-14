# Настройка Spotify API

Для полноценной работы бота необходимо настроить Spotify API:

## Шаги настройки:

1. Перейдите на [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)

2. Войдите в свой аккаунт Spotify

3. Нажмите "Create App"

4. Заполните форму:
   - App Name: `Spotify Music Bot` (или любое другое имя)
   - App Description: `Telegram bot for downloading music from Spotify links`
   - Website: `https://t.me/your_bot_username` (замените на имя вашего бота)
   - Redirect URI: `http://localhost:8080/callback`
   - API/SDKs: выберите "Web API"

5. После создания приложения:
   - Скопируйте `Client ID`
   - Нажмите "Show Client Secret" и скопируйте `Client Secret`

6. Обновите файл `.env`:
```
TELEGRAM_TOKEN=8313026423:AAHJVn0rWa1T-2wb4FBBQEqHdgKhe8mtiY4
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
```

## Важные замечания:

- Без Spotify API бот будет работать только с базовым парсингом ссылок
- С Spotify API бот получает полную информацию о треках, плейлистах и альбомах
- Spotify API бесплатный для некоммерческого использования
- Лимиты: 1000 запросов в час

## Альтернатива:

Если не хотите настраивать Spotify API, бот все равно будет работать, но с ограниченной функциональностью.
