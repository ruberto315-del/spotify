import asyncio
import logging
import os
import re
import time
from typing import List, Optional, Tuple
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import yt_dlp
import shutil
from aiohttp import web
from datetime import datetime

from utils import EnhancedSpotifyParser, MusicSearchEngine, clean_filename, format_file_size, JioSaavnProvider, SoundCloudProvider, YTMusicProvider, AlternativeMusicProvider, BandcampProvider, ArchiveOrgProvider, FreeMusicArchiveProvider, JamendoProvider, MixcloudProvider, AlternativeYouTubeProvider, VKMusicProvider, YandexMusicProvider, DeezerProvider, AudiomackProvider, MusopenProvider, PleerNetProvider, MP3JuicesProvider, ZaycevProvider, MyzukaProvider, RuTrackProvider, RedMp3Provider, Mp3SkullsProvider, Music7sProvider, Mp3DownloadProvider, Beemp3sProvider, VkMusicFunProvider, ImprovedSearchEngine, EnhancedSoundCloudProvider

db_config = {
    'user': 'postgres',
    'password': 'MppPCJrvBTeobJDWcFYnBVHISFBEcfxN',
    'database': 'railway',
    'host': 'postgres.railway.internal',
    'port': '5432',
}


# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)
# Перевірка наявності ffmpeg
def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None

# Ініціалізація бота
bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
dp = Dispatcher()

# Семафор для обмеження одночасних завантажень (максимум 3 одночасно)
download_semaphore = asyncio.Semaphore(3)

# Лічильник активних завантажень
active_downloads = 0

# Ініціалізація Spotify API
spotify_client_id = os.getenv('SPOTIFY_CLIENT_ID')
spotify_client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

# Створюємо екземпляр парсера Spotify
spotify_parser = EnhancedSpotifyParser(spotify_client_id, spotify_client_secret)

# Глобальные переменные для статистики
user_requests_today = {}
requests_today = 0
request_day = datetime.utcnow().strftime('%Y-%m-%d')


