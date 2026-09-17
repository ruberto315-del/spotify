FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание рабочей директории
WORKDIR /app

# Создаем non-root пользователя
RUN useradd --create-home --shell /usr/sbin/nologin botuser

# Копирование файлов зависимостей
COPY requirements.txt .

# Установка Python зависимостей
RUN pip install --upgrade pip \
 && pip install --upgrade --no-cache-dir -r requirements.txt

# Копирование исходного кода
COPY . .

# Создание папки для загрузок и отдаем владение non-root пользователю
RUN mkdir -p downloads && chown -R botuser:botuser /app

# Переменные окружения
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Запуск от name non-root пользователя
USER botuser

# Команда запуска
CMD ["python", "main.py"]
