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
    def extract_slug(url: str) -> str:
        clean = url.strip().rstrip('/')
        if '/movie/' in clean:
            return clean.split('/movie/')[-1].split('?')[0].split('/')[0]
        elif '/series/' in clean:
            return clean.split('/series/')[-1].split('?')[0].split('/')[0]
        elif clean.startswith('http'):
            path = urlparse(clean).path.strip('/').split('/')
            return path[-1] if path else clean
        return clean

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

    def get_video_data(self, url: str):
        """Fetch movie details and internal ID from URL or slug"""
        if not url:
            return {'status': False, 'message': 'URL is required'}

        slug = self.extract_slug(url)
        if not slug:
            return {'status': False, 'message': 'Invalid movie URL or slug'}

        self.movie_slug = slug

        try:
            res = self.request.get(f"{self.BASE_API_URL}/movies/{slug}", timeout=12)
            if res.status_code == 200:
                data = res.json()
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
                    'poster': self.poster
                }
            else:
                return {
                    'status': False,
                    'message': f'Movie not found on server (status {res.status_code})'
                }
        except Exception as error_video_data:
            return {'status': False, 'message': str(error_video_data)}

    def get_embed_url(self):
        """Unlocks and claims the streaming session from Pentos / MajorPlay API"""
        if not self.video_id:
            return {'status': False, 'message': 'Video ID is required'}

        try:
            # 1. Get play-info and gate token
            res = self.request.get(
                f"{self.BASE_API_URL}/watch/play-info/movie/{self.video_id}",
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

    def get_subtitle(self, download=True):
        """Downloads and converts WebVTT subtitle to SRT"""
        try:
            if not self.subtitles_list:
                self.is_subtitle = False
                return {'status': False, 'message': 'Subtitle not available'}

            # Prefer Indonesian, fallback to first available
            sub_entry = next(
                (s for s in self.subtitles_list if s.get('lang') in ['id', 'ind']),
                self.subtitles_list[0]
            )
            sub_url = sub_entry.get('path')
            if not sub_url:
                self.is_subtitle = False
                return {'status': False, 'message': 'Subtitle URL missing'}

            if download:
                sub_res = requests.get(
                    sub_url,
                    headers={"Referer": "https://z2.idlixku.com/", "Origin": "https://z2.idlixku.com"},
                    timeout=10
                )
                base_name = re.sub(r'\s+', '_', self.video_name)
                vtt_path = f"{base_name}.vtt"
                with open(vtt_path, 'wb') as sf:
                    sf.write(sub_res.content)

                self.convert_vtt_to_srt(vtt_path)
                self.is_subtitle = True
                srt_path = f"{base_name}.srt"
                return {
                    'status': True,
                    'subtitle': srt_path
                }

            self.is_subtitle = True
            return {
                'status': True,
                'subtitle': sub_url
            }

        except Exception as error_subtitle:
            self.is_subtitle = False
            return {'status': False, 'message': str(error_subtitle)}

    def download_m3u8(self):
        """Downloads all HLS segments multithreaded and stitches into MP4 using FFmpeg"""
        try:
            if not self.m3u8_url:
                return {'status': False, 'message': 'M3U8 URL is required'}

            # 1. Fetch variant playlist to extract segment URLs
            variant_res = self.request.get(
                self.m3u8_url,
                headers={"Origin": "https://z2.idlixku.com", "Referer": "https://z2.idlixku.com/"},
                timeout=12
            )
            if variant_res.status_code != 200:
                return {'status': False, 'message': f'Failed to fetch stream playlist: {variant_res.status_code}'}

            lines = variant_res.text.strip().splitlines()
            query_str = urlparse(self.m3u8_url).query
            segment_urls = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    seg_url = urljoin(self.m3u8_url, line)
                    if query_str and "?" not in seg_url:
                        seg_url += "?" + query_str
                    segment_urls.append(seg_url)

            if not segment_urls:
                return {'status': False, 'message': 'No video segments found in playlist'}

            total_segments = len(segment_urls)
            logger.info(f"Found {total_segments} video segments to download...")

            # 2. Prepare temporary directory
            tmp_dir = os.path.join(os.getcwd(), f"tmp_{int(time.time())}")
            os.makedirs(tmp_dir, exist_ok=True)

            # 3. Concurrent multithreaded download
            completed_count = 0

            def download_segment(idx: int, url: str) -> bool:
                seg_path = os.path.join(tmp_dir, f"seg_{idx:05d}.ts")
                for _ in range(3):
                    try:
                        r = self.request.get(
                            url,
                            headers={"Referer": "https://z2.idlixku.com/", "Origin": "https://z2.idlixku.com"},
                            timeout=15
                        )
                        if r.status_code == 200:
                            with open(seg_path, "wb") as f:
                                f.write(r.content)
                            return True
                    except Exception:
                        pass
                    time.sleep(1)
                return False

            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(download_segment, i, url): i
                    for i, url in enumerate(segment_urls)
                }
                for f in as_completed(futures):
                    if f.result():
                        completed_count += 1
                        if completed_count % 25 == 0 or completed_count == total_segments:
                            pct = int((completed_count / total_segments) * 100)
                            logger.info(f"Downloading chunks: {completed_count}/{total_segments} ({pct}%)")
                    else:
                        logger.warning(f"Failed chunk {futures[f]}, will continue...")

            # 4. Create concat manifest for FFmpeg
            manifest_path = os.path.join(tmp_dir, "list.txt")
            with open(manifest_path, "w") as mf:
                for i in range(total_segments):
                    seg_name = f"seg_{i:05d}.ts"
                    if os.path.exists(os.path.join(tmp_dir, seg_name)):
                        mf.write(f"file '{seg_name}'\n")

            # 5. FFmpeg concat to MP4
            output_filename = f"{self.video_name}.mp4"
            output_path = os.path.join(os.getcwd(), output_filename)
            logger.info(f"Merging segments into {output_filename} via FFmpeg...")

            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", manifest_path,
                "-c", "copy",
                output_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.rmtree(tmp_dir, ignore_errors=True)

            if result.returncode == 0 and os.path.exists(output_path):
                file_size_mb = round(os.path.getsize(output_path) / (1024 * 1024), 2)
                logger.success(f"Download complete: {output_filename} ({file_size_mb} MB)")
                return {
                    'status': True,
                    'message': 'Download success',
                    'path': output_path
                }
            else:
                return {
                    'status': False,
                    'message': f'FFmpeg concatenation failed (code {result.returncode})'
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

            subtitle_path = f"{self.video_name.replace(' ', '_')}.srt"
            if self.is_subtitle and os.path.exists(subtitle_path):
                args += ["-vf", f"subtitles={subtitle_path}"]

            subprocess.call(args)

            if self.is_subtitle:
                if os.path.exists(subtitle_path):
                    os.remove(subtitle_path)
                vtt_path = f"{self.video_name.replace(' ', '_')}.vtt"
                if os.path.exists(vtt_path):
                    os.remove(vtt_path)

            return {'status': True, 'message': 'Playback finished'}
        except Exception as error_play:
            return {'status': False, 'message': str(error_play)}

    @staticmethod
    def convert_vtt_to_srt(vtt_file):
        convert_file = ConvertFile(vtt_file, "utf-8")
        convert_file.convert()
