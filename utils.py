import os
import re
import asyncio
from typing import List, Optional, Dict
import aiohttp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
from typing import Tuple
import logging
logger = logging.getLogger(__name__)
from urllib.parse import quote
try:
    from rapidfuzz import fuzz
except ImportError:
    import difflib
    def fuzz(a, b):
        return int(difflib.SequenceMatcher(None, a, b).ratio() * 100)
from unicodedata import normalize
try:
    from unidecode import unidecode  # если есть
except ImportError:
    unidecode = None
from bs4 import BeautifulSoup
import yt_dlp  # нужно для корректного использования

async def _download_file(session: aiohttp.ClientSession, url: str, dest_path: str) -> Optional[str]:
    """Скачивает файл по URL в указанный путь"""
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            with open(dest_path, 'wb') as f:
                while True:
                    chunk = await resp.content.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        return dest_path
    except Exception:
        return None


class EnhancedSpotifyParser:
    """Улучшенный парсер Spotify с дополнительными функциями"""
    
    def __init__(self, client_id: str = None, client_secret: str = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.sp = None
        
        if client_id and client_secret:
            try:
                client_credentials_manager = SpotifyClientCredentials(
                    client_id=client_id,
                    client_secret=client_secret
                )
                self.sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
            except Exception as e:
                logger.error(f"Error initializing Spotify client: {e}")
    
    async def _resolve_short_url(self, url: str) -> str:
        """Разрешает короткие ссылки Spotify"""
        if 'spotify.link' in url or 'spoti.fi' in url:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, allow_redirects=True) as response:
                        if response.status == 200:
                            return str(response.url)
            except Exception as e:
                logger.error(f"Error resolving short URL: {e}")
        return url

    async def extract_ids_from_url(self, url: str) -> Dict[str, Optional[str]]:
        """Извлекает все возможные ID из ссылки Spotify"""
        # Сначала разрешаем короткие ссылки
        resolved_url = await self._resolve_short_url(url)
        
        patterns = {
            'track': [
                r'spotify:track:([a-zA-Z0-9]+)',
                r'https://open\.spotify\.com/track/([a-zA-Z0-9]+)',
                r'https://spotify\.com/track/([a-zA-Z0-9]+)'
            ],
            'playlist': [
                r'spotify:playlist:([a-zA-Z0-9]+)',
                r'https://open\.spotify\.com/playlist/([a-zA-Z0-9]+)',
                r'https://spotify\.com/playlist/([a-zA-Z0-9]+)'
            ],
            'album': [
                r'spotify:album:([a-zA-Z0-9]+)',
                r'https://open\.spotify\.com/album/([a-zA-Z0-9]+)',
                r'https://spotify\.com/album/([a-zA-Z0-9]+)'
            ],
            'artist': [
                r'spotify:artist:([a-zA-Z0-9]+)',
                r'https://open\.spotify\.com/artist/([a-zA-Z0-9]+)',
                r'https://spotify\.com/artist/([a-zA-Z0-9]+)'
            ]
        }
        
        result = {}
        for content_type, pattern_list in patterns.items():
            result[content_type] = None
            for pattern in pattern_list:
                match = re.search(pattern, resolved_url)
                if match:
                    result[content_type] = match.group(1)
                    break
        
        return result
    
    async def get_track_info(self, track_id: str) -> Optional[Dict]:
        """Получает подробную информацию о треке"""
        if not self.sp:
            return None
            
        try:
            track = self.sp.track(track_id)
            return {
                'id': track['id'],
                'name': track['name'],
                'artist': ', '.join([artist['name'] for artist in track['artists']]),
                'artists': [artist['name'] for artist in track['artists']],
                'album': track['album']['name'],
                'album_artists': [artist['name'] for artist in track['album']['artists']],
                'duration': track['duration_ms'] // 1000,
                'duration_formatted': self._format_duration(track['duration_ms']),
                'url': track['external_urls']['spotify'],
                'preview_url': track['preview_url'],
                'popularity': track['popularity'],
                'explicit': track['explicit'],
                'release_date': track['album']['release_date'],
                'genres': track['album'].get('genres', [])
            }
        except Exception as e:
            logger.error(f"Error getting track info: {e}")
            return None
    
    async def get_playlist_info(self, playlist_id: str) -> Optional[Dict]:
        """Получает информацию о плейлисте"""
        if not self.sp:
            return None
            
        try:
            playlist = self.sp.playlist(playlist_id)
            tracks = []
            
            # Получаем все треки из плейлиста
            results = self.sp.playlist_tracks(playlist_id)
            tracks.extend(results['items'])
            
            # Если есть следующая страница, загружаем её
            while results['next']:
                results = self.sp.next(results)
                tracks.extend(results['items'])
            
            track_list = []
            for item in tracks:
                track = item['track']
                if track and track['type'] == 'track':
                    track_list.append({
                        'id': track['id'],
                        'name': track['name'],
                        'artist': ', '.join([artist['name'] for artist in track['artists']]),
                        'artists': [artist['name'] for artist in track['artists']],
                        'album': track['album']['name'],
                        'duration': track['duration_ms'] // 1000,
                        'duration_formatted': self._format_duration(track['duration_ms']),
                        'url': track['external_urls']['spotify'],
                        'popularity': track['popularity']
                    })
            
            return {
                'id': playlist['id'],
                'name': playlist['name'],
                'description': playlist['description'],
                'owner': playlist['owner']['display_name'],
                'tracks_count': playlist['tracks']['total'],
                'url': playlist['external_urls']['spotify'],
                'tracks': track_list
            }
        except Exception as e:
            logger.error(f"Error getting playlist info: {e}")
            return None
    
    async def get_album_info(self, album_id: str) -> Optional[Dict]:
        """Получает информацию об альбоме"""
        if not self.sp:
            return None
            
        try:
            album = self.sp.album(album_id)
            tracks = []
            
            for track in album['tracks']['items']:
                tracks.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artist': ', '.join([artist['name'] for artist in track['artists']]),
                    'artists': [artist['name'] for artist in track['artists']],
                    'duration': track['duration_ms'] // 1000,
                    'duration_formatted': self._format_duration(track['duration_ms']),
                    'url': f"https://open.spotify.com/track/{track['id']}"
                })
            
            return {
                'id': album['id'],
                'name': album['name'],
                'artist': ', '.join([artist['name'] for artist in album['artists']]),
                'artists': [artist['name'] for artist in album['artists']],
                'release_date': album['release_date'],
                'total_tracks': album['total_tracks'],
                'url': album['external_urls']['spotify'],
                'tracks': tracks
            }
        except Exception as e:
            logger.error(f"Error getting album info: {e}")
            return None
    
    def _format_duration(self, duration_ms: int) -> str:
        """Форматирует длительность в читаемый вид"""
        seconds = duration_ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"
    
    def create_search_query(self, track_info: Dict) -> str:
        """Создает поисковый запрос для поиска музыки"""
        # Пробуем разные варианты поискового запроса
        queries = [
            f"{track_info['name']} {track_info['artist']}",
            f"{track_info['name']} {track_info['artists'][0]}",
            f"{track_info['name']} {track_info['album']}",
            f"{track_info['name']} {track_info['artist']} lyrics",
            f"{track_info['name']} {track_info['artist']} official"
        ]
        return queries[0]  # Возвращаем основной запрос


