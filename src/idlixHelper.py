"""
Helper Class for IDLIX Downloader & IDLIX Player CLI
Updated for Next.js & Pentos API architecture (z2.idlixku.com)
"""

import os
import random
import re
import json
import m3u8
import shutil
import zipfile
import time
import requests
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, urljoin
from vtt_to_srt.vtt_to_srt import ConvertFile
from curl_cffi import requests as cffi_requests
from src.CryptoJsAesHelper import CryptoJsAes, dec


class IdlixHelper:
    BASE_WEB_URL = "https://z2.idlixku.com/"
    BASE_API_URL = "https://z2.idlixku.com/api"
    BASE_STATIC_HEADERS = {
        "Referer": BASE_WEB_URL,
        "Origin": "https://z2.idlixku.com",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,id;q=0.8"
    }

    def __init__(self):
        self.poster = None
        self.m3u8_url = None
        self.video_id = None
        self.movie_slug = None
        self.embed_url = None
        self.video_name = None
        self.is_subtitle = False
        self.subtitles_list = []
        self.variant_playlist = None
        self.media_type = "movie"
        self.series_slug = None
        self.season_number = None
        self.episode_number = None
        self.series_data = None
        self.request = cffi_requests.Session(
            impersonate=random.choice(["chrome124", "chrome119"]),
            headers=self.BASE_STATIC_HEADERS,
            debug=False,
        )

        # FFMPEG Check
        if os.name == 'nt':
            for _ in os.environ.get('path', '').split(';'):
                if 'ffmpeg' in _:
                    logger.info(f'FFMPEG Found: {_}')
                    break
            else:
                if not os.path.exists('ffmpeg-release-essentials.zip'):
                    self.download_ffmpeg()
                logger.warning('FFMPEG not set in PATH, Trying set PATH')
                try:
                    with zipfile.ZipFile('ffmpeg-release-essentials.zip', 'r') as zip_ref:
                        zip_ref.extractall(
                            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')
                        )
                    logger.success('Success Extracting ffmpeg')
                    path = ""
                    for _ in os.listdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')):
                        if 'ffmpeg' in _:
                            logger.info(f'Found: {os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", _, "bin")}')
                            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", _, "bin")
                            break
                    else:
                        logger.error('FFMPEG not found, please install ffmpeg first before running this script')
                    subprocess.call(["setx", "PATH", "%PATH%;" + path])
                    logger.success('FFMPEG PATH set successfully, Please restart the program')
                    exit()
                except Exception as e:
                    print(f'Error: {e}')
        else:
            if not shutil.which('ffmpeg'):
                logger.error('FFMPEG not found, please install ffmpeg first before running this script')
                exit()

    @staticmethod
    def download_ffmpeg():
        try:
            logger.info('Downloading ffmpeg')
            content = requests.get(
                url='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
                stream=True
            )
            with open("ffmpeg-release-essentials.zip", mode="wb") as file:
                for chunk in content.iter_content(chunk_size=1024):
                    print(
                        '\rDownloading: {} MB of {} MB'.format(
                            round(os.path.getsize('ffmpeg-release-essentials.zip') / 1024 / 1024, 2),
                            round(int(content.headers.get('Content-Length', 0)) / 1024 / 1024, 2)
                        ),
                        end=''
                    )
                    file.write(chunk)
            print()
            logger.success('Downloaded ffmpeg')
        except Exception as e:
            print(f'Error: {e}')

    @staticmethod
    def parse_url(url: str) -> dict:
        """Parse IDLIX URL into media type (episode, series, movie) and identifiers"""
        clean = url.strip().rstrip('/')
        # Match episode: /series/[slug]/season/[season]/episode/[episode]
        ep_match = re.search(r'/series/([^/]+)/season/(\d+)/episode/(\d+)', clean, re.IGNORECASE)
        if ep_match:
            return {
                'type': 'episode',
                'slug': ep_match.group(1),
                'season': int(ep_match.group(2)),
                'episode': int(ep_match.group(3))
            }
        # Match series: /series/[slug]
        series_match = re.search(r'/series/([^/]+)', clean, re.IGNORECASE)
        if series_match:
            return {
                'type': 'series',
                'slug': series_match.group(1).split('?')[0].split('/')[0]
            }
        # Match movie: /movie/[slug]
        movie_match = re.search(r'/movie/([^/]+)', clean, re.IGNORECASE)
        if movie_match:
            return {
                'type': 'movie',
                'slug': movie_match.group(1).split('?')[0].split('/')[0]
            }
        # Fallback slug
        slug = clean.split('?')[0].split('/')[-1]
        return {
            'type': 'unknown',
            'slug': slug
        }

    @staticmethod
    def extract_slug(url: str) -> str:
        parsed = IdlixHelper.parse_url(url)
        return parsed['slug']

    def get_home(self):
        """Fetch featured / browse movies list for CLI and GUI"""
        try:
            # 1. Try browse API
            res = self.request.get(f"{self.BASE_API_URL}/browse", timeout=12)
            if res.status_code == 200:
                data = res.json()
                items = data.get('data', [])
                tmp_featured = []
                for it in items:
                    slug = it.get('slug')
                    if not slug:
                        continue
                    poster_path = it.get('posterPath') or it.get('backdropPath') or ''
                    if poster_path and not poster_path.startswith('http'):
                        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                    else:
                        poster_url = poster_path
                    title = it.get('title') or slug.replace('-', ' ').title()
                    year = str(it.get('releaseYear') or '')
                    tmp_featured.append({
                        'url': f"{self.BASE_WEB_URL}movie/{slug}",
                        'title': title,
                        'year': year,
                        'type': 'movie',
                        'poster': poster_url,
                    })
                if tmp_featured:
                    return {'status': True, 'featured_movie': tmp_featured}

            # 2. Fallback to scraping homepage HTML
            res_html = self.request.get(self.BASE_WEB_URL, timeout=12)
            if res_html.status_code == 200:
                bs = BeautifulSoup(res_html.text, 'html.parser')
                tmp_featured = []
                seen = set()
                for a in bs.find_all('a'):
                    href = a.get('href', '')
                    if '/movie/' in href:
                        slug = self.extract_slug(href)
                        if slug and slug not in seen:
                            seen.add(slug)
                            img = a.find('img')
                            poster = ''
                            title = slug.replace('-', ' ').title()
                            if img:
                                poster = img.get('src') or img.get('data-src') or ''
                                title = img.get('alt') or title
                            tmp_featured.append({
                                'url': f"{self.BASE_WEB_URL}movie/{slug}",
                                'title': title,
                                'year': '',
                                'type': 'movie',
                                'poster': poster,
                            })
                return {'status': True, 'featured_movie': tmp_featured}

            return {'status': False, 'message': 'Failed to get home page'}
        except Exception as error_get_home:
            return {'status': False, 'message': str(error_get_home)}

    def get_season_episodes(self, slug: str, season_num: int):
        """Fetch list of episodes for a specific season of a TV series"""
        try:
            res = self.request.get(f"{self.BASE_API_URL}/series/{slug}/season/{season_num}", timeout=12)
            if res.status_code == 200:
                data = res.json()
                episodes = data.get('season', {}).get('episodes', [])
                return {'status': True, 'episodes': episodes}
            return {'status': False, 'message': f'Failed to fetch season episodes: {res.status_code}'}
        except Exception as e:
            return {'status': False, 'message': str(e)}

    def get_episode_data(self, slug: str, season_num: int, episode_num: int):
        """Fetch specific episode details and configure media state"""
        try:
            res = self.request.get(
                f"{self.BASE_API_URL}/series/{slug}/season/{season_num}/episode/{episode_num}",
                timeout=12
            )
            if res.status_code == 200:
                data = res.json()
                series = data.get('series', {})
                season = data.get('season', {})
                episode = data.get('episode', {})

                self.media_type = 'episode'
                self.video_id = episode.get('id')
                self.series_slug = slug
                self.season_number = season_num
                self.episode_number = episode_num

                series_title = series.get('title') or slug.replace('-', ' ').title()
                ep_num = episode.get('episodeNumber') or episode_num
                ep_name = episode.get('name')
                if ep_name:
                    title = f"{series_title} S{season_num:02d}E{ep_num:02d} - {ep_name}"
                else:
                    title = f"{series_title} S{season_num:02d}E{ep_num:02d}"

                self.video_name = re.sub(r'[\\/*?:"<>|]', '', title).strip()

                still_path = episode.get('stillPath') or series.get('backdropPath') or series.get('posterPath') or ''
                if still_path and not still_path.startswith('http'):
                    self.poster = f"https://image.tmdb.org/t/p/w500{still_path}"
                else:
                    self.poster = still_path

                return {
                    'status': True,
                    'video_id': self.video_id,
                    'video_name': self.video_name,
                    'poster': self.poster,
                    'media_type': 'episode',
                    'series_title': series_title,
                    'season_number': season_num,
                    'episode_number': ep_num,
                    'episode_name': ep_name
                }
            return {'status': False, 'message': f'Episode not found on server (status {res.status_code})'}
        except Exception as e:
            return {'status': False, 'message': str(e)}

    def get_video_data(self, url: str):
        """Fetch movie or series details and internal ID from URL or slug"""
        if not url:
            return {'status': False, 'message': 'URL is required'}

        parsed = self.parse_url(url)
        slug = parsed['slug']
        self.movie_slug = slug

        # Case 1: Direct episode URL (/series/[slug]/season/[s]/episode/[e])
        if parsed['type'] == 'episode':
            return self.get_episode_data(slug, parsed['season'], parsed['episode'])

        # Case 2: Series root URL (/series/[slug])
        if parsed['type'] == 'series':
            try:
                res = self.request.get(f"{self.BASE_API_URL}/series/{slug}", timeout=12)
                if res.status_code == 200:
                    data = res.json()
                    self.series_data = data
                    self.series_slug = slug
                    title = data.get('title') or slug.replace('-', ' ').title()
                    poster_path = data.get('posterPath') or data.get('backdropPath') or ''
                    if poster_path and not poster_path.startswith('http'):
                        self.poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                    else:
                        self.poster = poster_path

                    return {
                        'status': True,
                        'is_series': True,
                        'media_type': 'series',
                        'slug': slug,
                        'series_title': title,
                        'poster': self.poster,
                        'seasons': data.get('seasons', [])
                    }
                return {'status': False, 'message': f'Series not found on server (status {res.status_code})'}
            except Exception as e:
                return {'status': False, 'message': str(e)}

        # Case 3: Movie or fallback slug
        try:
            res = self.request.get(f"{self.BASE_API_URL}/movies/{slug}", timeout=12)
            if res.status_code == 200:
                data = res.json()
                self.media_type = 'movie'
                self.video_id = data.get('id')
                title = data.get('title') or slug.replace('-', ' ').title()
                year = data.get('releaseYear')
                if year and str(year) not in title:
                    title = f"{title} ({year})"
                # Sanitize filename
                self.video_name = re.sub(r'[\\/*?:"<>|]', '', title).strip()

                poster_path = data.get('posterPath') or data.get('backdropPath') or ''
                if poster_path and not poster_path.startswith('http'):
                    self.poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                else:
                    self.poster = poster_path

                return {
                    'status': True,
                    'video_id': self.video_id,
                    'video_name': self.video_name,
                    'poster': self.poster,
                    'media_type': 'movie'
                }
            else:
                # If /movies/ returned 404, check if it's a series slug
                res_series = self.request.get(f"{self.BASE_API_URL}/series/{slug}", timeout=12)
                if res_series.status_code == 200:
                    data = res_series.json()
                    self.series_data = data
                    self.series_slug = slug
                    title = data.get('title') or slug.replace('-', ' ').title()
                    poster_path = data.get('posterPath') or data.get('backdropPath') or ''
                    if poster_path and not poster_path.startswith('http'):
                        self.poster = f"https://image.tmdb.org/t/p/w500{poster_path}"
                    else:
                        self.poster = poster_path

                    return {
                        'status': True,
                        'is_series': True,
                        'media_type': 'series',
                        'slug': slug,
                        'series_title': title,
                        'poster': self.poster,
                        'seasons': data.get('seasons', [])
                    }

                return {
                    'status': False,
                    'message': f'Media not found on server (status {res.status_code})'
                }
        except Exception as error_video_data:
            return {'status': False, 'message': str(error_video_data)}

    def get_embed_url(self):
        """Unlocks and claims the streaming session from Pentos / MajorPlay API"""
        if not self.video_id:
            return {'status': False, 'message': 'Video ID is required'}

        try:
            # 1. Get play-info and gate token
            watch_type = "episode" if self.media_type == "episode" else "movie"
            res = self.request.get(
                f"{self.BASE_API_URL}/watch/play-info/{watch_type}/{self.video_id}",
                timeout=12
            )
            if res.status_code != 200:
                return {'status': False, 'message': f'Failed to get play info: {res.status_code}'}

            play_info = res.json()
            gate_token = play_info.get("gateToken")
            if not gate_token:
                return {'status': False, 'message': 'Gate token not found in play info'}

            # 2. Wait for unlock countdown gate
            server_now = play_info.get("serverNow", int(time.time() * 1000))
            unlock_at = play_info.get("unlockAt", server_now + 7000)
            wait_sec = max(0.5, (unlock_at - server_now) / 1000.0) + 1.0

            logger.info(f"Unlocking stream gate, waiting ~{int(wait_sec)}s...")
            time.sleep(wait_sec)

            # 3. Claim session
            claim_data = None
            for _ in range(6):
                claim_res = self.request.post(
                    f"{self.BASE_API_URL}/watch/session/claim",
                    json={"gateToken": gate_token},
                    timeout=12
                )
                if claim_res.status_code == 200:
                    c_json = claim_res.json()
                    if c_json.get("kind") == "pentos":
                        claim_data = c_json
                        break
                time.sleep(1.5)

            if not claim_data:
                return {'status': False, 'message': 'Playback session unlock failed (timeout)'}

            redeem_url = claim_data.get("redeemUrl")
            if not redeem_url:
                return {'status': False, 'message': 'Redeem URL not provided'}

            # 4. Redeem stream URL
            redeem_res = self.request.post(
                redeem_url,
                headers={"Origin": "https://z2.idlixku.com", "Referer": "https://z2.idlixku.com/"},
                json={"claim": claim_data["claim"], "mode": "browser"},
                timeout=12
            )
            if redeem_res.status_code != 200:
                return {'status': False, 'message': f'Failed to redeem stream: {redeem_res.status_code}'}

            stream_data = redeem_res.json()
            self.m3u8_url = stream_data.get("url")
            self.subtitles_list = stream_data.get("subtitles", [])
            self.embed_url = redeem_url

            return {
                'status': True,
                'embed_url': self.embed_url
            }

        except Exception as error_get_embed:
            return {'status': False, 'message': str(error_get_embed)}

    def get_m3u8_url(self):
        """Fetches and parses the master playlist to discover available quality variants"""
        if not self.m3u8_url:
            return {'status': False, 'message': 'M3U8 URL is required'}

        try:
            res = self.request.get(
                self.m3u8_url,
                headers={"Origin": "https://z2.idlixku.com", "Referer": "https://z2.idlixku.com/"},
                timeout=12
            )
            if res.status_code != 200:
                return {'status': False, 'message': f'Failed to fetch master playlist ({res.status_code})'}

            self.variant_playlist = m3u8.loads(res.text)
            tmp_variant_playlist = []
            query_str = urlparse(self.m3u8_url).query

            # Parse custom NAME="..." attributes from #EXT-X-STREAM-INF lines
            name_map = {}
            current_name = None
            for line in res.text.splitlines():
                if line.startswith('#EXT-X-STREAM-INF'):
                    m = re.search(r'NAME="([^"]+)"', line)
                    current_name = m.group(1) if m else None
                elif line and not line.startswith('#') and current_name:
                    name_map[line.strip()] = current_name
                    current_name = None

            for idx, playlist in enumerate(self.variant_playlist.playlists):
                v_url = urljoin(self.m3u8_url, playlist.uri)
                if query_str and "?" not in v_url:
                    v_url += "?" + query_str

                res_label = name_map.get(playlist.uri)
                if not res_label:
                    if playlist.stream_info.resolution:
                        res_label = f"{playlist.stream_info.resolution[0]}x{playlist.stream_info.resolution[1]}"
                    else:
                        bw = getattr(playlist.stream_info, 'bandwidth', 0) or 0
                        res_label = f"{round(bw / 1000)}k"

                tmp_variant_playlist.append({
                    'id': str(idx),
                    'resolution': res_label,
                    'uri': v_url,
                    'bandwidth': getattr(playlist.stream_info, 'bandwidth', 0) or 0
                })

            # Sort by bandwidth descending (highest quality first)
            tmp_variant_playlist.sort(key=lambda x: x['bandwidth'], reverse=True)
            for idx, v in enumerate(tmp_variant_playlist):
                v['id'] = str(idx)

            if tmp_variant_playlist:
                self.m3u8_url = tmp_variant_playlist[0]['uri']

            is_variant_playlist = len(tmp_variant_playlist) > 1
            return {
                'status': True,
                'm3u8_url': self.m3u8_url,
                'variant_playlist': tmp_variant_playlist,
                'is_variant_playlist': is_variant_playlist
            }

        except Exception as error_m3u8:
            return {'status': False, 'message': str(error_m3u8)}

    def set_m3u8_url(self, m3u8_url: str):
        self.m3u8_url = m3u8_url

    @staticmethod
    def get_iso_lang(lang: str) -> str:
        """Map language code to ISO 639-2 3-letter code for FFmpeg metadata"""
        lang = (lang or "").lower().strip()
        mapping = {
            "id": "ind", "ind": "ind", "in": "ind", "indonesia": "ind", "indonesian": "ind",
            "en": "eng", "eng": "eng", "english": "eng",
            "ja": "jpn", "jpn": "jpn", "japanese": "jpn",
            "ko": "kor", "kor": "kor", "korean": "kor",
            "zh": "zho", "chi": "zho", "chinese": "zho",
            "es": "spa", "spa": "spa", "spanish": "spa",
            "fr": "fra", "fre": "fra", "french": "fra",
            "de": "deu", "ger": "deu", "german": "deu",
            "ar": "ara", "ara": "ara", "arabic": "ara",
            "th": "tha", "tha": "tha", "thai": "tha",
            "vi": "vie", "vie": "vie", "vietnamese": "vie",
            "ru": "rus", "rus": "rus", "russian": "rus",
        }
        return mapping.get(lang, lang[:3] if len(lang) >= 3 else "und")

    @staticmethod
    def get_lang_label(lang: str, fallback_label: str = None) -> str:
        """Get friendly title label for subtitle track"""
        if fallback_label and fallback_label.strip():
            return fallback_label.strip()
        labels = {
            "id": "Indonesian", "ind": "Indonesian", "in": "Indonesian",
            "en": "English", "eng": "English",
            "ja": "Japanese", "jpn": "Japanese",
            "ko": "Korean", "kor": "Korean",
            "zh": "Chinese", "zho": "Chinese",
            "es": "Spanish", "spa": "Spanish",
            "fr": "French", "fra": "French",
            "de": "German", "deu": "German",
        }
        return labels.get((lang or "").lower().strip(), (lang or "Subtitle").capitalize())

    @staticmethod
    def parse_time_to_seconds(ts_str: str) -> float:
        """Parse HH:MM:SS.mmm or MM:SS.mmm into total seconds"""
        ts_str = ts_str.strip().replace(',', '.')
        parts = ts_str.split(':')
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        return float(parts[0])

    @staticmethod
    def format_seconds_to_srt_time(seconds: float) -> str:
        """Format total seconds into standard SRT timestamp HH:MM:SS,mmm"""
        seconds = max(0.0, seconds)
        total_ms = int(round(seconds * 1000))
        ms = total_ms % 1000
        total_s = total_ms // 1000
        s = total_s % 60
        total_m = total_s // 60
        m = total_m % 60
        h = total_m // 60
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def clean_mojibake(text: str) -> str:
        """Clean common UTF-8 mojibake patterns in subtitle text"""
        replacements = {
            'â€¦': '…',
            'â€œ': '“',
            'â€\x9d': '”',
            'â€': '”',
            'â€˜': '‘',
            'â€™': '’',
            'â€”': '—',
            'â€“': '–',
            'Ã©': 'é',
            'Ã¨': 'è',
            'Ã ': 'à',
            'Ã¡': 'á',
            'Ã³': 'ó',
            'Ã±': 'ñ',
            'Ã§': 'ç',
            'â€¢': '•',
        }
        for bad, good in replacements.items():
            text = text.replace(bad, good)
        return text

    @staticmethod
    def shift_srt_file(srt_path: str, offset_seconds: float, output_path: str = None) -> str:
        """Adjusts all timestamps in an existing SRT file by offset_seconds"""
        target_path = output_path or srt_path
        with open(srt_path, 'r', encoding='utf-8', errors='ignore') as sf:
            content = sf.read()

        ts_pattern = re.compile(
            r'(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})'
        )

        def shift_cue(match):
            t_start = IdlixHelper.parse_time_to_seconds(match.group(1))
            t_end = IdlixHelper.parse_time_to_seconds(match.group(2))
            s_start = max(0.0, t_start + offset_seconds)
            s_end = max(s_start + 0.1, t_end + offset_seconds)
            return f"{IdlixHelper.format_seconds_to_srt_time(s_start)} --> {IdlixHelper.format_seconds_to_srt_time(s_end)}"

        shifted_content = ts_pattern.sub(shift_cue, content)
        shifted_content = IdlixHelper.clean_mojibake(shifted_content)

        with open(target_path, 'w', encoding='utf-8') as out_f:
            out_f.write(shifted_content)

        return target_path

    @staticmethod
    def convert_vtt_to_srt(vtt_file: str, target_srt: str = None, time_offset_seconds: float = 0.0) -> str:
        """Converts WebVTT file to standard compliant SRT format with optional time sync offset and mojibake cleaning"""
        output_srt = target_srt or (vtt_file.rsplit('.', 1)[0] + '.srt')
        try:
            with open(vtt_file, 'r', encoding='utf-8', errors='ignore') as vf:
                vtt_text = vf.read()

            # 1. Normalize line endings, strip BOM, and clean mojibake
            text = vtt_text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
            text = IdlixHelper.clean_mojibake(text)

            # 2. Strip WEBVTT header and comments/metadata before the first cue
            lines = text.split('\n')
            cue_lines = []
            in_header = True
            for line in lines:
                stripped = line.strip()
                if in_header:
                    if re.match(r'^(WEBVTT|NOTE|STYLE|REGION|Kind:|Language:)', stripped, re.IGNORECASE):
                        continue
                    if '-->' in stripped:
                        in_header = False
                        cue_lines.append(line)
                    continue
                cue_lines.append(line)

            content = '\n'.join(cue_lines)

            # 3. Standardize and shift timestamps to HH:MM:SS,mmm --> HH:MM:SS,mmm
            def shift_and_format_ts(match):
                raw_start = match.group(1)
                raw_end = match.group(2)
                t_start = IdlixHelper.parse_time_to_seconds(raw_start)
                t_end = IdlixHelper.parse_time_to_seconds(raw_end)
                s_start = max(0.0, t_start + time_offset_seconds)
                s_end = max(s_start + 0.1, t_end + time_offset_seconds)
                return f"{IdlixHelper.format_seconds_to_srt_time(s_start)} --> {IdlixHelper.format_seconds_to_srt_time(s_end)}"

            ts_pattern = re.compile(
                r'((?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})\s*-->\s*((?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})'
            )
            content = ts_pattern.sub(shift_and_format_ts, content)

            # 4. Split blocks and ensure strictly valid numbered cues
            blocks = re.split(r'\n\s*\n', content.strip())
            cues = []
            cue_num = 1
            for block in blocks:
                blines = [l.strip() for l in block.split('\n') if l.strip()]
                if not blines:
                    continue
                ts_idx = -1
                for idx, l in enumerate(blines):
                    if '-->' in l and re.search(r'\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}', l):
                        ts_idx = idx
                        break
                if ts_idx == -1:
                    continue

                ts_match = re.search(r'\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}', blines[ts_idx])
                ts_line = ts_match.group(0)
                text_lines = blines[ts_idx + 1:]
                if not text_lines:
                    continue

                cues.append(f"{cue_num}\n{ts_line}\n" + "\n".join(text_lines))
                cue_num += 1

            final_srt = "\n\n".join(cues) + "\n"
            with open(output_srt, 'w', encoding='utf-8') as sf:
                sf.write(final_srt)

            return output_srt
        except Exception as err:
            logger.error(f"Failed converting VTT to SRT: {err}")
            return None

    def get_subtitles(self, download=True, output_dir=None, time_offset: float = 0.0):
        """
        Downloads all available subtitles, converts to SRT with optional time sync offset,
        and saves them alongside the movie file.
        """
        if not self.subtitles_list:
            self.is_subtitle = False
            return []

        out_dir = output_dir or os.getcwd()
        os.makedirs(out_dir, exist_ok=True)
        clean_name = self.video_name.strip()

        downloaded = []

        for idx, sub_entry in enumerate(self.subtitles_list):
            sub_url = sub_entry.get("path")
            if not sub_url:
                continue

            lang_raw = sub_entry.get("lang") or sub_entry.get("language") or f"sub{idx+1}"
            iso_lang = self.get_iso_lang(lang_raw)
            label = self.get_lang_label(lang_raw, sub_entry.get("label"))

            if not download:
                downloaded.append({
                    "lang": lang_raw,
                    "iso_lang": iso_lang,
                    "label": label,
                    "url": sub_url,
                    "srt_path": None
                })
                continue

            try:
                sub_res = None
                try:
                    sub_res = self.request.get(
                        sub_url,
                        headers={"Referer": "https://z2.idlixku.com/", "Origin": "https://z2.idlixku.com"},
                        timeout=12
                    )
                except Exception:
                    pass

                if not sub_res or sub_res.status_code != 200 or not sub_res.content:
                    sub_res = requests.get(
                        sub_url,
                        headers={"Referer": "https://z2.idlixku.com/", "Origin": "https://z2.idlixku.com"},
                        timeout=12
                    )

                if not sub_res or sub_res.status_code != 200 or not sub_res.content:
                    logger.warning(f"Failed downloading subtitle from {sub_url}")
                    continue

                temp_vtt = os.path.join(out_dir, f"{clean_name}.{iso_lang}.tmp_{int(time.time())}_{idx}.vtt")
                with open(temp_vtt, "wb") as vf:
                    vf.write(sub_res.content)

                canonical_srt = os.path.join(out_dir, f"{clean_name}.{iso_lang}.srt")
                res_srt = self.convert_vtt_to_srt(temp_vtt, canonical_srt, time_offset_seconds=time_offset)

                if os.path.exists(temp_vtt):
                    try:
                        os.remove(temp_vtt)
                    except Exception:
                        pass

                if res_srt and os.path.exists(canonical_srt):
                    default_srt = os.path.join(out_dir, f"{clean_name}.srt")
                    if iso_lang == "ind" or not os.path.exists(default_srt):
                        try:
                            shutil.copyfile(canonical_srt, default_srt)
                        except Exception:
                            pass

                    downloaded.append({
                        "lang": lang_raw,
                        "iso_lang": iso_lang,
                        "label": label,
                        "url": sub_url,
                        "srt_path": canonical_srt
                    })
                    offset_msg = f" (sync offset: {time_offset:+.2f}s)" if time_offset != 0.0 else ""
                    logger.info(f"Subtitle ready [{label}]{offset_msg}: {os.path.basename(canonical_srt)}")

            except Exception as e:
                logger.warning(f"Error processing subtitle {lang_raw}: {e}")
                continue

        if downloaded:
            self.is_subtitle = True
        return downloaded

    def get_subtitle(self, download=True, time_offset: float = 0.0):
        """Downloads primary subtitle (preferring Indonesian) with optional time sync offset"""
        subs = self.get_subtitles(download=download, time_offset=time_offset)
        if not subs:
            self.is_subtitle = False
            return {'status': False, 'message': 'Subtitle not available'}

        primary = next((s for s in subs if s.get('iso_lang') == 'ind'), subs[0])
        self.is_subtitle = True
        return {
            'status': True,
            'subtitle': primary['srt_path'] if download else primary.get('url'),
            'subtitles': subs
        }

    def download_m3u8(self, output_dir=None, time_offset: float = 0.0):
        """Downloads all HLS segments multithreaded (supporting fMP4, separate audio tracks, and TS) and stitches into MP4 with subtitles using FFmpeg"""
        try:
            if not self.m3u8_url:
                return {'status': False, 'message': 'M3U8 URL is required'}

            # 1. Fetch variant playlist to extract video segment & init URLs
            variant_res = self.request.get(
                self.m3u8_url,
                headers={"Origin": "https://z2.idlixku.com", "Referer": "https://z2.idlixku.com/"},
                timeout=12
            )
            if variant_res.status_code != 200:
                return {'status': False, 'message': f'Failed to fetch stream playlist: {variant_res.status_code}'}

            lines = variant_res.text.strip().splitlines()
            query_str = urlparse(self.m3u8_url).query
            video_init_url = None
            video_seg_urls = []

            for line in lines:
                line = line.strip()
                if line.startswith('#EXT-X-MAP:URI='):
                    m_init = re.search(r'URI="([^"]+)"', line)
                    if m_init:
                        video_init_url = urljoin(self.m3u8_url, m_init.group(1))
                        if query_str and "?" not in video_init_url:
                            video_init_url += "?" + query_str
                elif line and not line.startswith('#'):
                    seg_url = urljoin(self.m3u8_url, line)
                    if query_str and "?" not in seg_url:
                        seg_url += "?" + query_str
                    video_seg_urls.append(seg_url)

            if not video_seg_urls:
                return {'status': False, 'message': 'No video segments found in playlist'}

            # 2. Check for separate audio track in master playlist
            audio_init_url = None
            audio_seg_urls = []
            if self.variant_playlist and getattr(self.variant_playlist, 'media', None):
                for m_elem in self.variant_playlist.media:
                    if getattr(m_elem, 'type', '').upper() == "AUDIO" and getattr(m_elem, 'uri', None):
                        a_playlist_url = urljoin(self.m3u8_url, m_elem.uri)
                        if query_str and "?" not in a_playlist_url:
                            a_playlist_url += "?" + query_str
                        try:
                            a_res = self.request.get(
                                a_playlist_url,
                                headers={"Origin": "https://z2.idlixku.com", "Referer": "https://z2.idlixku.com/"},
                                timeout=12
                            )
                            if a_res.status_code == 200:
                                for a_line in a_res.text.strip().splitlines():
                                    a_line = a_line.strip()
                                    if a_line.startswith('#EXT-X-MAP:URI='):
                                        m_ainit = re.search(r'URI="([^"]+)"', a_line)
                                        if m_ainit:
                                            audio_init_url = urljoin(a_playlist_url, m_ainit.group(1))
                                            if query_str and "?" not in audio_init_url:
                                                audio_init_url += "?" + query_str
                                    elif a_line and not a_line.startswith('#'):
                                        a_seg = urljoin(a_playlist_url, a_line)
                                        if query_str and "?" not in a_seg:
                                            a_seg += "?" + query_str
                                        audio_seg_urls.append(a_seg)
                                logger.info(f"Detected separate audio stream ({len(audio_seg_urls)} segments)")
                                break
                        except Exception as e_audio:
                            logger.warning(f"Could not load audio track: {e_audio}")

            total_video_segments = len(video_seg_urls)
            logger.info(f"Found {total_video_segments} video segments to download...")

            # 3. Prepare temporary directory
            tmp_dir = os.path.join(os.getcwd(), f"tmp_{int(time.time())}")
            os.makedirs(tmp_dir, exist_ok=True)

            # 4. Multithreaded segment downloader helper
            def download_chunk(dest_path: str, url: str) -> bool:
                for _ in range(3):
                    try:
                        r = self.request.get(
                            url,
                            headers={"Referer": "https://z2.idlixku.com/", "Origin": "https://z2.idlixku.com"},
                            timeout=15
                        )
                        if r.status_code == 200 and r.content:
                            with open(dest_path, "wb") as f:
                                f.write(r.content)
                            return True
                    except Exception:
                        pass
                    time.sleep(1)
                return False

            # Download video init if present
            v_init_path = os.path.join(tmp_dir, "v_init.mp4") if video_init_url else None
            if video_init_url:
                if not download_chunk(v_init_path, video_init_url):
                    logger.warning("Failed to download video init segment")

            # Download video segments
            v_paths = [os.path.join(tmp_dir, f"v_seg_{i:05d}.dat") for i in range(total_video_segments)]
            completed_v = 0
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(download_chunk, v_paths[i], url): i
                    for i, url in enumerate(video_seg_urls)
                }
                for f in as_completed(futures):
                    if f.result():
                        completed_v += 1
                        if completed_v % 25 == 0 or completed_v == total_video_segments:
                            pct = int((completed_v / total_video_segments) * 100)
                            logger.info(f"Downloading video chunks: {completed_v}/{total_video_segments} ({pct}%)")
                    else:
                        logger.warning(f"Failed video chunk {futures[f]}, continuing...")

            # Download audio stream if separate
            a_init_path = None
            a_paths = []
            has_separate_audio = bool(audio_seg_urls)
            if has_separate_audio:
                total_audio_segments = len(audio_seg_urls)
                if audio_init_url:
                    a_init_path = os.path.join(tmp_dir, "a_init.mp4")
                    download_chunk(a_init_path, audio_init_url)

                a_paths = [os.path.join(tmp_dir, f"a_seg_{i:05d}.dat") for i in range(total_audio_segments)]
                completed_a = 0
                logger.info(f"Downloading {total_audio_segments} audio segments...")
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures_a = {
                        executor.submit(download_chunk, a_paths[i], url): i
                        for i, url in enumerate(audio_seg_urls)
                    }
                    for f in as_completed(futures_a):
                        if f.result():
                            completed_a += 1
                            if completed_a % 50 == 0 or completed_a == total_audio_segments:
                                pct = int((completed_a / total_audio_segments) * 100)
                                logger.info(f"Downloading audio chunks: {completed_a}/{total_audio_segments} ({pct}%)")

            # 5. Assemble raw streams
            raw_video_path = os.path.join(tmp_dir, "raw_video.mp4" if video_init_url else "raw_video.ts")
            with open(raw_video_path, "wb") as out_vf:
                if v_init_path and os.path.exists(v_init_path):
                    with open(v_init_path, "rb") as inf:
                        out_vf.write(inf.read())
                for vp in v_paths:
                    if os.path.exists(vp):
                        with open(vp, "rb") as inf:
                            out_vf.write(inf.read())

            raw_audio_path = None
            if has_separate_audio:
                raw_audio_path = os.path.join(tmp_dir, "raw_audio.m4a" if audio_init_url else "raw_audio.ts")
                with open(raw_audio_path, "wb") as out_af:
                    if a_init_path and os.path.exists(a_init_path):
                        with open(a_init_path, "rb") as inf:
                            out_af.write(inf.read())
                    for ap in a_paths:
                        if os.path.exists(ap):
                            with open(ap, "rb") as inf:
                                out_af.write(inf.read())

            # 6. Handle Subtitles (sidecar and embedded)
            out_dir = output_dir or os.getcwd()
            os.makedirs(out_dir, exist_ok=True)
            output_filename = f"{self.video_name}.mp4"
            output_path = os.path.join(out_dir, output_filename)

            logger.info("Checking and preparing subtitles...")
            subs = self.get_subtitles(download=True, output_dir=out_dir, time_offset=time_offset)

            # 7. FFmpeg concat and mux to MP4
            logger.info(f"Merging streams into {output_filename} via FFmpeg...")

            mux_success = False
            # Base command
            cmd = ["ffmpeg", "-y", "-i", raw_video_path]
            if raw_audio_path and os.path.exists(raw_audio_path):
                cmd += ["-i", raw_audio_path]

            sub_input_offset = 2 if (raw_audio_path and os.path.exists(raw_audio_path)) else 1

            if subs:
                for sub in subs:
                    cmd += ["-i", sub["srt_path"]]

                cmd += ["-map", "0:v"]
                if raw_audio_path and os.path.exists(raw_audio_path):
                    cmd += ["-map", "1:a"]
                else:
                    cmd += ["-map", "0:a?"]

                for i in range(len(subs)):
                    cmd += ["-map", f"{sub_input_offset + i}:0"]

                cmd += ["-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-movflags", "+faststart"]

                for i, sub in enumerate(subs):
                    cmd += [
                        f"-metadata:s:s:{i}", f"language={sub['iso_lang']}",
                        f"-metadata:s:s:{i}", f"title={sub['label']}"
                    ]
                cmd.append(output_path)

                res_mux = subprocess.run(cmd, capture_output=True, text=True)
                if res_mux.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                    mux_success = True
                    logger.success(f"Successfully embedded {len(subs)} subtitle track(s) into {output_filename}")
                else:
                    err_msg = res_mux.stderr.strip().splitlines()[-1] if (res_mux.stderr and res_mux.stderr.strip()) else "Code " + str(res_mux.returncode)
                    logger.warning(f"FFmpeg subtitle muxing failed ({err_msg}), falling back to clean video/audio copy...")

            if not mux_success:
                cmd_fallback = ["ffmpeg", "-y", "-i", raw_video_path]
                if raw_audio_path and os.path.exists(raw_audio_path):
                    cmd_fallback += ["-i", raw_audio_path, "-map", "0:v", "-map", "1:a", "-c", "copy"]
                else:
                    cmd_fallback += ["-c", "copy"]
                cmd_fallback += ["-movflags", "+faststart", output_path]
                res_fallback = subprocess.run(cmd_fallback, capture_output=True, text=True)
                if res_fallback.returncode != 0:
                    err_msg = res_fallback.stderr.strip().splitlines()[-1] if (res_fallback.stderr and res_fallback.stderr.strip()) else "Code " + str(res_fallback.returncode)
                    logger.error(f"FFmpeg copy error: {err_msg}")

            shutil.rmtree(tmp_dir, ignore_errors=True)

            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                file_size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
                logger.success(f"Download complete: {output_filename} ({file_size_mb} MB)")
                return {
                    'status': True,
                    'message': 'Download success',
                    'path': output_path,
                    'subtitles': subs,
                    'subtitles_muxed': mux_success
                }
            else:
                return {
                    'status': False,
                    'message': 'FFmpeg merging failed to produce valid MP4'
                }

        except Exception as error_download:
            return {'status': False, 'message': str(error_download)}

    def play_m3u8(self):
        """Streams directly with FFplay using proper headers and demuxer options"""
        try:
            if not self.m3u8_url:
                return {'status': False, 'message': 'M3U8 URL is required'}

            args = [
                "ffplay",
                "-allowed_segment_extensions", "ALL",
                "-extension_picky", "0",
                "-headers", "Referer: https://z2.idlixku.com/\r\nOrigin: https://z2.idlixku.com\r\n",
                "-i", self.m3u8_url,
                "-window_title", self.video_name,
                "-hide_banner",
                "-loglevel", "panic"
            ]

            sub_info = self.get_subtitle(download=True)
            subtitle_path = sub_info.get("subtitle") if sub_info.get("status") else None

            if subtitle_path and os.path.exists(subtitle_path):
                args += ["-vf", f"subtitles={subtitle_path}"]

            subprocess.call(args)

            return {'status': True, 'message': 'Playback finished'}
        except Exception as error_play:
            return {'status': False, 'message': str(error_play)}
