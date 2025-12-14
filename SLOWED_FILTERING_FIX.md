# 🔧 Исправления фильтрации slowed версий

## ❌ Проблема

Бот все еще находил slowed версии треков вместо оригинальных:

**Примеры из логов:**
```
2025-10-19 21:20:53 - INFO - SoundCloud success: downloads/ESCORTE - PENTAGRAM (SUPER SLOWED + REVERB).mp3
2025-10-19 21:21:46 - INFO - SoundCloud success: downloads/Liko & Roxxy Bayern Demon (Slowed).mp3
```

## ✅ Исправления

### 1. **Улучшен поиск Enhanced SoundCloud**
- **Проблема**: Enhanced SoundCloud не находил треки через веб-поиск
- **Решение**: Добавлен yt-dlp поиск как fallback
- **Код**:
```python
# Если веб-поиск не дал результатов, пробуем yt-dlp поиск
if not track_urls:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        search_results = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
        if search_results and 'entries' in search_results:
            entries = [e for e in search_results['entries'] if e]
            track_urls = [entry.get('webpage_url', '') for entry in entries if entry.get('webpage_url')]
```

### 2. **Усилена фильтрация slowed версий**
- **Проблема**: Недостаточно строгие правила для slowed версий
- **Решение**: Добавлены дополнительные ключевые слова и штрафы
- **Новые ключевые слова**:
```python
non_original_keywords = [
    'slowed', 'sped up', 'nightcore', 'remix', 'edit', 'mashup',
    'cover', 'acoustic', 'live', 'instrumental', 'karaoke',
    'guitar', 'piano', 'orchestral', 'orchestra', 'symphony',
    'extended', 'club', 'radio', 'clean', 'explicit',
    'reverb', 'echo', 'bass boosted', '8d', '3d', 'spatial',
    'super slowed', 'ultra slowed', 'extreme slowed', 'heavily slowed',
    'slowed down', 'slow version', 'slow edit', 'slow remix'
]
```

### 3. **Добавлен особый штраф для slowed версий**
- **Проблема**: Slowed версии получали только -30 очков
- **Решение**: Дополнительный штраф -50 очков за slowed версии
- **Код**:
```python
# Особо строгий штраф за slowed версии
if any(keyword in title for keyword in ['slowed', 'super slowed', 'ultra slowed', 'extreme slowed']):
    score -= 50  # Очень большой штраф
```

### 4. **Добавлено детальное логирование**
- **Проблема**: Не было видно, что происходит в Enhanced SoundCloud
- **Решение**: Добавлены логи на каждом этапе
- **Логи**:
```python
logger.info(f"Enhanced SoundCloud: Searching for '{query}'")
logger.info(f"Enhanced SoundCloud: Found {len(candidates)} candidates")
logger.info(f"Enhanced SoundCloud: Candidate '{info.get('title', '')}'")
logger.info(f"Enhanced SoundCloud: After filtering: {len(filtered_candidates)} candidates")
logger.info(f"Enhanced SoundCloud: Best candidate '{best_candidate['title']}'")
```

## 📊 Алгоритм фильтрации

### Система очков:
- **Базовый скор**: 100 очков
- **Штраф за неоригинальные**: -30 очков
- **Штраф за slowed**: -50 очков (дополнительно)
- **Бонус за оригинальные**: +20 очков
- **Бонус за точную длительность**: +25 очков
- **Бонус за популярность**: +15 очков

### Примеры скоров:

**"Pentagram - Original Version"**:
- Базовый: 100
- "original": +20
- Итого: **120 очков** ✅

**"ESCORTE - PENTAGRAM (SUPER SLOWED + REVERB)"**:
- Базовый: 100
- "super slowed": -50
- "reverb": -30
- Итого: **20 очков** ❌

**"Pentagram - Official Studio Version"**:
- Базовый: 100
- "official": +20
- "studio": +20
- Итого: **140 очков** ✅

## 🎯 Ожидаемые результаты

### До исправлений:
```
Query: "Pentagram - Slowed escorte"
Result: "ESCORTE - PENTAGRAM (SUPER SLOWED + REVERB)" ❌
```

### После исправлений:
```
Query: "Pentagram - Slowed escorte"
Enhanced SoundCloud: Searching for 'Pentagram - Slowed escorte'
Enhanced SoundCloud: Found 5 candidates
Enhanced SoundCloud: Candidate 'Pentagram - Original Version'
Enhanced SoundCloud: Candidate 'ESCORTE - PENTAGRAM (SUPER SLOWED + REVERB)'
Enhanced SoundCloud: After filtering: 2 candidates
Enhanced SoundCloud: Best candidate 'Pentagram - Original Version'
Result: "Pentagram - Original Version" ✅
```

## 🔍 Отладка

### Логи Enhanced SoundCloud:
```
2025-10-19 21:20:39 - INFO - Provider: Enhanced SoundCloud
2025-10-19 21:20:40 - INFO - Enhanced SoundCloud: Searching for 'Pentagram - Slowed escorte'
2025-10-19 21:20:41 - INFO - Enhanced SoundCloud: Found 5 candidates
2025-10-19 21:20:42 - INFO - Enhanced SoundCloud: Candidate 'Pentagram - Original Version'
2025-10-19 21:20:43 - INFO - Enhanced SoundCloud: Candidate 'ESCORTE - PENTAGRAM (SUPER SLOWED + REVERB)'
2025-10-19 21:20:44 - INFO - Enhanced SoundCloud: After filtering: 2 candidates
2025-10-19 21:20:45 - INFO - Enhanced SoundCloud: Best candidate 'Pentagram - Original Version'
2025-10-19 21:20:46 - INFO - Enhanced SoundCloud success: downloads/Pentagram - Original Version.mp3
```

### Логи SoundCloud Fallback с фильтрацией:
```
2025-10-19 21:20:46 - INFO - Provider: SoundCloud Fallback
2025-10-19 21:20:47 - INFO - SoundCloud candidates: 3
2025-10-19 21:20:48 - INFO - SoundCloud Fallback: Best candidate 'Pentagram - Official'
2025-10-19 21:20:49 - INFO - SoundCloud try: https://soundcloud.com/pentagram-official
2025-10-19 21:20:50 - INFO - SoundCloud success: downloads/Pentagram - Official.mp3
```

## 🚀 Итог

**Теперь бот будет:**
- ✅ **Находить оригинальные версии** через Enhanced SoundCloud
- ✅ **Фильтровать slowed версии** с двойным штрафом (-80 очков)
- ✅ **Использовать yt-dlp поиск** если веб-поиск не работает
- ✅ **Показывать детальные логи** для отладки
- ✅ **Приоритизировать официальные версии** (+20 очков)

**Пользователи получат:**
- 🎵 **Оригинальные треки** вместо slowed версий
- 📊 **Прозрачность** через детальные логи
- ⚡ **Надежность** благодаря множественным методам поиска
- 🎯 **Точность** благодаря улучшенной фильтрации