class MusicSearchEngine:
    """Класс для поиска музыки в различных источниках"""
    
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_youtube(self, query: str, max_results: int = 5) -> List[Dict]:
        """Ищет видео на YouTube"""
        try:
            # Здесь можно добавить интеграцию с YouTube API
            # Пока используем yt-dlp для поиска
            import yt_dlp
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_results = ydl.extract_info(
                    f"ytsearch{max_results}:{query}",
                    download=False
                )
                
                if not search_results or 'entries' not in search_results:
                    return []
                
                results = []
                for entry in search_results['entries']:
                    if entry:
                        results.append({
                            'title': entry.get('title', ''),
                            'url': entry.get('url', ''),
                            'duration': entry.get('duration', 0),
                            'view_count': entry.get('view_count', 0)
                        })
                
                return results
                
        except Exception as e:
            logger.error(f"Error searching YouTube: {e}")
            return []
    
    async def search_soundcloud(self, query: str) -> List[Dict]:
        """Ищет треки на SoundCloud"""
        # Здесь можно добавить интеграцию с SoundCloud API
        return []
    
    async def get_best_match(self, track_info: Dict, search_results: List[Dict]) -> Optional[Dict]:
        """Выбирает лучший результат поиска"""
        if not search_results:
            return None
        
        # Простая логика выбора лучшего результата
        # Можно улучшить, добавив сравнение названий и исполнителей
        best_match = search_results[0]
        
        # Проверяем длительность (если доступна)
        if track_info.get('duration') and best_match.get('duration'):
            duration_diff = abs(track_info['duration'] - best_match['duration'])
            if duration_diff > 30:  # Если разница больше 30 секунд
                # Ищем более подходящий по длительности
                for result in search_results[1:]:
                    if result.get('duration'):
                        new_diff = abs(track_info['duration'] - result['duration'])
                        if new_diff < duration_diff:
                            best_match = result
                            duration_diff = new_diff
        
        return best_match


def clean_filename(filename: str) -> str:
    """Очищает имя файла от недопустимых символов с поддержкой Unicode"""
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
        # Обрезаем по байтам, а не по символам
        filename = filename.encode('utf-8')[:200].decode('utf-8', errors='ignore')
        # Убираем неполные символы в конце
        while len(filename.encode('utf-8')) > 200:
            filename = filename[:-1]
    
    # Если имя файла пустое, используем fallback
    if not filename or filename == '_':
        filename = 'track'
    
    return filename


def format_file_size(size_bytes: int) -> str:
    """Форматирует размер файла в читаемый вид"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


class JioSaavnProvider:
    """Онлайн-провайдер: поиск и скачивание MP3 через неофициальное API JioSaavn"""

    BASE = "https://saavn.me"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Ищет треки в JioSaavn по запросу"""
        try:
            assert self.session is not None
            params = {"query": query}
            async with self.session.get(f"{self.BASE}/search/songs", params=params, timeout=30) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                results = data.get("data", []) or []
                songs = results[:limit]
                parsed: List[Dict] = []
                for s in songs:
                    parsed.append({
                        "id": s.get("id"),
                        "title": s.get("name") or s.get("title"),
                        "primaryArtists": s.get("primaryArtists", ""),
                        "image": s.get("image"),
                        "album": s.get("album"),
                        "duration": int(s.get("duration", 0)) if s.get("duration") else 0
                    })
                return parsed
        except Exception:
            return []

    async def get_song(self, song_id: str) -> Optional[Dict]:
        try:
            assert self.session is not None
            params = {"id": song_id}
            async with self.session.get(f"{self.BASE}/songs", params=params, timeout=30) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                songs = data.get("data", []) or []
                return songs[0] if songs else None
        except Exception:
            return None

    async def download_best(self, query: str) -> Optional[str]:
        """Ищет трек и скачивает лучшую доступную версию MP3. Возвращает путь к файлу."""
        try:
            results = await self.search(query, limit=5)
            if not results:
                return None
            # Берем первый кандидат (можно улучшить по совпадению артиста/длительности)
            candidate = results[0]
            song = await self.get_song(candidate["id"]) if candidate.get("id") else None
            if not song:
                return None
            # Ищем ссылку на 320/160/96 kbps
            media_urls = []
            for key in ("downloadUrl", "moreInfo"):
                if isinstance(song.get(key), list):
                    media_urls.extend(song.get(key) or [])
                elif isinstance(song.get(key), dict):
                    # иногда аудиоссылки в moreInfo.download_links и т.п.
                    dl = song[key].get("download_links") if song[key] else None
                    if isinstance(dl, list):
                        media_urls.extend(dl)
            # Плоский список url-строк
            urls: List[str] = []
            for item in media_urls:
                if isinstance(item, dict):
                    u = item.get("link") or item.get("url")
                    if u:
                        urls.append(u)
                elif isinstance(item, str):
                    urls.append(item)
            # Фильтруем mp3 ссылки, предпочитая 320
            preferred = [u for u in urls if "320" in u]
            if not preferred:
                preferred = [u for u in urls if u.endswith(".mp3")]
            dl_url = preferred[0] if preferred else (urls[0] if urls else None)
            if not dl_url:
                return None
            safe_name = clean_filename(f"{candidate['title']} - {candidate.get('primaryArtists','')}".strip())
            dest = os.path.join("downloads", f"{safe_name}.mp3")
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, dl_url, dest)
            return path
        except Exception:
            return None


class SoundCloudProvider:
    """Онлайн-провайдер: поиск треков на SoundCloud (через HTML) и скачивание через yt-dlp"""

    SEARCH_URL = "https://soundcloud.com/search/sounds"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        })
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search_urls(self, query: str, limit: int = 3) -> List[str]:
        try:
            assert self.session is not None
            params = {"q": query}
            async with self.session.get(self.SEARCH_URL, params=params, timeout=30) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
            # Простейший парсинг ссылок на треки вида href="/artist/track"
            import re as _re
            candidates = []
            for m in _re.finditer(r'href="(/[^"\s]+/[^"\s]+)"', html):
                path = m.group(1)
                # отбрасываем плейлисты и всякое
                if "/sets/" in path or path.startswith("/search") or "/popular/" in path:
                    continue
                if path.count('/') >= 2:  # обычно /artist/track
                    url = f"https://soundcloud.com{path}"
                    if url not in candidates and not url.endswith("/popular/searches"):
                        candidates.append(url)
                if len(candidates) >= limit:
                    break
            return candidates
        except Exception:
            return []