class MusicDownloader:
    """Клас для пошуку та завантаження музики"""
    
    @staticmethod
    async def search_and_download(query: str, track_info: dict = None) -> Optional[str]:
        """Шукає та завантажує музику за запитом"""
        try:
            # Очищаємо запит від неприпустимих символів
            clean_query = clean_filename(query)
            logger.info(f"Download start. Query='{clean_query}'")
            
            # 1) Пробуємо онлайн провайдера (JioSaavn)
            try:
                logger.info("Provider: JioSaavn")
                async with JioSaavnProvider() as provider:
                    path = await provider.download_best(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"JioSaavn success: {path}")
                        return path
            except Exception as _:
                logger.exception("JioSaavn error")
            
            # Невелика затримка між провайдерами
            await asyncio.sleep(0.5)
            
            # 2) Пробуємо з різними варіантами запиту для збільшення шансів знайти трек
            search_variants = [
                clean_query,
                clean_query.replace('_', ' '),
                clean_query.replace(',', ' '),
                clean_query.replace('.', ' '),
                ' '.join(clean_query.split('_')[:3]),  # Первые 3 слова
            ]
            
            # Прибираємо дублікати
            search_variants = list(dict.fromkeys(search_variants))
            logger.info(f"Search variants: {search_variants}")
            
            # 2) Пробуємо покращений SoundCloud з фільтрацією версій
            for variant in search_variants:
                try:
                    logger.info(f"Provider: Enhanced SoundCloud (variant: '{variant}')")
                    async with EnhancedSoundCloudProvider() as sc:
                        path = await sc.search_and_download_best(variant, track_info)
                        logger.info(f"Enhanced SoundCloud returned path: {path}")
                        if path:
                            logger.info(f"Enhanced SoundCloud path exists: {os.path.exists(path)}")
                            if os.path.exists(path):
                                logger.info(f"Enhanced SoundCloud success: {path}")
                                return path
                            else:
                                logger.warning(f"Enhanced SoundCloud path does not exist: {path}")
                        else:
                            logger.warning("Enhanced SoundCloud returned None")
                except Exception as e:
                    logger.error(f"Enhanced SoundCloud error: {e}")
                    continue
            
            await asyncio.sleep(0.3)
                
            # 2.1) Пробуємо звичайний SoundCloud як fallback з фільтрацією
            for variant in search_variants:
                try:
                    logger.info(f"Provider: SoundCloud Fallback (variant: '{variant}')")
                    async with SoundCloudProvider() as sc:
                        sc_urls = await sc.search_urls(variant, limit=5)
                    logger.info(f"SoundCloud candidates: {len(sc_urls)}")
                    if sc_urls:
                        # Сначала анализируем кандидатов для фильтрации
                        candidate_info = []
                        for url in sc_urls:
                            try:
                                import yt_dlp
                                ydl_info_opts = {
                                    'quiet': True,
                                    'no_warnings': True,
                                    'extract_flat': True,
                                }
                                with yt_dlp.YoutubeDL(ydl_info_opts) as ydl_info:
                                    info = ydl_info.extract_info(url, download=False)
                                    if info:
                                        candidate_info.append({
                                            'url': url,
                                            'title': info.get('title', ''),
                                            'duration': info.get('duration', 0),
                                            'view_count': info.get('view_count', 0)
                                        })
                            except Exception:
                                continue
                    
                        # Фільтруємо кандидатів
                        filtered_candidates = ImprovedSearchEngine.filter_original_versions(candidate_info, track_info)
                        
                        if not filtered_candidates:
                            logger.info("SoundCloud Fallback: No good candidates after filtering")
                            # Якщо немає хороших кандидатів, пробуємо перший без фільтрації
                            filtered_candidates = candidate_info[:1]
                        
                        # Завантажуємо найкращого кандидата
                        best_candidate = filtered_candidates[0]
                        logger.info(f"SoundCloud Fallback: Best candidate '{best_candidate['title']}'")
                        
                        ydl_sc_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [
                                {
                                    'key': 'FFmpegExtractAudio',
                                    'preferredcodec': 'mp3',
                                    'preferredquality': '192',
                                }
                            ],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                            # Исправления для FFmpeg проблем
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
                            'ignoreerrors': True,  # Игнорируем ошибки постобработки
                            'no_check_certificate': True,  # Отключаем проверку сертификатов
                        }
                        import yt_dlp as _yt
                        with _yt.YoutubeDL(ydl_sc_opts) as ydl2:
                            try:
                                logger.info(f"SoundCloud try: {best_candidate['url']}")
                                info = ydl2.extract_info(best_candidate['url'], download=True)
                                title = info.get('title') or 'track'
                                
                                # Ищем скачанный файл в разных форматах
                                base_name = clean_filename(title)
                                for ext in ['mp3', 'webm', 'm4a', 'ogg', 'wav']:
                                    candidate = f"downloads/{base_name}.{ext}"
                                    if os.path.exists(candidate):
                                        logger.info(f"SoundCloud success: {candidate}")
                                        return candidate
                                
                                # Якщо MP3 не знайдено, але є інші формати, конвертуємо
                                for ext in ['webm', 'm4a', 'ogg', 'wav']:
                                    source_file = f"downloads/{base_name}.{ext}"
                                    if os.path.exists(source_file):
                                        # Пробуємо конвертувати в MP3
                                        mp3_file = f"downloads/{base_name}.mp3"
                                        try:
                                            import subprocess
                                            result = subprocess.run([
                                                'ffmpeg', '-i', source_file, 
                                                '-acodec', 'mp3', '-ab', '192k',
                                                '-ar', '44100', '-ac', '2',
                                                '-y', mp3_file
                                            ], capture_output=True, timeout=30)
                                            if result.returncode == 0 and os.path.exists(mp3_file):
                                                logger.info(f"SoundCloud converted success: {mp3_file}")
                                                return mp3_file
                                        except Exception:
                                            # Якщо конвертація не вдалася, повертаємо вихідний файл
                                            logger.info(f"SoundCloud success (original): {source_file}")
                                            return source_file
                                            
                            except Exception as e:
                                logger.error(f"SoundCloud candidate failed: {e}")
                except Exception:
                    logger.exception("SoundCloud provider error")
                    continue
            
            await asyncio.sleep(0.4)
            
            # 2.5) Пробуємо альтернативний провайдер (Last.fm + інші джерела)
            try:
                logger.info("Provider: AlternativeMusic")
                async with AlternativeMusicProvider() as alt_provider:
                    path = await alt_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"AlternativeMusic success: {path}")
                        return path
            except Exception as e:
                logger.error(f"AlternativeMusic error: {e}")

            # 2.5A) Пробуємо Pleer.net
            try:
                logger.info("Provider: PleerNet")
                async with PleerNetProvider() as pleer_provider:
                    path = await pleer_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"PleerNet success: {path}")
                        return path
            except Exception as e:
                logger.error(f"PleerNet error: {e}")
            
            await asyncio.sleep(0.2)
            # 2.5B) Пробуємо MP3Juices
            try:
                logger.info("Provider: MP3Juices")
                async with MP3JuicesProvider() as mp3j_provider:
                    path = await mp3j_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"MP3Juices success: {path}")
                        return path
            except Exception as e:
                logger.error(f"MP3Juices error: {e}")
            
            await asyncio.sleep(0.2)
            # 2.5C) Пробуємо Zaycev.net
            try:
                logger.info("Provider: Zaycev.net")
                async with ZaycevProvider() as zaycev_provider:
                    path = await zaycev_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Zaycev.net success: {path}")
                        return path
            except Exception as e:
                logger.error(f"ZaycevProvider error: {e}")
            
            # 2.5D) Пробуємо Myzuka.fm
            try:
                logger.info("Provider: Myzuka.fm")
                async with MyzukaProvider() as myzuka_provider:
                    path = await myzuka_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Myzuka.fm success: {path}")
                        return path
            except Exception as e:
                logger.error(f"MyzukaProvider error: {e}")
                # Продовжуємо роботу, не перериваємо виконання
            # 2.5E) Пробуємо rutracker.org (видаємо публічне посилання, якщо знайдено торрент)
            try:
                logger.info("Provider: RuTracker")
                async with RuTrackProvider() as rutr_provider:
                    info_url = await rutr_provider.search_and_download(clean_query)
                    if info_url:
                        logger.info(f"RuTracker info for '{clean_query}': {info_url}")
                        # Для этого типа результата можно отправить текстом ссылку пользователю, либо пробросить в формат ответа
            except Exception as e:
                logger.error(f"RuTrackProvider error: {e}")
            
            # 2.6) Пробуємо Bandcamp
            try:
                logger.info("Provider: Bandcamp")
                async with BandcampProvider() as bc_provider:
                    path = await bc_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Bandcamp success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Bandcamp error: {e}")
            
            # 2.7) Пробуємо Internet Archive
            try:
                logger.info("Provider: Archive.org")
                async with ArchiveOrgProvider() as arch_provider:
                    path = await arch_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Archive.org success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Archive.org error: {e}")
            
            # 2.8) Пробуємо Free Music Archive
            try:
                logger.info("Provider: Free Music Archive")
                async with FreeMusicArchiveProvider() as fma_provider:
                    path = await fma_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Free Music Archive success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Free Music Archive error: {e}")
            
            # 2.9) Пробуємо Jamendo
            try:
                logger.info("Provider: Jamendo")
                async with JamendoProvider() as jam_provider:
                    path = await jam_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Jamendo success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Jamendo error: {e}")
            
            # 2.10) Пробуємо Mixcloud
            try:
                logger.info("Provider: Mixcloud")
                async with MixcloudProvider() as mix_provider:
                    path = await mix_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Mixcloud success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Mixcloud error: {e}")
            
            # 2.11) Пробуємо VK Music
            try:
                logger.info("Provider: VK Music")
                async with VKMusicProvider() as vk_provider:
                    path = await vk_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"VK Music success: {path}")
                        return path
            except Exception as e:
                logger.error(f"VK Music error: {e}")
            
            # 2.12) Пробуємо Яндекс.Музика
            try:
                logger.info("Provider: Yandex Music")
                async with YandexMusicProvider() as yandex_provider:
                    path = await yandex_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Yandex Music success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Yandex Music error: {e}")
            
            # 2.13) Пробуємо Deezer
            try:
                logger.info("Provider: Deezer")
                async with DeezerProvider() as deezer_provider:
                    path = await deezer_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Deezer success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Deezer error: {e}")
            
            # 2.14) Пробуємо Audiomack
            try:
                logger.info("Provider: Audiomack")
                async with AudiomackProvider() as audiomack_provider:
                    path = await audiomack_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Audiomack success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Audiomack error: {e}")

            # 2.15) Пробуємо Musopen
            try:
                logger.info("Provider: Musopen")
                async with MusopenProvider() as musopen_provider:
                    path = await musopen_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Musopen success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Musopen error: {e}")
            
            # 2.16) Пробуємо альтернативний YouTube провайдер
            try:
                logger.info("Provider: AlternativeYouTube")
                alt_yt_provider = AlternativeYouTubeProvider()
                path = await alt_yt_provider.search_and_download(clean_query)
                if path and os.path.exists(path):
                    logger.info(f"AlternativeYouTube success: {path}")
                    return path
            except Exception as e:
                logger.error(f"AlternativeYouTube error: {e}")
            
            # 2.17) Пробуємо YouTube Music: шукаємо пісні та завантажуємо найкращого кандидата через yt-dlp
            try:
                ytm = YTMusicProvider()
                ytm_candidates = ytm.search(clean_query, limit=7)
                # если есть track_info, переформируем запросы и расширим список
                if track_info:
                    extra_q = f"{track_info.get('name','')} {track_info.get('artist','')}".strip()
                    if extra_q and extra_q.lower() != clean_query.lower():
                        ytm_candidates += ytm.search(extra_q, limit=7)
                # сортируем по близости длительности, если известна
                target_dur = track_info.get('duration') if track_info else None
                if target_dur:
                    ytm_candidates.sort(key=lambda c: abs((c.get('duration') or 0) - target_dur))
                ydl_ytm_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                    'postprocessors': [
                        {
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }
                    ],
                    'prefer_ffmpeg': True,
                    'noprogress': True,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'windowsfilenames': True,
                }
                import yt_dlp as _ytm
                with _ytm.YoutubeDL(ydl_ytm_opts) as ydlm:
                    tried = 0
                    for cand in ytm_candidates:
                        if tried >= 5:
                            break
                        tried += 1
                        url = cand.get('url')
                        if not url:
                            continue
                        try:
                            info = ydlm.extract_info(url, download=True)
                            title = info.get('title') or cand.get('title') or 'track'
                            candidate = f"downloads/{clean_filename(title)}.mp3"
                            if os.path.exists(candidate):
                                return candidate
                        except Exception:
                            continue
            except Exception:
                pass

            # Настройки для yt-dlp с максимальным обходом блокировок
            import random
            
            # Ротация User-Agent для обхода детекции
            user_agents = [
                'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
                'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0'
            ]
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }
                ],
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
                'ignoreerrors': True,  # Игнорируем ошибки постобработки
                'no_check_certificate': True,  # Отключаем проверку сертификатов
                'prefer_ffmpeg': True,
                'noprogress': True,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,  # 50MB лимит
                'windowsfilenames': True,
                # Максимальный обход блокировок YouTube
                'http_headers': {
                    'User-Agent': random.choice(user_agents),
                    'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'android_music', 'android', 'web'],
                        'skip': ['dash', 'hls'],
                        'player_skip': ['webpage'],
                        'comment_sort': ['top'],
                        'innertube_host': 'music.youtube.com',
                    }
                },
                'retries': 3,
                'fragment_retries': 3,
                'retry_sleep': 2,
                'sleep_interval': 1,
                'max_sleep_interval': 3,
                # Дополнительные настройки обхода
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'cookiesfrombrowser': None,  # Отключаем cookies
                'no_check_certificate': True,
                'ignoreerrors': True,
                # Отключаем аутентификацию
                'username': None,
                'password': None,
                'netrc': False,
                # Дополнительные настройки для обхода блокировок
                'extract_flat': False,
                'writethumbnail': False,
                'writeinfojson': False,
                'writesubtitles': False,
                'writeautomaticsub': False,
                # Прокси (если доступны)
                'proxy': None,  # Можно добавить прокси позже
            }
            
            try:
                import yt_dlp
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info("Provider: YouTube search")
                    # Ищем до 5 видео и выбираем наиболее подходящее
                    search_results = ydl.extract_info(
                        f"ytsearch5:{clean_query}",
                        download=False
                    )
                
                if not search_results or 'entries' not in search_results:
                    logger.info("YouTube returned no entries")
                    return None
                
                entries = [e for e in (search_results.get('entries') or []) if e]
                if not entries:
                    logger.info("YouTube entries empty")
                    return None
                
                # Подбор по длительности (если известна)
                target_duration = None
                if track_info and isinstance(track_info.get('duration'), int) and track_info['duration'] > 0:
                    target_duration = track_info['duration']
                
                def duration_score(e):
                    d = e.get('duration') or 0
                    if target_duration is None:
                        return 0
                    return abs(d - target_duration)
                
                # Сортируем: сначала по длительности, затем по просмотрам (если есть)
                entries.sort(key=lambda e: (duration_score(e), -(e.get('view_count') or 0)))
                best = entries[0]
                video_url = best.get('webpage_url') or best.get('url')
                if not video_url:
                    logger.info("Best YouTube entry has no URL")
                    return None
                
                # Скачиваем
                logger.info(f"YouTube downloading: {video_url}")
                ydl.download([video_url])
                
                # Возвращаем путь к файлу
                title = best.get('title') or 'track'
                filename = f"downloads/{clean_filename(title)}.mp3"
                logger.info(f"YouTube success: {filename}")
                return filename
                
            except Exception as e:
                logger.error(f"YouTube search failed: {e}")
                
                # Пробуємо альтернативний підхід з більш простими налаштуваннями
                try:
                    logger.info("Provider: YouTube fallback")
                    simple_ydl_opts = {
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
                        'ignoreerrors': True,
                        'extract_flat': False,
                        # Исправления для FFmpeg
                        'ffmpeg_location': None,
                        'postprocessor_args': {
                            'FFmpegExtractAudio': [
                                '-acodec', 'mp3',
                                '-ab', '192k',
                                '-ar', '44100',
                                '-ac', '2',
                                '-avoid_negative_ts', 'make_zero',
                                '-fflags', '+genpts',
                                '-strict', '-2',
                                '-max_muxing_queue_size', '1024'
                            ]
                        },
                        'no_check_certificate': True,
                    }
                    
                    with yt_dlp.YoutubeDL(simple_ydl_opts) as ydl:
                        search_results = ydl.extract_info(
                            f"ytsearch3:{clean_query}",
                            download=False
                        )
                        
                        if search_results and 'entries' in search_results:
                            entries = [e for e in search_results.get('entries', []) if e]
                            if entries:
                                best = entries[0]
                                video_url = best.get('webpage_url') or best.get('url')
                                if video_url:
                                    # Скачиваем с простыми настройками
                                    download_opts = simple_ydl_opts.copy()
                                    download_opts['extract_flat'] = False
                                    with yt_dlp.YoutubeDL(download_opts) as ydl_download:
                                        ydl_download.download([video_url])
                                    
                                    title = best.get('title') or 'track'
                                    filename = f"downloads/{clean_filename(title)}.mp3"
                                    if os.path.exists(filename):
                                        logger.info(f"YouTube fallback success: {filename}")
                                        return filename
                except Exception as fallback_error:
                    logger.error(f"YouTube fallback also failed: {fallback_error}")
                    
                    # Последняя попытка - максимально простые настройки
                    try:
                        logger.info("Provider: YouTube ultra-simple")
                        ultra_simple_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'ignoreerrors': True,
                            'no_check_certificate': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ultra_simple_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{clean_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:  # Файл создан в последние 30 секунд
                                            logger.info(f"YouTube ultra-simple success: {file_path}")
                                            return file_path
                    except Exception as ultra_error:
                        logger.error(f"YouTube ultra-simple also failed: {ultra_error}")
                
                # Не прерываем выполнение, продолжаем с другими провайдерами
                return None
            
            # 2.5F) Пробуємо RedMp3
            try:
                logger.info("Provider: RedMp3")
                async with RedMp3Provider() as redmp3:
                    path = await redmp3.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"RedMp3 success: {path}")
                        return path
            except Exception as e:
                logger.error(f"RedMp3Provider error: {e}")
            # 2.5G) Пробуємо Mp3Skulls
            try:
                logger.info("Provider: Mp3Skulls")
                async with Mp3SkullsProvider() as skulls:
                    path = await skulls.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Mp3Skulls success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Mp3SkullsProvider error: {e}")
            # 2.5I) Пробуємо Mp3Download.to
            try:
                logger.info("Provider: Mp3Download.to")
                async with Mp3DownloadProvider() as mp3dl:
                    path = await mp3dl.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Mp3Download.to success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Mp3DownloadProvider error: {e}")
            # 2.5J) Пробуємо Beemp3s.net
            try:
                logger.info("Provider: Beemp3s.net")
                async with Beemp3sProvider() as beemp3s:
                    path = await beemp3s.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Beemp3s.net success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Beemp3sProvider error: {e}")
            # 2.5K) Пробуємо VkMusic.fun
            try:
                logger.info("Provider: VkMusic.fun")
                async with VkMusicFunProvider() as vkmusic:
                    path = await vkmusic.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"VkMusic.fun success: {path}")
                        return path
            except Exception as e:
                logger.error(f"VkMusicFunProvider error: {e}")

            # 2.6) Пробуємо Last.fm
            try:
                logger.info("Provider: Last.fm")
                # Last.fm API для поиска треков
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Получаем API ключ из переменных окружения или используем демо
                    api_key = os.getenv('LASTFM_API_KEY', 'demo')
                    url = f"http://ws.audioscrobbler.com/2.0/?method=track.search&track={clean_query}&api_key={api_key}&format=json"
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            tracks = data.get('results', {}).get('trackmatches', {}).get('track', [])
                            if tracks:
                                # Берем первый трек и ищем его на YouTube
                                track = tracks[0]
                                artist = track.get('artist', '')
                                track_name = track.get('name', '')
                                search_query = f"{artist} {track_name}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Last.fm success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Last.fm error: {e}")

            # 2.7) Пробуємо Genius
            try:
                logger.info("Provider: Genius")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Genius API для поиска треков
                    access_token = os.getenv('GENIUS_ACCESS_TOKEN', 'demo')
                    headers = {'Authorization': f'Bearer {access_token}'}
                    url = f"https://api.genius.com/search?q={clean_query}"
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            hits = data.get('response', {}).get('hits', [])
                            if hits:
                                # Берем первый хит и ищем на YouTube
                                hit = hits[0]
                                result = hit.get('result', {})
                                artist = result.get('primary_artist', {}).get('name', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Genius success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Genius error: {e}")

            # 2.8) Пробуємо MusicBrainz
            try:
                logger.info("Provider: MusicBrainz")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # MusicBrainz API для поиска треков
                    url = f"https://musicbrainz.org/ws/2/recording?query={clean_query}&fmt=json"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            recordings = data.get('recordings', [])
                            if recordings:
                                # Берем первую запись и ищем на YouTube
                                recording = recordings[0]
                                artist = recording.get('artist-credit', [{}])[0].get('name', '')
                                title = recording.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"MusicBrainz success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"MusicBrainz error: {e}")

            # 2.9) Пробуємо Discogs
            try:
                logger.info("Provider: Discogs")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Discogs API для поиска треков
                    token = os.getenv('DISCOGS_TOKEN', 'demo')
                    headers = {'Authorization': f'Discogs token={token}'}
                    url = f"https://api.discogs.com/database/search?q={clean_query}&type=release"
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('title', '').split(' - ')[0] if ' - ' in result.get('title', '') else ''
                                title = result.get('title', '').split(' - ')[1] if ' - ' in result.get('title', '') else result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Discogs success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Discogs error: {e}")

            # 2.10) Пробуємо Rate Your Music
            try:
                logger.info("Provider: Rate Your Music")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # RYM API для поиска треков
                    url = f"https://rateyourmusic.com/api/search?q={clean_query}&type=album"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Rate Your Music success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Rate Your Music error: {e}")

            # 2.11) Пробуємо AllMusic
            try:
                logger.info("Provider: AllMusic")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # AllMusic API для поиска треков
                    url = f"https://www.allmusic.com/search/all/{clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            # Парсим HTML для поиска треков
                            html = await response.text()
                            # Простой поиск по HTML (можно улучшить с помощью BeautifulSoup)
                            if 'track' in html.lower() or 'song' in html.lower():
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{clean_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"AllMusic success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"AllMusic error: {e}")

            # 2.12) Пробуємо Pitchfork
            try:
                logger.info("Provider: Pitchfork")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Pitchfork API для поиска треков
                    url = f"https://pitchfork.com/api/v2/search/?query={clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Pitchfork success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Pitchfork error: {e}")

            # 2.13) Пробуємо NME
            try:
                logger.info("Provider: NME")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # NME API для поиска треков
                    url = f"https://www.nme.com/api/search?q={clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"NME success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"NME error: {e}")

            # 2.14) Пробуємо Rolling Stone
            try:
                logger.info("Provider: Rolling Stone")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Rolling Stone API для поиска треков
                    url = f"https://www.rollingstone.com/api/search?q={clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Rolling Stone success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Rolling Stone error: {e}")

            # 2.15) Пробуємо Billboard
            try:
                logger.info("Provider: Billboard")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Billboard API для поиска треков
                    url = f"https://www.billboard.com/api/search?q={clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Billboard success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Billboard error: {e}")

            # 2.16) Пробуємо додаткові варіанти пошуку на YouTube
            try:
                logger.info("Provider: YouTube Variants")
                # Пробуємо різні варіанти пошукового запиту
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' - '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' - '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' '),
                    # Дополнительные варианты для сложных названий
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip(),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' music',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' song',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' audio',
                    # Пробуємо тільки першу частину назви
                    clean_query.split('_')[0] if '_' in clean_query else clean_query,
                    # Пробуємо тільки другу частину назви
                    clean_query.split('_')[1] if '_' in clean_query and len(clean_query.split('_')) > 1 else clean_query,
                    # Дополнительные варианты для треков с подчеркиваниями
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' official',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' lyrics',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' remix',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' cover',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' slowed',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' sped up',
                    # Пробуємо без знаків пунктуації
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip().replace('.', '').replace('?', '').replace(':', ''),
                    # Пробуємо з різними розділювачами
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip().replace(' ', ' - '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip().replace(' ', ' | '),
                    # Пробуємо тільки ключові слова
                    ' '.join(clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip().split()[:3]),
                    ' '.join(clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip().split()[-3:]),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                            # Более агрессивные настройки для обхода блокировок
                            'extractor_args': {
                                'youtube': {
                                    'player_client': ['android', 'web'],
                                    'innertube_host': 'music.youtube.com',
                                    'api_key': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8',
                                    'client_version': '17.31.35',
                                }
                            },
                            'http_headers': {
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                            },
                            'retries': 3,
                            'sleep_interval': 1,
                            'max_sleep_interval': 5,
                            'username': None,
                            'password': None,
                            'netrc': False,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"ytsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуємо завантажити перше відео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"YouTube Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"YouTube Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"YouTube Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"YouTube Variants error: {e}")

            # 2.17) Пробуємо SoundCloud з різними варіантами
            try:
                logger.info("Provider: SoundCloud Variants")
                # Пробуємо різні варіанти пошукового запиту на SoundCloud
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                    # Дополнительные варианты для SoundCloud
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip(),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' music',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' song',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' track',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' beat',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' instrumental',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' remix',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' cover',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' slowed',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' sped up',
                    # Пробуємо тільки ключові слова
                    ' '.join(clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip().split()[:2]),
                    ' '.join(clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip().split()[-2:]),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"scsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуємо завантажити перше відео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"SoundCloud Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"SoundCloud Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"SoundCloud Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"SoundCloud Variants error: {e}")

            # 2.18) Пробуємо Bandcamp з різними варіантами
            try:
                logger.info("Provider: Bandcamp Variants")
                # Пробуємо різні варіанти пошукового запиту на Bandcamp
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"bandcampsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуємо завантажити перше відео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"Bandcamp Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"Bandcamp Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"Bandcamp Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"Bandcamp Variants error: {e}")

            # 2.19) Пробуємо Mixcloud з різними варіантами
            try:
                logger.info("Provider: Mixcloud Variants")
                # Пробуємо різні варіанти пошукового запиту на Mixcloud
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"mixcloudsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуємо завантажити перше відео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"Mixcloud Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"Mixcloud Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"Mixcloud Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"Mixcloud Variants error: {e}")

            # 2.20) Пробуємо Archive.org з різними варіантами
            try:
                logger.info("Provider: Archive.org Variants")
                # Пробуємо різні варіанти пошукового запиту на Archive.org
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"archiveorgsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуємо завантажити перше відео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"Archive.org Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"Archive.org Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"Archive.org Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"Archive.org Variants error: {e}")

        except Exception as e:
            logger.exception("Downloader fatal error")
            return None
        
        # Дополнительные провайдеры для увеличения шансов нахождения трека
        
        # 3.1) Пробуємо Last.fm + YouTube
        try:
            logger.info("Provider: Last.fm + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Last.fm
                lastfm_url = f"http://ws.audioscrobbler.com/2.0/?method=track.search&track={quote(clean_query)}&api_key=YOUR_API_KEY&format=json"
                async with session.get(lastfm_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'results' in data and 'trackmatches' in data['results']:
                            tracks = data['results']['trackmatches']['track']
                            if tracks:
                                # Берем первый трек
                                track = tracks[0] if isinstance(tracks, list) else tracks
                                artist = track.get('artist', '')
                                track_name = track.get('name', '')
                                
                                # Ищем на YouTube
                                youtube_query = f"{artist} {track_name}"
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
                                    'ignoreerrors': True,
                                }
                                
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(
                                        f"ytsearch1:{youtube_query}",
                                        download=True
                                    )
                                    
                                    if search_results:
                                        # Ищем скачанный файл
                                        import glob
                                        import time
                                        await asyncio.sleep(2)
                                        
                                        for file_path in glob.glob("downloads/*"):
                                            if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                                file_age = time.time() - os.path.getctime(file_path)
                                                if file_age < 30:
                                                    logger.info(f"Last.fm + YouTube success: {file_path}")
                                                    return file_path
        except Exception as e:
            logger.error(f"Last.fm + YouTube failed: {e}")
        
        # 3.2) Пробуємо Genius + YouTube
        try:
            logger.info("Provider: Genius + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Genius
                genius_url = f"https://api.genius.com/search?q={quote(clean_query)}"
                headers = {'Authorization': 'Bearer YOUR_ACCESS_TOKEN'}
                async with session.get(genius_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'response' in data and 'hits' in data['response']:
                            hits = data['response']['hits']
                            if hits:
                                # Берем первый хит
                                hit = hits[0]['result']
                                artist = hit.get('primary_artist', {}).get('name', '')
                                title = hit.get('title', '')
                                
                                # Ищем на YouTube
                                youtube_query = f"{artist} {title}"
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
                                    'ignoreerrors': True,
                                }
                                
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(
                                        f"ytsearch1:{youtube_query}",
                                        download=True
                                    )
                                    
                                    if search_results:
                                        # Ищем скачанный файл
                                        import glob
                                        import time
                                        await asyncio.sleep(2)
                                        
                                        for file_path in glob.glob("downloads/*"):
                                            if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                                file_age = time.time() - os.path.getctime(file_path)
                                                if file_age < 30:
                                                    logger.info(f"Genius + YouTube success: {file_path}")
                                                    return file_path
        except Exception as e:
            logger.error(f"Genius + YouTube failed: {e}")
        
        # 3.3) Пробуємо MusicBrainz + YouTube
        try:
            logger.info("Provider: MusicBrainz + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на MusicBrainz
                musicbrainz_url = f"https://musicbrainz.org/ws/2/recording?query={quote(clean_query)}&fmt=json"
                async with session.get(musicbrainz_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'recordings' in data and data['recordings']:
                            recording = data['recordings'][0]
                            title = recording.get('title', '')
                            artist = ''
                            if 'artist-credit' in recording:
                                artist_credit = recording['artist-credit'][0]
                                if 'name' in artist_credit:
                                    artist = artist_credit['name']
                            
                            # Ищем на YouTube
                            youtube_query = f"{artist} {title}"
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
                                'ignoreerrors': True,
                            }
                            
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                search_results = ydl.extract_info(
                                    f"ytsearch1:{youtube_query}",
                                    download=True
                                )
                                
                                if search_results:
                                    # Ищем скачанный файл
                                    import glob
                                    import time
                                    await asyncio.sleep(2)
                                    
                                    for file_path in glob.glob("downloads/*"):
                                        if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                            file_age = time.time() - os.path.getctime(file_path)
                                            if file_age < 30:
                                                logger.info(f"MusicBrainz + YouTube success: {file_path}")
                                                return file_path
        except Exception as e:
            logger.error(f"MusicBrainz + YouTube failed: {e}")
        
        # 3.4) Пробуємо Discogs + YouTube
        try:
            logger.info("Provider: Discogs + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Discogs
                discogs_url = f"https://api.discogs.com/database/search?q={quote(clean_query)}&type=release"
                headers = {'User-Agent': 'SpotifyBot/1.0'}
                async with session.get(discogs_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'results' in data and data['results']:
                            result = data['results'][0]
                            title = result.get('title', '')
                            artist = result.get('artist', '')
                            
                            # Ищем на YouTube
                            youtube_query = f"{artist} {title}"
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
                                'ignoreerrors': True,
                            }
                            
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                search_results = ydl.extract_info(
                                    f"ytsearch1:{youtube_query}",
                                    download=True
                                )
                                
                                if search_results:
                                    # Ищем скачанный файл
                                    import glob
                                    import time
                                    await asyncio.sleep(2)
                                    
                                    for file_path in glob.glob("downloads/*"):
                                        if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                            file_age = time.time() - os.path.getctime(file_path)
                                            if file_age < 30:
                                                logger.info(f"Discogs + YouTube success: {file_path}")
                                                return file_path
        except Exception as e:
            logger.error(f"Discogs + YouTube failed: {e}")
        
        # 3.5) Пробуємо Rate Your Music + YouTube
        try:
            logger.info("Provider: Rate Your Music + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Rate Your Music
                rym_url = f"https://rateyourmusic.com/search?searchterm={quote(clean_query)}&searchtype=l"
                async with session.get(rym_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Rate Your Music + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Rate Your Music + YouTube failed: {e}")
        
        # 3.6) Пробуємо AllMusic + YouTube
        try:
            logger.info("Provider: AllMusic + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на AllMusic
                allmusic_url = f"https://www.allmusic.com/search/all/{quote(clean_query)}"
                async with session.get(allmusic_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"AllMusic + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"AllMusic + YouTube failed: {e}")
        
        # 3.7) Пробуємо Pitchfork + YouTube
        try:
            logger.info("Provider: Pitchfork + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Pitchfork
                pitchfork_url = f"https://pitchfork.com/search/?query={quote(clean_query)}"
                async with session.get(pitchfork_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Pitchfork + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Pitchfork + YouTube failed: {e}")
        
        # 3.8) Пробуємо NME + YouTube
        try:
            logger.info("Provider: NME + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на NME
                nme_url = f"https://www.nme.com/search?q={quote(clean_query)}"
                async with session.get(nme_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"NME + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"NME + YouTube failed: {e}")
        
        # 3.9) Пробуємо Rolling Stone + YouTube
        try:
            logger.info("Provider: Rolling Stone + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Rolling Stone
                rollingstone_url = f"https://www.rollingstone.com/search/?q={quote(clean_query)}"
                async with session.get(rollingstone_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Rolling Stone + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Rolling Stone + YouTube failed: {e}")
        
        # 3.10) Пробуємо Billboard + YouTube
        try:
            logger.info("Provider: Billboard + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Billboard
                billboard_url = f"https://www.billboard.com/search?q={quote(clean_query)}"
                async with session.get(billboard_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Billboard + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Billboard + YouTube failed: {e}")
        
        # Дополнительные музыкальные сервисы для максимального покрытия
        
        # 4.1) Пробуємо Spotify Web API + YouTube
        try:
            logger.info("Provider: Spotify Web + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Spotify Web API (публичный поиск)
                spotify_url = f"https://api.spotify.com/v1/search?q={quote(clean_query)}&type=track&limit=1"
                headers = {'Accept': 'application/json'}
                async with session.get(spotify_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'tracks' in data and 'items' in data['tracks'] and data['tracks']['items']:
                            track = data['tracks']['items'][0]
                            artist = track.get('artists', [{}])[0].get('name', '')
                            title = track.get('name', '')
                            
                            # Ищем на YouTube
                            youtube_query = f"{artist} {title}"
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
                                'ignoreerrors': True,
                            }
                            
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                search_results = ydl.extract_info(
                                    f"ytsearch1:{youtube_query}",
                                    download=True
                                )
                                
                                if search_results:
                                    # Ищем скачанный файл
                                    import glob
                                    import time
                                    await asyncio.sleep(2)
                                    
                                    for file_path in glob.glob("downloads/*"):
                                        if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                            file_age = time.time() - os.path.getctime(file_path)
                                            if file_age < 30:
                                                logger.info(f"Spotify Web + YouTube success: {file_path}")
                                                return file_path
        except Exception as e:
            logger.error(f"Spotify Web + YouTube failed: {e}")
        
        # 4.2) Пробуємо Apple Music + YouTube
        try:
            logger.info("Provider: Apple Music + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Apple Music (публичный поиск)
                apple_url = f"https://itunes.apple.com/search?term={quote(clean_query)}&media=music&limit=1"
                async with session.get(apple_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'results' in data and data['results']:
                            track = data['results'][0]
                            artist = track.get('artistName', '')
                            title = track.get('trackName', '')
                            
                            # Ищем на YouTube
                            youtube_query = f"{artist} {title}"
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
                                'ignoreerrors': True,
                            }
                            
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                search_results = ydl.extract_info(
                                    f"ytsearch1:{youtube_query}",
                                    download=True
                                )
                                
                                if search_results:
                                    # Ищем скачанный файл
                                    import glob
                                    import time
                                    await asyncio.sleep(2)
                                    
                                    for file_path in glob.glob("downloads/*"):
                                        if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                            file_age = time.time() - os.path.getctime(file_path)
                                            if file_age < 30:
                                                logger.info(f"Apple Music + YouTube success: {file_path}")
                                                return file_path
        except Exception as e:
            logger.error(f"Apple Music + YouTube failed: {e}")
        
        # 4.3) Пробуємо Tidal + YouTube
        try:
            logger.info("Provider: Tidal + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Tidal (публичный поиск)
                tidal_url = f"https://api.tidal.com/v1/search?query={quote(clean_query)}&limit=1&types=TRACKS"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(tidal_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'tracks' in data and data['tracks']:
                            track = data['tracks'][0]
                            artist = track.get('artist', {}).get('name', '')
                            title = track.get('title', '')
                            
                            # Ищем на YouTube
                            youtube_query = f"{artist} {title}"
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
                                'ignoreerrors': True,
                            }
                            
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                search_results = ydl.extract_info(
                                    f"ytsearch1:{youtube_query}",
                                    download=True
                                )
                                
                                if search_results:
                                    # Ищем скачанный файл
                                    import glob
                                    import time
                                    await asyncio.sleep(2)
                                    
                                    for file_path in glob.glob("downloads/*"):
                                        if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                            file_age = time.time() - os.path.getctime(file_path)
                                            if file_age < 30:
                                                logger.info(f"Tidal + YouTube success: {file_path}")
                                                return file_path
        except Exception as e:
            logger.error(f"Tidal + YouTube failed: {e}")
        
        # 4.4) Пробуємо Amazon Music + YouTube
        try:
            logger.info("Provider: Amazon Music + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Amazon Music (публичный поиск)
                amazon_url = f"https://music.amazon.com/search?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(amazon_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Amazon Music + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Amazon Music + YouTube failed: {e}")
        
        # 4.5) Пробуем Pandora + YouTube
        try:
            logger.info("Provider: Pandora + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Pandora (публичный поиск)
                pandora_url = f"https://www.pandora.com/search?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(pandora_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Pandora + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Pandora + YouTube failed: {e}")
        
        # 4.6) Пробуем iHeartRadio + YouTube
        try:
            logger.info("Provider: iHeartRadio + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через iHeartRadio (публичный поиск)
                iheart_url = f"https://www.iheart.com/search/?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(iheart_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"iHeartRadio + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"iHeartRadio + YouTube failed: {e}")
        
        # 4.7) Пробуем TuneIn + YouTube
        try:
            logger.info("Provider: TuneIn + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через TuneIn (публичный поиск)
                tunein_url = f"https://tunein.com/search/?query={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(tunein_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"TuneIn + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"TuneIn + YouTube failed: {e}")
        
        # 4.8) Пробуем Shazam + YouTube
        try:
            logger.info("Provider: Shazam + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Shazam (публичный поиск)
                shazam_url = f"https://www.shazam.com/search?term={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(shazam_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Shazam + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Shazam + YouTube failed: {e}")
        
        # 4.9) Пробуем SoundHound + YouTube
        try:
            logger.info("Provider: SoundHound + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через SoundHound (публичный поиск)
                soundhound_url = f"https://www.soundhound.com/search?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(soundhound_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"SoundHound + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"SoundHound + YouTube failed: {e}")
        
        # 4.10) Пробуем AHA Music + YouTube
        try:
            logger.info("Provider: AHA Music + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через AHA Music (публичный поиск)
                aha_url = f"https://www.ahamusic.com/search?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(aha_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"AHA Music + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"AHA Music + YouTube failed: {e}")
        
        # 4.11) Пробуем Musixmatch + YouTube
        try:
            logger.info("Provider: Musixmatch + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Musixmatch (публичный поиск)
                musixmatch_url = f"https://www.musixmatch.com/search/{quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(musixmatch_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Musixmatch + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Musixmatch + YouTube failed: {e}")
        
        # 4.12) Пробуем Lyrics.com + YouTube
        try:
            logger.info("Provider: Lyrics.com + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Lyrics.com (публичный поиск)
                lyrics_url = f"https://www.lyrics.com/search.php?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(lyrics_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Lyrics.com + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Lyrics.com + YouTube failed: {e}")
        
        # 4.13) Пробуем SongMeanings + YouTube
        try:
            logger.info("Provider: SongMeanings + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через SongMeanings (публичный поиск)
                songmeanings_url = f"https://songmeanings.com/search/?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(songmeanings_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"SongMeanings + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"SongMeanings + YouTube failed: {e}")
        
        # 4.14) Пробуем Songfacts + YouTube
        try:
            logger.info("Provider: Songfacts + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Songfacts (публичный поиск)
                songfacts_url = f"https://www.songfacts.com/search.php?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(songfacts_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Songfacts + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Songfacts + YouTube failed: {e}")
        
        # 4.15) Пробуем Songkick + YouTube
        try:
            logger.info("Provider: Songkick + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек через Songkick (публичный поиск)
                songkick_url = f"https://www.songkick.com/search?q={quote(clean_query)}"
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                async with session.get(songkick_url, headers=headers) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
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
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Songkick + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Songkick + YouTube failed: {e}")
        
        # Якщо нічого не знайдено
        logger.info("All providers failed to find the track")
        return None


@dp.message(Command("start"))
async def start_handler(message: Message):
    """Обробник команди /start"""
    welcome_text = """
🎵 Привіт! Я Spotify Music Bot

Просто надішли мені посилання на трек, плейлист або альбом з Spotify, і я знайду та надішлю тобі MP3 файл.

Команди:
/start - Почати роботу
/help - Допомога

Обмеження:
• Плейлисти та альбоми: максимум 15 треків
• Розмір файлу: максимум 50MB
    """
    
    await message.answer(welcome_text)


@dp.message(Command("status"))
async def status_command(message: Message):
    """Показує статус бота та активних завантажень"""
    global active_downloads
    
    status_text = (
        f"🤖 **Статус бота**\n\n"
        f"🔄 Активних завантажень: {active_downloads}/3\n"
        f"🎵 FFmpeg доступний: {'✅' if is_ffmpeg_available() else '❌'}\n"
        f"🎧 Spotify API: {'✅' if spotify_client_id and spotify_client_secret else '❌'}\n"
        f"🌐 Провайдерів: 25+\n\n"
        f"💡 **Можливості:**\n"
        f"• Пошук за Spotify посиланнями\n"
        f"• Пошук за назвою треку\n"
        f"• Фільтрація оригінальних версій\n"
        f"• Паралельна обробка запитів\n"
        f"• 25+ джерел музики"
    )
    
    await message.answer(status_text, parse_mode="Markdown")


@dp.message(Command("help"))
async def help_handler(message: Message):
    """Обробник команди /help"""
    help_text = """
📖 Допомога з використанням бота

Як користуватися:
1. Скопіюй посилання на трек, плейлист або альбом з Spotify
2. Надішли посилання боту
3. Дочекайся обробки та отримання MP3 файлу

Підтримувані формати:
• Треки: https://open.spotify.com/track/...
• Плейлисти: https://open.spotify.com/playlist/...
• Альбоми: https://open.spotify.com/album/...

Приклади посилань:
• https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh
• https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
• https://open.spotify.com/album/1A2GTWGtFfWp7KSQTwWOyo

Обмеження:
• Плейлисти та альбоми: максимум 15 треків
• Розмір файлу: максимум 50MB
• Якість: 192kbps MP3

Примітка: Бот працює через пошук у YouTube, тому якість може варіюватися.
    """
    
    await message.answer(help_text)


@dp.message(Command("admin"))
async def admin_handler(message: Message):
    if message.from_user.id != 810944378:
        await message.reply("⛔️ У вас нет доступа к админ-команде.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="show_stats")]
    ])
    await message.reply("🔐 Админ-панель", reply_markup=keyboard)

# Callback для статистики
@dp.callback_query(F.data == "show_stats")
async def show_stats_callback(call: types.CallbackQuery):
    if call.from_user.id != 810944378:
        await call.answer("Нет доступа.", show_alert=True)
        return
    unique_users = len(user_requests_today)
    await call.answer(
        f"👤 Уникальных пользователей за сегодня: {unique_users}\n📊 Всего запросов: {requests_today}",
        show_alert=True
    )


@dp.message(F.text)
async def process_spotify_link(message: Message):
    """Обробник посилань Spotify"""
    global user_requests_today, requests_today, request_day
    # Фиксируем день, сбрасываем если дата сменилась (по UTC)
    today = datetime.utcnow().strftime('%Y-%m-%d')
    if today != request_day:
        user_requests_today.clear()
        requests_today = 0
        request_day = today

    # Статистика: сколько пользователей и сколько запросов
    uid = message.from_user.id
    user_requests_today[uid] = user_requests_today.get(uid, 0) + 1
    requests_today += 1

    text = message.text.strip()
    
    # Надсилаємо повідомлення про початок обробки
    processing_msg = await message.answer("🔄 Обробляю посилання...")
    
    try:
        # Витягуємо ID з посилання (тепер асинхронно)
        ids = await spotify_parser.extract_ids_from_url(text)
        
        if not any(ids.values()):
            await processing_msg.edit_text("❌ Будь ласка, надішліть посилання на трек або плейлист Spotify.")
            return
        
        if ids['track']:
            # Обробляємо трек
            await process_track(message, ids['track'], processing_msg)
        elif ids['playlist']:
            # Обробляємо плейлист
            await process_playlist(message, ids['playlist'], processing_msg)
        elif ids['album']:
            # Обробляємо альбом
            await process_album(message, ids['album'], processing_msg)
        else:
            await processing_msg.edit_text("❌ Не вдалося розпізнати посилання Spotify.")
            
    except Exception as e:
        logger.error(f"Error processing Spotify link: {e}")
        await processing_msg.edit_text("❌ Сталася помилка при обробці посилання.")


async def process_track(message: Message, track_id: str, processing_msg: types.Message):
    """Обрабатывает отдельный трек"""
    global active_downloads
    
    # Проверяем, не превышен ли лимит одновременных загрузок
    if active_downloads >= 3:
        await processing_msg.edit_text("⏳ Слишком много запросов одновременно. Попробуйте через минуту.")
        return
    
    # Збільшуємо лічильник активних завантажень
    active_downloads += 1
    
    try:
        # Получаем информацию о треке
        track_info = await spotify_parser.get_track_info(track_id)
        
        if not track_info:
            await processing_msg.edit_text("❌ Не вдалося отримати інформацію про трек.")
            return
        
        # Оновлюємо повідомлення
        await processing_msg.edit_text(
            f"🎵 Знайдено трек: {track_info['name']} - {track_info['artist']}\n"
            f"⏱️ Тривалість: {track_info['duration_formatted']}\n"
            f"🔄 Шукаю та завантажую... (активних завантажень: {active_downloads})"
        )
        
        # Формуємо пошуковий запит
        search_query = spotify_parser.create_search_query(track_info)
        
        # Используем семафор для ограничения одновременных загрузок
        async with download_semaphore:
            file_path = await MusicDownloader.search_and_download(search_query, track_info)
        
        # Добавляем подробное логирование для отладки
        logger.info(f"Download result: file_path={file_path}")
        if file_path:
            logger.info(f"File exists: {os.path.exists(file_path)}")
            if os.path.exists(file_path):
                logger.info(f"File size: {os.path.getsize(file_path)} bytes")
                logger.info(f"File path resolved: {os.path.abspath(file_path)}")
            else:
                logger.error(f"File does not exist at path: {file_path}")
        else:
            logger.error("No file path returned from downloader")
        
        if file_path and os.path.exists(file_path):
            # Получаем размер файла
            file_size = os.path.getsize(file_path)
            logger.info(f"Sending file: {file_path} (size: {file_size} bytes)")
            
            # Проверяем формат файла и конвертируем если нужно
            file_extension = os.path.splitext(file_path)[1].lower()
            logger.info(f"File extension: {file_extension}")
            
            if file_extension not in ['.mp3', '.m4a', '.aac', '.ogg', '.wav', '.webm']:
                logger.error(f"Unsupported file format: {file_extension}")
                await processing_msg.edit_text("❌ Неподдерживаемый формат файла.")
                os.remove(file_path)
                return
            
            # Конвертируем в MP3 только если файл НЕ в MP3 формате
            if file_extension != '.mp3':
                try:
                    # Проверяем размер файла - если слишком маленький, пропускаем конвертацию
                    if file_size < 10000:  # Меньше 10KB - вероятно поврежденный файл
                        logger.warning(f"File too small ({file_size} bytes), skipping conversion")
                        await processing_msg.edit_text("❌ Файл слишком маленький или поврежден.")
                        os.remove(file_path)
                        return
                    else:
                        import subprocess
                        import tempfile
                    
                        # Создаем временный файл для конвертации
                        mp3_path = file_path.replace(file_extension, '.mp3')
                        
                        # Используем FFmpeg напрямую для конвертации с дополнительными параметрами
                        ffmpeg_cmd = [
                            'ffmpeg',
                            '-f', 'aac',  # Указываем формат явно
                            '-i', file_path,
                            '-acodec', 'mp3',
                            '-ab', '192k',
                            '-ar', '44100',
                            '-ac', '2',
                            '-avoid_negative_ts', 'make_zero',
                            '-fflags', '+genpts',
                            '-y',  # Перезаписываем файл если существует
                            mp3_path
                        ]
                        
                        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=60)
                        
                        if result.returncode == 0 and os.path.exists(mp3_path):
                            # Проверяем размер нового файла
                            new_size = os.path.getsize(mp3_path)
                            if new_size > 1000:  # Новый файл должен быть больше 1KB
                                # Удаляем оригинальный файл
                                os.remove(file_path)
                                file_path = mp3_path
                                file_size = new_size
                                logger.info(f"Successfully converted to MP3: {file_path} ({file_size} bytes)")
                            else:
                                logger.error(f"Converted file too small: {new_size} bytes")
                                os.remove(mp3_path)
                                raise Exception("Converted file too small")
                        else:
                            logger.error(f"FFmpeg conversion failed: {result.stderr}")
                            # Если FFmpeg не смог конвертировать, пробуем отправить оригинальный файл
                            raise Exception(f"FFmpeg failed: {result.stderr}")
                            
                except Exception as conversion_error:
                    logger.error(f"Conversion error: {conversion_error}")
                    # Якщо конвертація не вдалася, видаляємо файл та повідомляємо про помилку
                    await processing_msg.edit_text("❌ Не вдалося конвертувати файл у MP3.")
                    os.remove(file_path)
                    return
            
            # Отправляем файл (теперь он всегда в MP3 формате)
            try:
                # Создаем красивое название файла только с названием трека
                clean_track_name = clean_filename(track_info['name'])
                
                # Отправляем файл с кастомным именем (всегда .mp3)
                await message.answer_document(
                    document=types.FSInputFile(file_path, filename=f"{clean_track_name}.mp3"),
                    caption=f"🎵 {track_info['name']} - {track_info['artist']}\n"
                           f"⏱️ {track_info['duration_formatted']} | 📁 {format_file_size(file_size)}"
                )
                
                # Удаляем временный файл
                os.remove(file_path)
                logger.info(f"MP3 file sent successfully and removed: {file_path}")
                
                await processing_msg.delete()
            except Exception as send_error:
                logger.error(f"Error sending file: {send_error}")
                await processing_msg.edit_text(f"❌ Помилка відправки файлу: {send_error}")
        else:
            logger.error(f"File not found or invalid path: {file_path}")
            await processing_msg.edit_text("❌ Не вдалося знайти або завантажити трек.")
            
    except Exception as e:
        logger.error(f"Error processing track: {e}")
        await processing_msg.edit_text("❌ Сталася помилка при обробці треку.")
    finally:
        # Зменшуємо лічильник активних завантажень
        active_downloads -= 1


async def process_playlist(message: Message, playlist_id: str, processing_msg: types.Message):
    """Обрабатывает плейлист"""
    try:
        # Получаем информацию о плейлисте
        playlist_info = await spotify_parser.get_playlist_info(playlist_id)
        
        if not playlist_info:
            await processing_msg.edit_text("❌ Не вдалося отримати інформацію про плейлист.")
            return
        
        tracks = playlist_info['tracks']
        
        if len(tracks) > 50:
            await processing_msg.edit_text(
                f"⚠️ Плейлист '{playlist_info['name']}' містить {len(tracks)} треків.\n"
                f"Для великих плейлистів рекомендується обробляти треки окремо.\n"
                f"Максимум для обробки: 15 треків."
            )
            return
        
        # Оновлюємо повідомлення
        await processing_msg.edit_text(
            f"🎵 Плейлист: {playlist_info['name']}\n"
            f"👤 Автор: {playlist_info['owner']}\n"
            f"📊 Треків: {len(tracks)}\n"
            f"🔄 Починаю завантаження..."
        )
        
        downloaded_count = 0
        
        for i, track in enumerate(tracks, 1):
            try:
                # Оновлюємо прогрес
                await processing_msg.edit_text(
                    f"🎵 Плейлист: {playlist_info['name']}\n"
                    f"📥 Завантажую {i}/{len(tracks)}: {track['name']} - {track['artist']}"
                )
                
                # Формуємо пошуковий запит
                search_query = spotify_parser.create_search_query(track)
                
                # Скачиваем музыку
                file_path = await MusicDownloader.search_and_download(search_query, track)
                
                if file_path and os.path.exists(file_path):
                    # Получаем размер файла
                    file_size = os.path.getsize(file_path)
                    
                    # Отправляем файл
                    await message.answer_document(
                        document=types.FSInputFile(file_path),
                        caption=f"🎵 {track['name']} - {track['artist']}\n"
                               f"⏱️ {track['duration_formatted']} | 📁 {format_file_size(file_size)}"
                    )
                    
                    # Удаляем временный файл
                    os.remove(file_path)
                    downloaded_count += 1
                    
                    # Небольшая пауза между скачиваниями
                    await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error downloading track {track['name']}: {e}")
                continue
        
        await processing_msg.edit_text(
            f"✅ Завантаження завершено!\n"
            f"🎵 Плейлист: {playlist_info['name']}\n"
            f"📊 Успішно завантажено: {downloaded_count}/{len(tracks)} треків"
        )
        
    except Exception as e:
        logger.error(f"Error processing playlist: {e}")
        await processing_msg.edit_text("❌ Сталася помилка при обробці плейлисту.")


async def process_album(message: Message, album_id: str, processing_msg: types.Message):
    """Обрабатывает альбом"""
    try:
        # Получаем информацию об альбоме
        album_info = await spotify_parser.get_album_info(album_id)
        
        if not album_info:
            await processing_msg.edit_text("❌ Не вдалося отримати інформацію про альбом.")
            return
        
        tracks = album_info['tracks']
        
        if len(tracks) > 15:
            await processing_msg.edit_text(
                f"⚠️ Альбом '{album_info['name']}' містить {len(tracks)} треків.\n"
                f"Для великих альбомів рекомендується обробляти треки окремо.\n"
                f"Максимум для обробки: 15 треків."
            )
            return
        
        # Оновлюємо повідомлення
        await processing_msg.edit_text(
            f"🎵 Альбом: {album_info['name']}\n"
            f"👤 Виконавець: {album_info['artist']}\n"
            f"📅 Рік: {album_info['release_date']}\n"
            f"📊 Треків: {len(tracks)}\n"
            f"🔄 Починаю завантаження..."
        )
        
        downloaded_count = 0
        
        for i, track in enumerate(tracks, 1):
            try:
                # Оновлюємо прогрес
                await processing_msg.edit_text(
                    f"🎵 Альбом: {album_info['name']}\n"
                    f"📥 Завантажую {i}/{len(tracks)}: {track['name']}"
                )
                
                # Формуємо пошуковий запит
                search_query = spotify_parser.create_search_query(track)
                
                # Скачиваем музыку
                file_path = await MusicDownloader.search_and_download(search_query, track)
                
                if file_path and os.path.exists(file_path):
                    # Получаем размер файла
                    file_size = os.path.getsize(file_path)
                    
                    # Отправляем файл
                    await message.answer_document(
                        document=types.FSInputFile(file_path),
                        caption=f"🎵 {track['name']} - {track['artist']}\n"
                               f"⏱️ {track['duration_formatted']} | 📁 {format_file_size(file_size)}"
                    )
                    
                    # Удаляем временный файл
                    os.remove(file_path)
                    downloaded_count += 1
                    
                    # Небольшая пауза между скачиваниями
                    await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error downloading track {track['name']}: {e}")
                continue
        
        await processing_msg.edit_text(
            f"✅ Завантаження завершено!\n"
            f"🎵 Альбом: {album_info['name']}\n"
            f"📊 Успішно завантажено: {downloaded_count}/{len(tracks)} треків"
        )
        
    except Exception as e:
        logger.error(f"Error processing album: {e}")
        await processing_msg.edit_text("❌ Сталася помилка при обробці альбому.")


async def health_check(request):
    """Health check endpoint для Railway"""
    return web.Response(text="Spotify Music Bot is running", status=200)

async def main():
    """Основная функция"""
    # Проверяем переменные окружения
    if not os.getenv('TELEGRAM_TOKEN'):
        logger.error("TELEGRAM_TOKEN not found in environment variables")
        return
    
    # Создаем папку для загрузок
    os.makedirs("downloads", exist_ok=True)
    
    logger.info("Starting Spotify Music Bot...")
    logger.info(f"FFmpeg available: {is_ffmpeg_available()}")
    logger.info(f"Spotify API configured: {bool(spotify_client_id and spotify_client_secret)}")
    
    # Создаем HTTP сервер для health check
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    # Запускаем HTTP сервер в фоне
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"HTTP server started on port {port}")
    
    try:
        # Запускаем Telegram бота с обработкой конфликтов
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logger.error(f"Bot startup error: {e}")
        # Если ошибка связана с конфликтом, ждем и перезапускаем
        if "Conflict" in str(e) or "terminated by other getUpdates" in str(e):
            logger.info("Detected Telegram conflict, waiting 10 seconds before retry...")
            await asyncio.sleep(10)
            try:
                await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
            except Exception as retry_error:
                logger.error(f"Retry failed: {retry_error}")
                raise
        else:
            raise


if __name__ == "__main__":
    asyncio.run(main())

