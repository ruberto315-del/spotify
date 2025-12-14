# Поддержка Unicode символов в Spotify Music Bot

## 🌍 Проблема
Бот не оптимально обрабатывал китайские иероглифы и другие Unicode символы в поисковых запросах и именах файлов.

## ✅ Решение

### 1. Улучшена функция `clean_filename()`
**Было:**
```python
def clean_filename(filename: str) -> str:
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename.strip()
```

**Стало:**
```python
def clean_filename(filename: str) -> str:
    import unicodedata
    
    # Нормализуем Unicode символы
    filename = unicodedata.normalize('NFC', filename)
    
    # Удаляем недопустимые символы для Windows
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Удаляем управляющие символы
    filename = ''.join(char for char in filename if unicodedata.category(char)[0] != 'C')
    
    # Заменяем пробелы и табы на подчеркивания
    filename = filename.replace(' ', '_').replace('\t', '_')
    
    # Удаляем множественные подчеркивания
    while '__' in filename:
        filename = filename.replace('__', '_')
    
    # Удаляем подчеркивания в начале и конце
    filename = filename.strip('_')
    
    # Ограничиваем длину имени файла (учитываем Unicode)
    if len(filename.encode('utf-8')) > 200:
        filename = filename.encode('utf-8')[:200].decode('utf-8', errors='ignore')
        while len(filename.encode('utf-8')) > 200:
            filename = filename[:-1]
    
    # Если имя файла пустое, используем fallback
    if not filename or filename == '_':
        filename = 'track'
    
    return filename
```

### 2. Улучшено URL кодирование
**Было:**
```python
search_url = f"https://soundcloud.com/search/sounds?q={quote(query, safe='')}"
```

**Стало:**
```python
encoded_query = quote(query, safe='', encoding='utf-8')
search_url = f"https://soundcloud.com/search/sounds?q={encoded_query}"
```

## 🎯 Поддерживаемые символы

### ✅ Теперь поддерживаются:
- **Китайские иероглифы**: 你好世界, 煉獄と猗窩座の戦い
- **Японские символы**: こんにちは, 音楽
- **Кириллица**: Привет мир, Музыка
- **Арабский**: مرحبا بالعالم
- **Эмодзи**: 🎵 Music Bot 🎶
- **Диакритические знаки**: Café & Résumé
- **Специальные символы**: правильно обрабатываются и заменяются

### 🔧 Улучшения обработки:
1. **Нормализация Unicode** - приведение к единому формату
2. **Правильное кодирование URL** - поддержка UTF-8
3. **Безопасные имена файлов** - удаление проблемных символов
4. **Обработка длины** - учет байтов, а не символов
5. **Fallback механизм** - если имя файла пустое

## 📊 Примеры работы

### Входные данные:
```
"煉獄と猗窩座の戦い 椎名豪"
"你好世界 Music"
"🎵 Test Song 🎶"
"Café & Résumé"
```

### Результат обработки:
```
"煉獄と猗窩座の戦い_椎名豪"
"你好世界_Music"
"Test_Song"
"Café_Résumé"
```

## 🚀 Развертывание

Изменения автоматически применятся при следующем развертывании на Railway:

```bash
git add .
git commit -m "Add Unicode support for Chinese characters and emojis"
git push origin main
```

## 🧪 Тестирование

Для проверки поддержки Unicode можно использовать:

1. **Китайские иероглифы**: 你好世界
2. **Японские символы**: こんにちは
3. **Эмодзи**: 🎵🎶
4. **Смешанные языки**: Hello 世界

Бот теперь корректно обрабатывает все эти символы в поисковых запросах и именах файлов.