class AlternativeMusicProvider:
    """Альтернативный провайдер: поиск через различные музыкальные API"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str) -> Optional[str]:
        """Ищет трек через альтернативные источники"""
        try:
            # Попробуем через Last.fm API (бесплатный)
            lastfm_results = await self._search_lastfm(query)
            if lastfm_results:
                # Попробуем скачать через yt-dlp с найденной информацией
                return await self._download_via_ytdl(query, lastfm_results)
            
            # Если Last.fm не сработал, попробуем другие методы
            return await self._fallback_search(query)
            
        except Exception as e:
            logger.error(f"AlternativeMusicProvider error: {e}")
            return None
    
    async def _search_lastfm(self, query: str) -> Optional[Dict]:
        """Поиск через Last.fm API"""
        try:
            # Используем публичный API Last.fm
            url = "http://ws.audioscrobbler.com/2.0/"
            params = {
                'method': 'track.search',
                'track': query,
                'api_key': 'c8b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0',  # Публичный ключ
                'format': 'json',
                'limit': 1
            }
            
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tracks = data.get('results', {}).get('trackmatches', {}).get('track', [])
                    if tracks:
                        return tracks[0] if isinstance(tracks, list) else tracks
        except Exception:
            pass
        return None
    
    async def _download_via_ytdl(self, query: str, track_info: Dict) -> Optional[str]:
        """Скачивание через yt-dlp с улучшенным запросом"""
        try:
            # Формируем улучшенный поисковый запрос
            artist = track_info.get('artist', '')
            track_name = track_info.get('name', '')
            enhanced_query = f"{artist} {track_name} official audio"
            
            # Используем yt-dlp с минимальными настройками
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15'
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'android_music'],
                    }
                },
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_results = ydl.extract_info(
                    f"ytsearch5:{enhanced_query}",
                    download=False
                )
                
                if search_results and 'entries' in search_results:
                    entries = [e for e in search_results['entries'] if e]
                    if entries:
                        # Выбираем первое видео
                        video = entries[0]
                        video_url = video.get('webpage_url') or video.get('url')
                        if video_url:
                            # Скачиваем выбранное видео
                            ydl.download([video_url])
                            
                            # Ищем скачанный файл
                            title = clean_filename(video.get('title', 'Unknown'))
                            for ext in ['mp3', 'webm', 'm4a']:
                                file_path = f"downloads/{title}.{ext}"
                                if os.path.exists(file_path):
                                    return file_path
        except Exception:
            pass
        return None
    
    async def _fallback_search(self, query: str) -> Optional[str]:
        """Резервный поиск через простые методы"""
        try:
            # Попробуем поиск через DuckDuckGo (может найти прямые ссылки)
            search_url = f"https://html.duckduckgo.com/html/?q={query}+mp3+download"
            
            async with self.session.get(search_url, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Простой поиск ссылок на MP3
                    import re
                    mp3_links = re.findall(r'href="([^"]*\.mp3[^"]*)"', html)
                    if mp3_links:
                        # Попробуем скачать первую найденную ссылку
                        mp3_url = mp3_links[0]
                        if mp3_url.startswith('http'):
                            safe_name = clean_filename(query)
                            dest = os.path.join("downloads", f"{safe_name}.mp3")
                            async with aiohttp.ClientSession() as s:
                                path = await _download_file(s, mp3_url, dest)
                            return path
        except Exception:
            pass
        return None


class BandcampProvider:
    """Провайдер для поиска и скачивания с Bandcamp"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str) -> Optional[str]:
        """Ищет треки на Bandcamp и скачивает через yt-dlp"""
        try:
            # Поиск на Bandcamp
            search_url = f"https://bandcamp.com/search?q={query}"
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            
            # Парсим ссылки на треки
            import re
            track_links = re.findall(r'href="(https://[^"]+\.bandcamp\.com/track/[^"]+)"', html)
            
            if not track_links:
                return None
            
            # Пробуем скачать первый найденный трек
            track_url = track_links[0]
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(track_url, download=True)
                if info:
                    title = clean_filename(info.get('title', 'Unknown'))
                    for ext in ['mp3', 'webm', 'm4a']:
                        file_path = f"downloads/{title}.{ext}"
                        if os.path.exists(file_path):
                            return file_path
        except Exception as e:
            logger.error(f"BandcampProvider error: {e}")
        return None


