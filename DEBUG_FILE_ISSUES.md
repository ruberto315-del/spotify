# Отладка проблем с файлами

## 🚨 Проблема
Бот находит и скачивает треки через Enhanced SoundCloud, но не отправляет их пользователю, показывая "❌ Не удалось найти или скачать трек."

## 🔍 Диагностика

### Добавлено подробное логирование:

1. **В `main.py` (process_track):**
   ```python
   logger.info(f"Download result: file_path={file_path}")
   logger.info(f"File exists: {os.path.exists(file_path)}")
   logger.info(f"File size: {os.path.getsize(file_path)} bytes")
   logger.info(f"Sending file: {file_path} (size: {file_size} bytes)")
   ```

2. **В `utils.py` (EnhancedSoundCloudProvider):**
   ```python
   logger.info(f"Enhanced SoundCloud: Downloaded '{title}', looking for file...")
   logger.info(f"Enhanced SoundCloud: Found file {file_path}")
   logger.info(f"Enhanced SoundCloud: New files found: {new_files}")
   ```

## 🔧 Исправления

### 1. Улучшена обработка файлов в EnhancedSoundCloudProvider:

- ✅ Добавлен поиск файлов по разным расширениям
- ✅ Добавлен поиск новых файлов в папке downloads
- ✅ Добавлена проверка размера файла (не пустой)
- ✅ Добавлено подробное логирование

### 2. Улучшена обработка ошибок в process_track:

- ✅ Добавлено логирование результата скачивания
- ✅ Добавлена проверка существования файла
- ✅ Добавлена обработка ошибок отправки файла
- ✅ Добавлено логирование успешной отправки

## 📊 Ожидаемые логи

После исправлений в логах должно быть:

```
Enhanced SoundCloud: Downloaded 'Track Name', looking for file...
Enhanced SoundCloud: Found file downloads/Track_Name.mp3
Enhanced SoundCloud: Download result: downloads/Track_Name.mp3
Download result: file_path=downloads/Track_Name.mp3
File exists: True
File size: 1234567 bytes
Sending file: downloads/Track_Name.mp3 (size: 1234567 bytes)
File sent successfully and removed: downloads/Track_Name.mp3
```

## 🚀 Развертывание

```bash
git add .
git commit -m "Fix file handling and add detailed logging for debugging"
git push origin main
```

## 🔍 Если проблема остается

Проверьте логи на:

1. **Файл скачивается, но не находится:**
   ```
   Enhanced SoundCloud: Downloaded 'Track Name', looking for file...
   Enhanced SoundCloud: New files found: set()
   ```

2. **Файл находится, но не отправляется:**
   ```
   Download result: file_path=downloads/Track_Name.mp3
   File exists: True
   Error sending file: [ошибка]
   ```

3. **Файл пустой:**
   ```
   Enhanced SoundCloud: Using new file downloads/Track_Name.mp3 (size: 0 bytes)
   Enhanced SoundCloud: File downloads/Track_Name.mp3 is empty
   ```

## 🛠️ Дополнительные исправления

Если проблема остается, можно добавить:

1. **Проверку прав доступа к файлам**
2. **Очистку папки downloads перед скачиванием**
3. **Альтернативные методы поиска файлов**
4. **Резервное копирование файлов перед отправкой**

## 📈 Мониторинг

После развертывания следите за логами:
- ✅ Файлы находятся и имеют размер > 0
- ✅ Файлы успешно отправляются пользователю
- ✅ Нет ошибок при отправке файлов