class ArchiveOrgProvider:
    """Провайдер для поиска в Internet Archive (Archive.org)"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str) -> Optional[str]:
        """Ищет аудио в Internet Archive"""
        try:
            # Поиск в Internet Archive
            search_url = "https://archive.org/advancedsearch.php"
            params = {
                'q': f'collection:audio AND title:({query})',
                'fl': 'identifier,title,creator',
                'rows': 5,
                'output': 'json'
            }
            
            async with self.session.get(search_url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            
            docs = data.get('response', {}).get('docs', [])
            if not docs:
                return None
            
            # Берем первый результат
            item = docs[0]
            identifier = item.get('identifier')
            if not identifier:
                return None
            
            # Получаем прямую ссылку на MP3
            item_url = f"https://archive.org/details/{identifier}"
            async with self.session.get(item_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            
            # Ищем прямые ссылки на MP3
            import re
            mp3_links = re.findall(r'href="(https://[^"]*\.mp3[^"]*)"', html)
            
            if mp3_links:
                mp3_url = mp3_links[0]
                title = clean_filename(item.get('title', query))
                dest = os.path.join("downloads", f"{title}.mp3")
                
                async with aiohttp.ClientSession() as s:
                    path = await _download_file(s, mp3_url, dest)
                return path
        except Exception as e:
            logger.error(f"ArchiveOrgProvider error: {e}")
        return None


class FreeMusicArchiveProvider:
    """Провайдер для Free Music Archive"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str) -> Optional[str]:
        """Ищет треки в Free Music Archive"""
        try:
            # Поиск в FMA
            search_url = f"https://freemusicarchive.org/search?adv=1&music-filter-genre=all&music-filter-artist={query}"
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            
            # Парсим ссылки на треки
            import re
            track_links = re.findall(r'href="(/music/[^"]+)"', html)
            
            if not track_links:
                return None
            
            # Берем первый трек
            track_path = track_links[0]
            track_url = f"https://freemusicarchive.org{track_path}"
            
            async with self.session.get(track_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            
            # Ищем прямые ссылки на MP3
            mp3_links = re.findall(r'href="(https://[^"]*\.mp3[^"]*)"', html)
            
            if mp3_links:
                mp3_url = mp3_links[0]
                title = clean_filename(query)
                dest = os.path.join("downloads", f"{title}.mp3")
                
                async with aiohttp.ClientSession() as s:
                    path = await _download_file(s, mp3_url, dest)
                return path
        except Exception as e:
            logger.error(f"FreeMusicArchiveProvider error: {e}")
        return None


class JamendoProvider:
    """Провайдер для Jamendo (бесплатная музыка)"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str) -> Optional[str]:
        """Ищет треки в Jamendo"""
        try:
            # Поиск через Jamendo API
            api_url = "https://api.jamendo.com/v3.0/tracks/"
            params = {
                'client_id': 'jamendotest',  # Публичный тестовый ключ
                'format': 'json',
                'search': query,
                'limit': 5,
                'include': 'musicinfo'
            }
            
            async with self.session.get(api_url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
            
            tracks = data.get('results', [])
            if not tracks:
                return None
            
            # Берем первый трек
            track = tracks[0]
            audio_url = track.get('audio')
            if not audio_url:
                return None
            
            title = clean_filename(f"{track.get('name', 'Unknown')} - {track.get('artist_name', 'Unknown')}")
            dest = os.path.join("downloads", f"{title}.mp3")
            
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, audio_url, dest)
            return path
        except Exception as e:
            logger.error(f"JamendoProvider error: {e}")
        return None


class MixcloudProvider:
    """Провайдер для Mixcloud (миксы и подкасты)"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str) -> Optional[str]:
        """Ищет миксы на Mixcloud и скачивает через yt-dlp"""
        try:
            # Поиск на Mixcloud
            search_url = f"https://www.mixcloud.com/search/?q={query}"
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            
            # Парсим ссылки на миксы
            import re
            mix_links = re.findall(r'href="(/[^"]+/[^"]+/)"', html)
            
            if not mix_links:
                return None
            
            # Берем первый микс
            mix_path = mix_links[0]
            mix_url = f"https://www.mixcloud.com{mix_path}"
            
            # Скачиваем через yt-dlp
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 100 * 1024 * 1024,  # Mixcloud может быть больше
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(mix_url, download=True)
                if info:
                    title = clean_filename(info.get('title', 'Unknown'))
                    for ext in ['mp3', 'webm', 'm4a']:
                        file_path = f"downloads/{title}.{ext}"
                        if os.path.exists(file_path):
                            return file_path
        except Exception as e:
            logger.error(f"MixcloudProvider error: {e}")
        return None


class VKMusicProvider:
    """Провайдер для поиска музыки в VK"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str, orig_title: Optional[str]=None, orig_artist: Optional[str]=None) -> Optional[str]:
        """Ищет треки в VK и скачивает лучший по fuzzy сопоставлению"""
        try:
            import yt_dlp
            import re
            # Поиск в VK через поисковую систему
            search_url = f"https://vk.com/search?c[q]={quote(query, safe='')}&c[section]=audio"
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            audio_links = re.findall(r'href="(/audio[^"]+)"', html)
            logger.info(f"[VK] Candidates found: {len(audio_links)} links -> {audio_links[:5]}")
            if not audio_links:
                logger.info(f"[VK] No audio candidates for query: {query}")
                return None
            candidates = []
            for path in audio_links[:5]:
                url = f"https://vk.com{path}"
                async with self.session.get(url, timeout=15) as page:
                    if page.status != 200:
                        continue
                    content = await page.text()
                    # Метаинфо — парсим title
                    soup = BeautifulSoup(content, "html.parser")
                    title = soup.title.text.strip() if soup.title else ''
                    # В title VK часто "Artist - Track Title"
                    parts = title.split(' - ', 1)
                    artist = parts[0] if len(parts)>1 else ''
                    track = parts[1] if len(parts)>1 else title
                    score = 0
                    if orig_title and orig_artist:
                        score = fuzz.ratio(track.lower(), orig_title.lower()) + fuzz.ratio(artist.lower(), orig_artist.lower())
                    elif orig_title:
                        score = fuzz.ratio(track.lower(), orig_title.lower())
                    else:
                        score = fuzz.ratio(title.lower(), query.lower())
                    candidates.append({'url': url, 'score': score, 'title': title})
            best = max(candidates, key=lambda c: c['score'], default=None)
            if not best or best['score'] < 120:
                logger.info(f"[VK] No good match, best scored {best['score'] if best else None}, query '{query}'")
                return None
            audio_url = best['url']
            logger.info(f"[VK] Downloading best match: {audio_url} (score={best['score']})")
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(audio_url, download=True)
                if info:
                    title = clean_filename(info.get('title', 'Unknown'))
                    for ext in ['mp3', 'webm', 'm4a']:
                        file_path = f"downloads/{title}.{ext}"
                        if os.path.exists(file_path):
                            return file_path
        except Exception as e:
            logger.error(f"VKMusicProvider error: {e}")
        return None


class YandexMusicProvider:
    """Провайдер для поиска в Яндекс.Музыке"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str, orig_title: Optional[str]=None, orig_artist: Optional[str]=None) -> Optional[str]:
        """Ищет треки в Яндекс.Музыке по fuzzy совпадению"""
        try:
            import yt_dlp
            import re
            search_url = f"https://music.yandex.ru/search?text={quote(query, safe='')}"
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            track_links = re.findall(r'href="(/track/[^"]+)"', html)
            logger.info(f"[Yandex] Candidates found: {len(track_links)} links -> {track_links[:5]}")
            if not track_links:
                logger.info(f"[Yandex] No track candidates for query: {query}")
                return None
            candidates = []
            for path in track_links[:5]:
                url = f"https://music.yandex.ru{path}"
                async with self.session.get(url, timeout=15) as page:
                    if page.status != 200:
                        continue
                    content = await page.text()
                    soup = BeautifulSoup(content, "html.parser")
                    title = soup.title.text.strip() if soup.title else ''
                    parts = title.split(' — ', 1)
                    artist = parts[0] if len(parts)>1 else ''
                    track = parts[1] if len(parts)>1 else title
                    score = 0
                    if orig_title and orig_artist:
                        score = fuzz.ratio(track.lower(), orig_title.lower()) + fuzz.ratio(artist.lower(), orig_artist.lower())
                    elif orig_title:
                        score = fuzz.ratio(track.lower(), orig_title.lower())
                    else:
                        score = fuzz.ratio(title.lower(), query.lower())
                    candidates.append({'url': url, 'score': score, 'title': title})
            best = max(candidates, key=lambda c: c['score'], default=None)
            if not best or best['score'] < 120:
                logger.info(f"[Yandex] No good match, best scored {best['score'] if best else None}, query '{query}'")
                return None
            track_url = best['url']
            logger.info(f"[Yandex] Downloading best match: {track_url} (score={best['score']})")
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(track_url, download=True)
                if info:
                    title = clean_filename(info.get('title', 'Unknown'))
                    for ext in ['mp3', 'webm', 'm4a']:
                        file_path = f"downloads/{title}.{ext}"
                        if os.path.exists(file_path):
                            return file_path
        except Exception as e:
            logger.error(f"YandexMusicProvider error: {e}")
        return None


class DeezerProvider:
    """Провайдер для поиска в Deezer"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_and_download(self, query: str, orig_title: Optional[str]=None, orig_artist: Optional[str]=None) -> Optional[str]:
        """Ищет треки в Deezer по fuzzy совпадению"""
        try:
            import yt_dlp
            import re
            search_url = f"https://www.deezer.com/search/{quote(query, safe='')}"
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            track_links = re.findall(r'href="(/track/[^"]+)"', html)
            logger.info(f"[Deezer] Candidates found: {len(track_links)} links -> {track_links[:5]}")
            if not track_links:
                logger.info(f"[Deezer] No track candidates for query: {query}")
                return None
            candidates = []
            for path in track_links[:5]:
                url = f"https://www.deezer.com{path}"
                async with self.session.get(url, timeout=15) as page:
                    if page.status != 200:
                        continue
                    content = await page.text()
                    soup = BeautifulSoup(content, "html.parser")
                    title = soup.title.text.strip() if soup.title else ''
                    # Deezer: обычно title это "Artist - Track Title | Deezer"
                    base_title = title.split('|')[0].strip()
                    parts = base_title.split(' - ', 1)
                    artist = parts[0] if len(parts)>1 else ''
                    track = parts[1] if len(parts)>1 else base_title
                    score = 0
                    if orig_title and orig_artist:
                        score = fuzz.ratio(track.lower(), orig_title.lower()) + fuzz.ratio(artist.lower(), orig_artist.lower())
                    elif orig_title:
                        score = fuzz.ratio(track.lower(), orig_title.lower())
                    else:
                        score = fuzz.ratio(title.lower(), query.lower())
                    candidates.append({'url': url, 'score': score, 'title': title})
            best = max(candidates, key=lambda c: c['score'], default=None)
            if not best or best['score'] < 120:
                logger.info(f"[Deezer] No good match, best scored {best['score'] if best else None}, query '{query}'")
                return None
            track_url = best['url']
            logger.info(f"[Deezer] Downloading best match: {track_url} (score={best['score']})")
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(track_url, download=True)
                if info:
                    title = clean_filename(info.get('title', 'Unknown'))
                    for ext in ['mp3', 'webm', 'm4a']:
                        file_path = f"downloads/{title}.{ext}"
                        if os.path.exists(file_path):
                            return file_path
        except Exception as e:
            logger.error(f"DeezerProvider error: {e}")
        return None


class AlternativeYouTubeProvider:
    """Альтернативный YouTube провайдер с другими настройками обхода блокировок"""
    
    async def search_and_download(self, query: str) -> Optional[str]:
        """Ищет треки через альтернативные YouTube методы"""
        try:
            import random
            import yt_dlp
            
            # Альтернативные настройки для обхода блокировок
            alt_user_agents = [
                'Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1',
                'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/119.0'
            ]
            
            ydl_opts = {
                'format': 'worstaudio/worst',  # Берем худшее качество для обхода блокировок
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',  # Низкое качество для обхода
                }],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 25 * 1024 * 1024,  # Меньший лимит
                'http_headers': {
                    'User-Agent': random.choice(alt_user_agents),
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['tv_embedded', 'tv', 'ios'],
                        'skip': ['dash', 'hls'],
                    }
                },
                'retries': 3,
                'fragment_retries': 3,
                'retry_sleep': 1,
                'sleep_interval': 0.5,
                'geo_bypass': True,
                'geo_bypass_country': 'RU',  # Другая страна
                'no_check_certificate': True,
                'ignoreerrors': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Пробуем разные поисковые запросы
                search_queries = [
                    f"{query} official",
                    f"{query} audio",
                    f"{query} music",
                    f"{query} song"
                ]
                
                for search_query in search_queries:
                    try:
                        search_results = ydl.extract_info(
                            f"ytsearch3:{search_query}",
                            download=False
                        )
                        
                        if search_results and 'entries' in search_results:
                            entries = [e for e in search_results['entries'] if e]
                            if entries:
                                # Берем первое видео
                                video = entries[0]
                                video_url = video.get('webpage_url') or video.get('url')
                                if video_url:
                                    ydl.download([video_url])
                                    
                                    # Ищем скачанный файл
                                    title = clean_filename(video.get('title', 'Unknown'))
                                    for ext in ['mp3', 'webm', 'm4a']:
                                        file_path = f"downloads/{title}.{ext}"
                                        if os.path.exists(file_path):
                                            return file_path
                    except Exception:
                        continue
                        
        except Exception as e:
            logger.error(f"AlternativeYouTubeProvider error: {e}")
        return None


class YTMusicProvider:
    """Провайдер поиска в YouTube Music через ytmusicapi (без ключа)"""

    def __init__(self):
        from ytmusicapi import YTMusic
        # Анонимная инициализация (без cookies) — для поиска хватает
        self.yt = YTMusic()

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        try:
            results = self.yt.search(query, filter="songs", limit=limit) or []
            parsed: List[Dict] = []
            for r in results:
                title = r.get("title")
                artists = ", ".join([a.get("name") for a in (r.get("artists") or []) if a.get("name")])
                dur = r.get("duration")  # формат mm:ss
                seconds = 0
                if isinstance(dur, str) and ":" in dur:
                    try:
                        m, s = dur.split(":")
                        seconds = int(m) * 60 + int(s)
                    except Exception:
                        seconds = 0
                video_id = r.get("videoId")
                if video_id:
                    parsed.append({
                        "title": title,
                        "artist": artists,
                        "duration": seconds,
                        "url": f"https://music.youtube.com/watch?v={video_id}",
                    })
            return parsed
        except Exception:
            return []

    async def download_best(self, query: str) -> Optional[str]:
        """Ищет трек и скачивает лучшую доступную версию MP3. Возвращает путь к файлу."""
        try:
            results = await self.search(query, limit=5)
            if not results:
                return None
            # Берем первый кандидат (можно улучшить по совпадению артиста/длительности)
            candidate = results[0]
            song = await self.get_song(candidate["id"]) if candidate.get("id") else None
            if not song:
                return None
            # Ищем ссылку на 320/160/96 kbps
            media_urls = []
            for key in ("downloadUrl", "moreInfo"):
                if isinstance(song.get(key), list):
                    media_urls.extend(song.get(key) or [])
                elif isinstance(song.get(key), dict):
                    # иногда аудиоссылки в moreInfo.download_links и т.п.
                    dl = song[key].get("download_links") if song[key] else None
                    if isinstance(dl, list):
                        media_urls.extend(dl)
            # Плоский список url-строк
            urls: List[str] = []
            for item in media_urls:
                if isinstance(item, dict):
                    u = item.get("link") or item.get("url")
                    if u:
                        urls.append(u)
                elif isinstance(item, str):
                    urls.append(item)
            # Фильтруем mp3 ссылки, предпочитая 320
            preferred = [u for u in urls if "320" in u]
            if not preferred:
                preferred = [u for u in urls if u.endswith(".mp3")]
            dl_url = preferred[0] if preferred else (urls[0] if urls else None)
            if not dl_url:
                return None
            safe_name = clean_filename(f"{candidate['title']} - {candidate.get('primaryArtists','')}".strip())
            dest = os.path.join("downloads", f"{safe_name}.mp3")
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, dl_url, dest)
            return path
        except Exception:
            return None


class AudiomackProvider:
    """Провайдер для поиска и скачивания с Audiomack"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://audiomack.com/search?q={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            track_links = re.findall(r'href="(/song/[\w\-]+/[\w\-]+)"', html)
            logger.info(f"[Audiomack] Candidates found: {len(track_links)} links -> {track_links[:3]}")
            if not track_links:
                logger.info(f"[Audiomack] No track candidates for query: {query}")
                return None
            for path in track_links[:3]:
                url = f'https://audiomack.com{path}'
                logger.info(f"[Audiomack] Trying download: {url}")
                try:
                    import yt_dlp
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': f'downloads/%(title)s.%(ext)s',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'max_filesize': 50 * 1024 * 1024,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        if info:
                            title = clean_filename(info.get('title', 'Unknown'))
                            for ext in ['mp3', 'webm', 'm4a']:
                                file_path = f"downloads/{title}.{ext}"
                                if os.path.exists(file_path):
                                    return file_path
                except Exception as ex:
                    logger.error(f"Audiomack candidate failed: {ex}")
                    continue
        except Exception as e:
            logger.error(f"AudiomackProvider error: {e}")
        return None


class MusopenProvider:
    """Провайдер для скачивания классики с musopen.org"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://musopen.org/music/search/?q={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=20) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            track_links = re.findall(r'href=["\'](/music/[\w\d\-]+/[\w\d\-/]+)["\']', html)
            logger.info(f"[Musopen] Candidates found: {len(track_links)} -> {track_links[:3]}")
            if not track_links:
                logger.info(f"[Musopen] No track candidates for query: {query}")
                return None
            for path in track_links[:3]:
                url = f'https://musopen.org{path}'
                logger.info(f"[Musopen] Trying: {url}")
                try:
                    async with self.session.get(url, timeout=15) as resp2:
                        if resp2.status != 200:
                            continue
                        inner = await resp2.text()
                    # Ищем прямые mp3-ссылки на странице трека
                    mp3_links = re.findall(r'href="(https://cdn\.musopen\.org/[^"]+\.mp3)"', inner)
                    if mp3_links:
                        audio_url = mp3_links[0]
                        filename = os.path.basename(audio_url).split("?")[0]
                        dest = os.path.join("downloads", filename)
                        async with aiohttp.ClientSession() as s:
                            path = await _download_file(s, audio_url, dest)
                        if path:
                            logger.info(f"[Musopen] Success: {path}")
                            return path
                except Exception as ex:
                    logger.error(f"Musopen candidate error: {ex}")
                    continue
        except Exception as e:
            logger.error(f"MusopenProvider error: {e}")
        return None

class PleerNetProvider:
    """Провайдер для поиска и скачивания mp3 с pleer.net"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            base_url = 'https://pleer.net'
            search_url = f'{base_url}/search?q={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=12) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            import re
            track_links = re.findall(r'(<a class="track__download-btn" [^>]*href="([^"]+\.mp3[^"]*)"[^>]*>)', html)
            if not track_links:
                return None
            mp3_url = track_links[0][1] if isinstance(track_links[0], tuple) else track_links[0]
            if not mp3_url.startswith('http'):
                mp3_url = base_url + mp3_url
            safe_name = clean_filename(query)
            dest = os.path.join("downloads", f"{safe_name}.mp3")
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, mp3_url, dest)
            return path
        except Exception as e:
            logger.error(f"PleerNetProvider error: {e}")
            return None

class MP3JuicesProvider:
    """Провайдер для поиска на mp3juices.cc"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://www.mp3juices.cc/search/{quote(query, safe="")}'
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            import re
            mp3_links = re.findall(r'href=[\'"]([^\'"]+?\.mp3[^\'"]*)[\'"]', html)
            for link in mp3_links:
                if link.startswith('//'):
                    link = 'https:' + link
                elif not link.startswith('http'):
                    link = 'https://' + link
                safe_name = clean_filename(query)
                dest = os.path.join("downloads", f"{safe_name}.mp3")
                async with aiohttp.ClientSession() as s:
                    path = await _download_file(s, link, dest)
                if path:
                    return path
            return None
        except Exception as e:
            logger.error(f"MP3JuicesProvider error: {e}")
            return None

class ZaycevProvider:
    """Провайдер для поиска на zaycev.net (простым парсингом)"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://zaycev.net/search.html?query_search={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            import re
            mp3_links = re.findall(r'href=[\'"]([^\'"]+?\.mp3[^\'"]*)[\'"]', html)
            for link in mp3_links:
                if link.startswith('//'):
                    link = 'https:' + link
                elif not link.startswith('http'):
                    link = 'https://' + link
                safe_name = clean_filename(query)
                dest = os.path.join("downloads", f"{safe_name}.mp3")
                async with aiohttp.ClientSession() as s:
                    path = await _download_file(s, link, dest)
                if path:
                    return path
            return None
        except Exception as e:
            logger.error(f"ZaycevProvider error: {e}")
            return None

class MyzukaProvider:
    """Провайдер для поиска и скачивания mp3 с myzuka.fm"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://myzuka.fm/Search.aspx?Text={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            import re
            links = re.findall(r'<a href="(/Track/\d+/[^"]+)"', html)
            if not links:
                return None
            # Берём первую детальную страницу и ищем кнопку mp3/stream
            detail_url = f'https://myzuka.fm{links[0]}'
            async with self.session.get(detail_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                detail = await resp.text()
            mp3_matches = re.findall(r'data-url="([^"]+\.mp3[^"]*)"', detail)
            if not mp3_matches:
                return None
            mp3_url = mp3_matches[0]
            safe_name = clean_filename(query)
            dest = os.path.join("downloads", f"{safe_name}.mp3")
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, mp3_url, dest)
            return path
        except Exception as e:
            logger.error(f"MyzukaProvider error: {e}")
            return None

class RuTrackProvider:
    """Провайдер для поиска на rutracker.org (скачать .torrent -- опционально)."""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        # Внимание! Для rutracker нужны прокси/куки, но мы попробуем только парсинг публичного поиска! Торренты не качаем, а только даем ссылку.
        try:
            search_url = f'https://rutracker.org/forum/tracker.php?nm={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=15) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
            import re
            links = re.findall(r'<a class="tLink nowrap f\d+" href="([^"]+)"', html)
            if not links:
                return None
            title = clean_filename(query)
            info_url = f'https://rutracker.org{links[0]}'
            # В данной реализации можно лишь вернуть info_url, но не скачивать .torrent без залогина
            logger.info(f"RuTrackProvider: найден торрент для {query}: {info_url}")
            return None
        except Exception as e:
            logger.error(f"RuTrackProvider error: {e}")
            return None

class RedMp3Provider:
    """Провайдер redmp3.cc - прямые mp3 из поиска."""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://redmp3.cc/search/{quote(query, safe="")}/'
            async with self.session.get(search_url, timeout=15) as resp:
                html = await resp.text()
            import re
            links = re.findall(r'<a href="(/\d+\-[a-zA-Z0-9\-]+\.html)"', html)
            if not links:
                return None
            detail_url = 'https://redmp3.cc' + links[0]
            async with self.session.get(detail_url, timeout=8) as resp:
                det = await resp.text()
            mp3_links = re.findall(r'src="(https://files\.redmp3\.cc/[^\"]+\.mp3)"', det)
            if not mp3_links:
                return None
            mp3_url = mp3_links[0]
            safe_name = clean_filename(query)
            dest = os.path.join("downloads", f"{safe_name}.mp3")
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, mp3_url, dest)
            return path
        except Exception as e:
            logger.error(f"RedMp3Provider error: {e}")
            return None

class Mp3SkullsProvider:
    """Провайдер mp3skulls.info - парсинг mp3 из поиска и деталек."""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://mp3skulls.info/mg/search.html?wm={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=12) as resp:
                html = await resp.text()
            import re
            mp3_links = re.findall(r'<a[^>]*href=["\']([^"\']+\.mp3[^"\']*)["\'][^>]*>', html)
            for link in mp3_links:
                if link.startswith('//'):
                    link = 'https:' + link
                elif not link.startswith('http'):
                    link = 'https://' + link
                safe_name = clean_filename(query)
                dest = os.path.join("downloads", f"{safe_name}.mp3")
                async with aiohttp.ClientSession() as s:
                    path = await _download_file(s, link, dest)
                if path:
                    return path
            return None
        except Exception as e:
            logger.error(f"Mp3SkullsProvider error: {e}")
            return None

class Music7sProvider:
    """Провайдер music7s.cc - быстрый поиск mp3."""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://music7s.cc/search?q={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=13) as resp:
                html = await resp.text()
            import re
            mp3_links = re.findall(r'<a[^>]+href=["\']([^"\']+\.mp3[^"\']*)["\']', html)
            for link in mp3_links:
                if link.startswith('//'):
                    link = 'https:' + link
                elif not link.startswith('http'):
                    link = 'https://' + link
                safe_name = clean_filename(query)
                dest = os.path.join("downloads", f"{safe_name}.mp3")
                async with aiohttp.ClientSession() as s:
                    path = await _download_file(s, link, dest)
                if path:
                    return path
            return None
        except Exception as e:
            logger.error(f"Music7sProvider error: {e}")
            return None


class ImprovedSearchEngine:
    """Улучшенный поисковый движок с приоритетом оригинальных версий"""
    
    @staticmethod
    def filter_original_versions(candidates: List[Dict], track_info: dict = None) -> List[Dict]:
        """Фильтрует кандидатов, отдавая приоритет оригинальным версиям"""
        if not candidates:
            return candidates
            
        # Слова-индикаторы неоригинальных версий
        non_original_keywords = [
            'slowed', 'sped up', 'nightcore', 'remix', 'edit', 'mashup',
            'cover', 'acoustic', 'live', 'instrumental', 'karaoke',
            'guitar', 'piano', 'orchestral', 'orchestra', 'symphony',
            'extended', 'club', 'radio', 'clean', 'explicit',
            'reverb', 'echo', 'bass boosted', '8d', '3d', 'spatial',
            'super slowed', 'ultra slowed', 'extreme slowed', 'heavily slowed',
            'slowed down', 'slow version', 'slow edit', 'slow remix'
        ]
        
        # Слова-индикаторы оригинальных версий
        original_keywords = [
            'original', 'official', 'studio', 'album version',
            'single', 'main', 'standard'
        ]
        
        scored_candidates = []
        
        for candidate in candidates:
            title = candidate.get('title', '').lower()
            score = 100  # Базовый скор
            
            # Штрафуем за неоригинальные версии
            for keyword in non_original_keywords:
                if keyword in title:
                    score -= 30
                    
            # Особо строгий штраф за slowed версии
            if any(keyword in title for keyword in ['slowed', 'super slowed', 'ultra slowed', 'extreme slowed']):
                score -= 50  # Очень большой штраф
                    
            # Бонус за оригинальные версии
            for keyword in original_keywords:
                if keyword in title:
                    score += 20
                    
            # Бонус за совпадение длительности (если известна)
            if track_info and track_info.get('duration'):
                candidate_duration = candidate.get('duration', 0)
                target_duration = track_info['duration']
                if candidate_duration > 0:
                    duration_diff = abs(candidate_duration - target_duration)
                    if duration_diff <= 5:  # Разница до 5 секунд
                        score += 25
                    elif duration_diff <= 15:  # Разница до 15 секунд
                        score += 10
                    else:
                        score -= 15
                        
            # Бонус за высокие просмотры (популярность)
            view_count = candidate.get('view_count', 0)
            if view_count > 1000000:
                score += 15
            elif view_count > 100000:
                score += 10
                
            scored_candidates.append((candidate, score))
            
        # Сортируем по скору (убывание)
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        
        # Возвращаем только кандидатов с положительным скором
        return [candidate for candidate, score in scored_candidates if score > 0]

    @staticmethod
    def enhance_search_query(query: str, track_info: dict = None) -> List[str]:
        """Создает улучшенные поисковые запросы с приоритетом оригинальных версий"""
        queries = []
        
        # Основной запрос
        queries.append(query)
        
        if track_info:
            # Добавляем "official" для поиска оригинальных версий
            artist = track_info.get('artist', '')
            track_name = track_info.get('name', '')
            
            if artist and track_name:
                queries.append(f'"{track_name}" "{artist}" official')
                queries.append(f'"{track_name}" "{artist}" original')
                queries.append(f'"{track_name}" "{artist}" studio version')
                
        return queries


class EnhancedSoundCloudProvider:
    """Улучшенный SoundCloud провайдер с фильтрацией версий"""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_urls(self, query: str, limit: int = 10) -> List[str]:
        """Ищет URL треков на SoundCloud"""
        try:
            # Правильно кодируем Unicode символы для URL
            encoded_query = quote(query, safe='', encoding='utf-8')
            
            # Используем API SoundCloud для поиска
            search_url = f"https://api-v2.soundcloud.com/search/tracks?q={encoded_query}&limit={limit}&client_id=YOUR_CLIENT_ID"
            
            # Fallback на веб-поиск если API не работает
            try:
                async with self.session.get(search_url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if 'collection' in data:
                            return [track['permalink_url'] for track in data['collection'] if track.get('permalink_url')]
            except Exception:
                pass
            
            # Веб-поиск как fallback
            web_search_url = f"https://soundcloud.com/search/sounds?q={encoded_query}"
            async with self.session.get(web_search_url, timeout=15) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
            
            import re
            # Ищем ссылки на треки в HTML
            track_links = re.findall(r'href="(https://soundcloud\.com/[^"]+)"', html)
            # Фильтруем только ссылки на треки (не на пользователей)
            track_urls = [link for link in track_links if '/tracks/' in link]
            
            # Если веб-поиск не дал результатов, пробуем yt-dlp поиск
            if not track_urls:
                try:
                    import yt_dlp
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        search_results = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
                        if search_results and 'entries' in search_results:
                            entries = [e for e in search_results['entries'] if e]
                            track_urls = [entry.get('webpage_url', '') for entry in entries if entry.get('webpage_url')]
                except Exception as e:
                    logger.warning(f"Enhanced SoundCloud yt-dlp search failed: {e}")
            
            return track_urls[:limit]
        except Exception as e:
            logger.error(f"EnhancedSoundCloud search error: {e}")
            return []
    
    async def search_and_download_best(self, query: str, track_info: dict = None) -> Optional[str]:
        """Ищет лучшую версию трека на SoundCloud"""
        try:
            logger.info(f"Enhanced SoundCloud: Searching for '{query}'")
            
            # Получаем кандидатов
            candidates = await self.search_urls(query, limit=10)
            logger.info(f"Enhanced SoundCloud: Found {len(candidates)} candidates")
            
            if not candidates:
                logger.info("Enhanced SoundCloud: No candidates found")
                return None
                
            # Скачиваем информацию о каждом кандидате
            candidate_info = []
            for url in candidates:
                try:
                    import yt_dlp
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': True,
                    }
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        if info:
                            candidate_info.append({
                                'url': url,
                                'title': info.get('title', ''),
                                'duration': info.get('duration', 0),
                                'view_count': info.get('view_count', 0)
                            })
                            logger.info(f"Enhanced SoundCloud: Candidate '{info.get('title', '')}'")
                except Exception as e:
                    logger.warning(f"Enhanced SoundCloud: Failed to get info for {url}: {e}")
                    continue
                    
            logger.info(f"Enhanced SoundCloud: Analyzed {len(candidate_info)} candidates")
            
            # Фильтруем кандидатов
            filtered_candidates = ImprovedSearchEngine.filter_original_versions(candidate_info, track_info)
            
            logger.info(f"Enhanced SoundCloud: After filtering: {len(filtered_candidates)} candidates")
            
            if not filtered_candidates:
                logger.info("Enhanced SoundCloud: No good candidates after filtering")
                return None
                
            # Скачиваем лучшего кандидата
            best_candidate = filtered_candidates[0]
            logger.info(f"Enhanced SoundCloud: Best candidate '{best_candidate['title']}'")
            result = await self._download_candidate(best_candidate['url'])
            logger.info(f"Enhanced SoundCloud: Download result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"EnhancedSoundCloudProvider error: {e}")
            return None
            
    async def _download_candidate(self, url: str) -> Optional[str]:
        """Скачивает трек по URL"""
        try:
            import shutil
            import glob
            import time
            # Полная очистка папки downloads перед скачиванием
            if os.path.exists("downloads"):
                for f in glob.glob("downloads/*"):
                    try:
                        os.remove(f)
                    except Exception as e:
                        logger.warning(f"Enhanced SoundCloud: Could not remove {f}: {e}")
            os.makedirs("downloads", exist_ok=True)
            logger.info(f"Enhanced SoundCloud: Downloads directory ready and cleaned")
            logger.info(f"Enhanced SoundCloud: downloads dir after clean: {glob.glob('downloads/*')}")

            # Список before_files до скачивания
            before_files = set(glob.glob("downloads/*"))
            logger.info(f"Enhanced SoundCloud: Files before download: {before_files}")

            # --- Ваш код скачивания (yt-dlp или иной способ) ---
            import yt_dlp
            ydl_opts = {
                'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio[ext=webm]/bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'windowsfilenames': True,
                # Исправления для FFmpeg
                'ffmpeg_location': None,  # Используем системный FFmpeg
                'postprocessor_args': {
                    'FFmpegExtractAudio': [
                        '-acodec', 'mp3',
                        '-ab', '192k',
                        '-ar', '44100',
                        '-ac', '2',
                        '-avoid_negative_ts', 'make_zero',
                        '-fflags', '+genpts',
                        '-strict', '-2',  # Разрешаем экспериментальные кодеки
                        '-max_muxing_queue_size', '1024'  # Увеличиваем буфер
                    ]
                },
                'ignoreerrors': True,
                'no_check_certificate': True,
                'prefer_ffmpeg': True,
                'keepvideo': False,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # После скачивания — лог содержимого папки
                logger.info(f"Enhanced SoundCloud: downloads dir after download: {glob.glob('downloads/*')}")
                if info:
                    title = clean_filename(info.get('title', 'track'))
                    logger.info(f"Enhanced SoundCloud: Downloaded '{title}', looking for file...")
                    for ext in ['mp3', 'webm', 'm4a', 'ogg', 'wav']:
                        file_path = f"downloads/{title}.{ext}"
                        if os.path.exists(file_path):
                            logger.info(f"Enhanced SoundCloud: Found file {file_path}")
                            return file_path
                    aac_path = f"downloads/{title}.aac"
                    if os.path.exists(aac_path):
                        logger.info(f"Enhanced SoundCloud: Found AAC file {aac_path}, will convert to MP3")
                        return aac_path

            await asyncio.sleep(3)

            # После скачивания — второй лог содержимого
            after_files = set(glob.glob("downloads/*"))
            logger.info(f"Enhanced SoundCloud: Files after download: {after_files}")
            new_files = after_files - before_files
            logger.info(f"Enhanced SoundCloud: New files found: {new_files}")

            # Если появились "новые" файлы
            if new_files:
                new_files_list = list(new_files)
                new_files_list.sort(key=lambda x: os.path.getctime(x), reverse=True)
                for new_file in new_files_list:
                    try:
                        file_size = os.path.getsize(new_file)
                        logger.info(f"Enhanced SoundCloud: Checking file {new_file} (size: {file_size} bytes)")
                        if file_size > 1000:
                            if new_file.lower().endswith('.mp3'):
                                logger.info(f"Enhanced SoundCloud: Using MP3 file {new_file} (size: {file_size} bytes)")
                                return new_file
                            elif new_file.lower().endswith(('.webm', '.m4a', '.ogg', '.wav')):
                                logger.info(f"Enhanced SoundCloud: Using audio file {new_file} (size: {file_size} bytes)")
                                return new_file
                            elif new_file.lower().endswith('.aac'):
                                logger.info(f"Enhanced SoundCloud: Using AAC file {new_file} (size: {file_size} bytes, will convert)")
                                return new_file
                    except Exception as e:
                        logger.error(f"Enhanced SoundCloud: Error checking new file {new_file}: {e}")
                        continue
            # Нет новых файлов — fallback: выбрать самый последний подходящий аудиофайл (даже если он старый)
            all_files = glob.glob("downloads/*")
            all_files.sort(key=lambda x: os.path.getctime(x), reverse=True)
            logger.info(f"Enhanced SoundCloud: fallback all files in downloads: {all_files}")
            best = None
            best_mtime = 0
            current_time = time.time()
            for file_path in all_files:
                try:
                    file_size = os.path.getsize(file_path)
                    file_age = current_time - os.path.getctime(file_path)
                    logger.info(f"Enhanced SoundCloud: Fallback file {file_path} (size: {file_size}, age: {file_age}s)")
                    if file_size > 1000 and file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                        if best is None or os.path.getctime(file_path) > best_mtime:
                            best = file_path
                            best_mtime = os.path.getctime(file_path)
                except Exception as e:
                    logger.error(f"Enhanced SoundCloud: Error in fallback check {file_path}: {e}")
                    continue
            if best:
                logger.info(f"Enhanced SoundCloud: Fallback returning best available file: {best}")
                return best
            logger.warning("Enhanced SoundCloud: Nothing found after all checks!")
            return None
        except Exception as e:
            logger.error(f"Enhanced SoundCloud download error: {e}")
            return None


class Mp3DownloadProvider:
    """Провайдер mp3download.to - популярный mp3 сайт"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://mp3download.to/search/{quote(query, safe="")}'
            async with self.session.get(search_url, timeout=15) as resp:
                html = await resp.text()
            import re
            # Ищем ссылки на треки
            track_links = re.findall(r'<a href="(/download/[^"]+)"', html)
            if not track_links:
                return None
            # Переходим на страницу трека
            track_url = f'https://mp3download.to{track_links[0]}'
            async with self.session.get(track_url, timeout=10) as resp:
                track_html = await resp.text()
            # Ищем прямую ссылку на mp3
            mp3_links = re.findall(r'href="(https://[^"]+\.mp3[^"]*)"', track_html)
            if not mp3_links:
                return None
            mp3_url = mp3_links[0]
            safe_name = clean_filename(query)
            dest = os.path.join("downloads", f"{safe_name}.mp3")
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, mp3_url, dest)
            return path
        except Exception as e:
            logger.error(f"Mp3DownloadProvider error: {e}")
            return None


class Beemp3sProvider:
    """Провайдер beemp3s.net - быстрый поиск mp3"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://beemp3s.net/search/{quote(query, safe="")}'
            async with self.session.get(search_url, timeout=12) as resp:
                html = await resp.text()
            import re
            mp3_links = re.findall(r'<a[^>]+href=["\']([^"\']+\.mp3[^"\']*)["\']', html)
            for link in mp3_links:
                if link.startswith('//'):
                    link = 'https:' + link
                elif not link.startswith('http'):
                    link = 'https://' + link
                safe_name = clean_filename(query)
                dest = os.path.join("downloads", f"{safe_name}.mp3")
                async with aiohttp.ClientSession() as s:
                    path = await _download_file(s, link, dest)
                if path:
                    return path
            return None
        except Exception as e:
            logger.error(f"Beemp3sProvider error: {e}")
            return None


class VkMusicFunProvider:
    """Провайдер vkmusic.fun - VK музыка без регистрации"""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    async def search_and_download(self, query: str) -> Optional[str]:
        try:
            search_url = f'https://vkmusic.fun/search?q={quote(query, safe="")}'
            async with self.session.get(search_url, timeout=15) as resp:
                html = await resp.text()
            import re
            # Ищем ссылки на треки
            track_links = re.findall(r'<a href="(/track/[^"]+)"', html)
            if not track_links:
                return None
            # Переходим на страницу трека
            track_url = f'https://vkmusic.fun{track_links[0]}'
            async with self.session.get(track_url, timeout=10) as resp:
                track_html = await resp.text()
            # Ищем прямую ссылку на mp3
            mp3_links = re.findall(r'href="(https://[^"]+\.mp3[^"]*)"', track_html)
            if not mp3_links:
                return None
            mp3_url = mp3_links[0]
            safe_name = clean_filename(query)
            dest = os.path.join("downloads", f"{safe_name}.mp3")
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, mp3_url, dest)
            return path
        except Exception as e:
            logger.error(f"VkMusicFunProvider error: {e}")
            return None
