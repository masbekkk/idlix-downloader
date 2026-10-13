import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import subprocess
import os
import re
import time
import webbrowser
from io import BytesIO

from PIL import Image, ImageTk
import requests
from bs4 import BeautifulSoup

from src.idlixHelper import IdlixHelper, logger

# ============================================================
# RETRY logic (same as CLI)
# ============================================================
RETRY_LIMIT = 3


def retry(func, *args, **kwargs):
    for _ in range(RETRY_LIMIT):
        result = func(*args, **kwargs)
        if result and result.get("status"):
            return result
        time.sleep(1)
    return {"status": False, "message": "Maximum retry reached"}


# ============================================================
# GUI LOGGER
# ============================================================
class GuiLogger:
    def __init__(self, textbox):
        self.textbox = textbox

    def write(self, msg):
        self.textbox.configure(state='normal')
        self.textbox.insert(tk.END, msg)
        self.textbox.see(tk.END)
        self.textbox.configure(state='disabled')

    def flush(self):
        pass


# ============================================================
# MAIN GUI
# ============================================================
class IdlixGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("IDLIX Downloader & Player GUI")
        self.root.geometry("1400x650")

        self.idlix = IdlixHelper()
        self.featured_movies = []
        self.poster_images = []
        self.ffplay_process = None

        # Main container
        main_frame = ttk.Frame(root, padding=10)
        main_frame.pack(fill="both", expand=True)

        # LEFT = poster grid
        left_panel = ttk.Frame(main_frame)
        left_panel.grid(row=0, column=0, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_rowconfigure(0, weight=1)

        ttk.Label(left_panel, text="Featured Movies", font=("Arial", 16, "bold")).pack(anchor="w")

        self.poster_canvas = tk.Canvas(left_panel, bg="#181818")
        scrollbar = ttk.Scrollbar(left_panel, orient="vertical", command=self.poster_canvas.yview)
        self.poster_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.poster_canvas.pack(side="left", fill="both", expand=True)

        self.poster_frame = ttk.Frame(self.poster_canvas)
        self.poster_canvas.create_window((0, 0), window=self.poster_frame, anchor="nw")

        self.poster_canvas.bind(
            "<Configure>",
            lambda e: self.poster_canvas.configure(scrollregion=self.poster_canvas.bbox("all"))
        )

        # RIGHT = controls + log
        right_panel = ttk.Frame(main_frame, padding=(10, 0))
        right_panel.grid(row=0, column=1, sticky="ns")
        right_panel.grid_propagate(False)

        ttk.Label(right_panel, text="Controls", font=("Arial", 16, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Button(right_panel, text="Refresh Featured", command=self.refresh_featured).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Download by URL", command=self.download_by_url).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Play by URL", command=self.play_by_url).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Download Subtitle by URL", command=self.download_subtitle_by_url).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Shift / Sync Subtitle (.srt)", command=self.shift_existing_subtitle).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Stop Player", command=self.stop_player).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Open Downloads Folder", command=self.open_download_folder).pack(fill="x", pady=4)
        ttk.Button(right_panel, text="Clear Log", command=self.clear_log).pack(fill="x", pady=4)

        ttk.Label(right_panel, text="Log Output", font=("Arial", 14, "bold")).pack(anchor="w", pady=(20, 5))

        self.log_box = tk.Text(right_panel, height=28, state='disabled', bg="#111", fg="#0f0")
        self.log_box.pack(fill="both", expand=True)

        # Logger injection
        logger.remove()
        logger.add(GuiLogger(self.log_box), format="{time:HH:mm:ss} | {level} | {message}")

        # Load posters initially
        self.refresh_featured()

    # ============================================================
    # POSTER GRID
    # ============================================================
    def show_poster_grid(self):
        for w in self.poster_frame.winfo_children():
            w.destroy()

        self.poster_images.clear()

        posters_per_row = 4
        size = (150, 210)
        row = col = 0

        for movie in self.featured_movies:
            try:
                img_raw = requests.get(movie["poster"], timeout=8).content
                img = Image.open(BytesIO(img_raw)).resize(size)
                tk_img = ImageTk.PhotoImage(img)
            except:
                continue

            self.poster_images.append(tk_img)

            frame = ttk.Frame(self.poster_frame)
            frame.grid(row=row, column=col, padx=10, pady=10)

            tk.Button(
                frame,
                image=tk_img,
                relief="flat",
                command=lambda m=movie: self.on_poster_click(m)
            ).pack()

            ttk.Label(
                frame,
                text=movie["title"],
                wraplength=150,
                justify="center"
            ).pack()

            col += 1
            if col >= posters_per_row:
                col = 0
                row += 1

    # ============================================================
    # POSTER POPUP MENU
    # ============================================================
    def on_poster_click(self, movie):
        popup = tk.Toplevel(self.root)
        popup.title(movie["title"])
        popup.geometry("350x260")

        ttk.Label(popup, text=movie["title"], font=("Arial", 12, "bold")).pack(pady=10)

        ttk.Button(
            popup,
            text="Play",
            width=22,
            command=lambda: [popup.destroy(), self.process_movie(movie["url"], "play")]
        ).pack(pady=4)

        ttk.Button(
            popup,
            text="Download Video",
            width=22,
            command=lambda: [popup.destroy(), self.process_movie(movie["url"], "download")]
        ).pack(pady=4)

        def on_sub_click():
            popup.destroy()
            offset_str = simpledialog.askstring(
                "Subtitle Sync",
                f"Enter sync offset in seconds for:\n'{movie['title']}':\n\n(e.g. -1.2 to display earlier, 0.0 for original)",
                initialvalue="0.0"
            )
            offset = 0.0
            if offset_str:
                try:
                    offset = float(offset_str)
                except ValueError:
                    offset = 0.0
            self.process_movie(movie["url"], "subtitle", time_offset=offset)

        ttk.Button(
            popup,
            text="Download Subtitles Only",
            width=22,
            command=on_sub_click
        ).pack(pady=4)

        ttk.Button(popup, text="Cancel", width=22, command=popup.destroy).pack(pady=8)

    # Variant selector
    def ask_variant(self, choices):
        popup = tk.Toplevel(self.root)
        popup.title("Select Resolution")
        popup.geometry("320x360")

        ttk.Label(popup, text="Select Video Quality", font=("Arial", 11, "bold")).pack(pady=10)

        listbox = tk.Listbox(popup, width=32, height=12)
        for c in choices:
            listbox.insert(tk.END, c)
        if choices:
            listbox.selection_set(0)
        listbox.pack(padx=10, pady=5)

        result = {"res": choices[0] if choices else None}

        def choose():
            sel = listbox.curselection()
            if sel:
                result["res"] = listbox.get(sel[0])
            popup.destroy()

        ttk.Button(popup, text="OK", command=choose).pack(pady=10)

        popup.grab_set()
        self.root.wait_window(popup)

        return result["res"]

    def ask_selection(self, title: str, prompt: str, choices: list) -> str:
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.geometry("420x180")
        popup.resizable(False, False)

        ttk.Label(popup, text=prompt, font=("Arial", 11, "bold")).pack(pady=10)

        combo = ttk.Combobox(popup, values=choices, state="readonly", width=45)
        combo.current(0)
        combo.pack(pady=10)

        result = {"val": choices[0]}

        def choose():
            result["val"] = combo.get()
            popup.destroy()

        ttk.Button(popup, text="Select", command=choose).pack(pady=8)
        popup.grab_set()
        self.root.wait_window(popup)
        return result["val"]

    def ask_episodes_selection(self, title: str, prompt: str, episodes: list) -> list:
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.geometry("500x480")
        popup.minsize(440, 400)

        ttk.Label(popup, text=prompt, font=("Arial", 11, "bold")).pack(pady=8)

        # Quick action buttons bar
        btn_bar = ttk.Frame(popup)
        btn_bar.pack(fill="x", padx=15, pady=4)

        # Multi-select listbox with scrollbar
        list_frame = ttk.Frame(popup)
        list_frame.pack(fill="both", expand=True, padx=15, pady=5)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, yscrollcommand=scrollbar.set, font=("Arial", 10))
        scrollbar.config(command=listbox.yview)
        scrollbar.pack(side="right", fill="y")
        listbox.pack(side="left", fill="both", expand=True)

        ep_map = {}
        for idx, e in enumerate(episodes):
            ep_num = e.get("episodeNumber", idx + 1)
            ep_name = e.get("name", f"Episode {ep_num}")
            display = f"Ep {ep_num}: {ep_name}"
            listbox.insert(tk.END, display)
            ep_map[idx] = ep_num

        def select_all():
            listbox.select_set(0, tk.END)

        def deselect_all():
            listbox.select_clear(0, tk.END)

        ttk.Button(btn_bar, text="Select All (Whole Season)", command=select_all).pack(side="left", padx=4)
        ttk.Button(btn_bar, text="Clear All", command=deselect_all).pack(side="left", padx=4)

        # Range entry frame
        range_frame = ttk.Frame(popup)
        range_frame.pack(fill="x", padx=15, pady=6)
        ttk.Label(range_frame, text="Or Range (e.g. 1-5, 8):").pack(side="left", padx=4)
        range_entry = ttk.Entry(range_frame, width=18)
        range_entry.pack(side="left", padx=4)

        def apply_range():
            val = range_entry.get().strip()
            if val:
                try:
                    parsed = IdlixHelper.parse_episode_selection(val, episodes)
                    deselect_all()
                    for i, e in enumerate(episodes):
                        if e.get("episodeNumber") in parsed:
                            listbox.select_set(i)
                except Exception as ex:
                    messagebox.showwarning("Invalid Range", str(ex), parent=popup)

        ttk.Button(range_frame, text="Apply Range", command=apply_range).pack(side="left", padx=4)

        result = {"episodes": []}

        def confirm():
            sel_indices = listbox.curselection()
            if not sel_indices:
                messagebox.showwarning("Selection Required", "Please select at least one episode.", parent=popup)
                return
            result["episodes"] = [ep_map[i] for i in sel_indices if i in ep_map]
            popup.destroy()

        def cancel():
            result["episodes"] = []
            popup.destroy()

        bottom_frame = ttk.Frame(popup)
        bottom_frame.pack(fill="x", padx=15, pady=10)
        ttk.Button(bottom_frame, text="Confirm & Proceed", command=confirm).pack(side="right", padx=8)
        ttk.Button(bottom_frame, text="Cancel", command=cancel).pack(side="right", padx=4)

        # Pre-select all by default for convenient 1-click Whole Season download
        select_all()

        popup.grab_set()
        self.root.wait_window(popup)
        return result["episodes"]

    # ============================================================
    # REFRESH FEATURED LIST
    # ============================================================
    def refresh_featured(self):
        def task():
            logger.info("Loading featured movies...")
            home = retry(self.idlix.get_home)

            if not home.get("status"):
                logger.error(f"Failed: {home.get('message')}")
                return

            self.featured_movies = home["featured_movie"]
            self.root.after(0, self.show_poster_grid)

            logger.success("Featured loaded.")

        threading.Thread(target=task, daemon=True).start()

    # ============================================================
    # URL BUTTON ACTIONS
    # ============================================================
    def download_by_url(self):
        url = simpledialog.askstring("Download Media", "Enter Movie or Series Episode URL:")
        if url:
            self.process_movie(url.strip(), "download")

    def play_by_url(self):
        url = simpledialog.askstring("Play Media", "Enter Movie or Series Episode URL:")
        if url:
            self.process_movie(url.strip(), "play")

    def download_subtitle_by_url(self):
        url = simpledialog.askstring("Download Subtitles", "Enter Movie or Series Episode URL:")
        if url:
            offset_str = simpledialog.askstring(
                "Subtitle Sync",
                "Enter subtitle sync offset in seconds:\n(e.g. -1.2 to display earlier, 0.0 for original):",
                initialvalue="0.0"
            )
            offset = 0.0
            if offset_str:
                try:
                    offset = float(offset_str)
                except ValueError:
                    offset = 0.0
            self.process_movie(url.strip(), "subtitle", time_offset=offset)

    def shift_existing_subtitle(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="Select SRT Subtitle File to Shift",
            filetypes=[("SRT Subtitles", "*.srt"), ("All Files", "*.*")]
        )
        if not path:
            return
        offset_str = simpledialog.askstring(
            "Shift Subtitle",
            f"Enter offset in seconds for:\n{os.path.basename(path)}\n\n(e.g. -1.2 to display earlier, +1.5 to delay):",
            initialvalue="-1.2"
        )
        if offset_str:
            try:
                offset = float(offset_str)
                new_path = IdlixHelper.shift_srt_file(path, offset)
                logger.success(f"Shifted subtitle saved successfully: {new_path}")
                messagebox.showinfo("Success", f"Subtitle adjusted by {offset:+.2f}s:\n{os.path.basename(new_path)}")
            except Exception as e:
                logger.error(f"Failed to shift subtitle: {e}")
                messagebox.showerror("Error", f"Failed to shift subtitle: {e}")

    # ============================================================
    # CORE PROCESS (100% same as CLI)
    # ============================================================
    def process_movie(self, url: str, mode: str, time_offset: float = 0.0):

        def task():
            idlix = self.idlix

            # 1. get video data
            video_data = retry(idlix.get_video_data, url)
            if not video_data.get("status"):
                logger.error("Error getting video data")
                return

            # Handle TV series root URL (prompt for Season and Episode/Batch)
            if video_data.get("is_series"):
                seasons = video_data.get("seasons", [])
                if not seasons:
                    logger.error("No seasons found for this series.")
                    return

                season_choices = [
                    f"Season {s.get('seasonNumber', i+1)}: {s.get('name', '')}"
                    for i, s in enumerate(seasons)
                ]

                s_event = threading.Event()
                selected_season_str = None

                def ask_s():
                    nonlocal selected_season_str
                    selected_season_str = self.ask_selection("Select Season", f"Choose Season for {video_data.get('series_title')}:", season_choices)
                    s_event.set()

                self.root.after(0, ask_s)
                s_event.wait()
                if not selected_season_str:
                    return

                s_idx = season_choices.index(selected_season_str)
                season_num = seasons[s_idx].get("seasonNumber", s_idx + 1)

                logger.info(f"Fetching episodes for Season {season_num}...")
                eps_data = idlix.get_season_episodes(video_data["slug"], season_num)
                episodes = eps_data.get("episodes", [])
                if not episodes:
                    logger.error(f"No episodes found for Season {season_num}")
                    return

                # If Play mode -> Single episode selection
                if mode == "play":
                    ep_choices = [
                        f"Ep {e.get('episodeNumber')}: {e.get('name', 'Episode ' + str(e.get('episodeNumber')))}"
                        for e in episodes
                    ]

                    e_event = threading.Event()
                    selected_ep_str = None

                    def ask_e():
                        nonlocal selected_ep_str
                        selected_ep_str = self.ask_selection("Select Episode", f"Choose Episode to Play (Season {season_num}):", ep_choices)
                        e_event.set()

                    self.root.after(0, ask_e)
                    e_event.wait()
                    if not selected_ep_str:
                        return

                    e_idx = ep_choices.index(selected_ep_str)
                    ep_num = episodes[e_idx].get("episodeNumber")

                    video_data = idlix.get_episode_data(video_data["slug"], season_num, ep_num)
                    if not video_data.get("status"):
                        logger.error("Failed to load episode.")
                        return
                else:
                    # Download or Subtitle mode -> Multi-episode / Whole Season Batch flow
                    ep_event = threading.Event()
                    selected_episodes = []

                    def ask_eps():
                        nonlocal selected_episodes
                        selected_episodes = self.ask_episodes_selection(
                            "Select Episodes to Download",
                            f"Select Episodes for {video_data.get('series_title')} (Season {season_num}):",
                            episodes
                        )
                        ep_event.set()

                    self.root.after(0, ask_eps)
                    ep_event.wait()

                    if not selected_episodes:
                        logger.warning("Episode selection cancelled.")
                        return

                    safe_series_title = re.sub(r'[\\/*?:"<>|]', '', video_data.get("series_title") or video_data.get("slug", "Series")).strip()
                    output_dir = os.path.join(os.getcwd(), "downloads", safe_series_title, f"Season {season_num}")
                    os.makedirs(output_dir, exist_ok=True)
                    logger.info(f"Target download folder: {output_dir}")

                    total_eps = len(selected_episodes)
                    selected_quality_pref = "best"
                    probe_helper = None
                    probe_data = None
                    probe_m3u8 = None

                    # Set quality ONCE for all episodes in the batch
                    if mode == "download":
                        first_ep = selected_episodes[0]
                        logger.info(f"Probing video stream quality using Episode {first_ep}...")
                        probe_helper = IdlixHelper()
                        probe_data = retry(probe_helper.get_episode_data, video_data["slug"], season_num, first_ep)
                        if not probe_data.get("status"):
                            logger.error(f"Failed to probe stream quality: {probe_data.get('message')}")
                            return

                        probe_embed = retry(probe_helper.get_embed_url)
                        if not probe_embed.get("status"):
                            logger.error("Failed to unlock stream for quality probing")
                            return

                        probe_m3u8 = retry(probe_helper.get_m3u8_url)
                        if probe_m3u8.get("status") and probe_m3u8.get("is_variant_playlist"):
                            choices = ["Auto - Best Available (Highest Quality)"] + [
                                f"{v['id']} - {v['resolution']}" for v in probe_m3u8["variant_playlist"]
                            ]

                            q_event = threading.Event()
                            chosen_variant_str = None

                            def ask_q():
                                nonlocal chosen_variant_str
                                chosen_variant_str = self.ask_variant(choices)
                                q_event.set()

                            self.root.after(0, ask_q)
                            q_event.wait()

                            if not chosen_variant_str:
                                logger.warning("Quality selection cancelled.")
                                return

                            if chosen_variant_str.startswith("Auto"):
                                selected_quality_pref = "best"
                                logger.success("Quality format set to: Best Available (Auto)")
                            else:
                                selected_quality_pref = chosen_variant_str.split(" - ")[1].strip()
                                logger.success(f"Quality format set to: {selected_quality_pref} (applied to all {total_eps} episodes)")
                        else:
                            logger.info("Video has single quality stream. Default quality will be used for all episodes.")

                    # Run sequential batch execution
                    logger.info(f"Starting batch download of {total_eps} episode(s)...")
                    succeeded = 0
                    failed = 0

                    for idx, ep_num in enumerate(selected_episodes, 1):
                        logger.info("-" * 60)
                        logger.info(f"[{idx}/{total_eps}] Processing Season {season_num} Episode {ep_num}...")
                        logger.info("-" * 60)

                        if idx == 1 and probe_helper and probe_helper.m3u8_url and mode == "download":
                            ep_helper = probe_helper
                            ep_data = probe_data
                            m3u8 = probe_m3u8
                        else:
                            ep_helper = IdlixHelper()
                            ep_data = retry(ep_helper.get_episode_data, video_data["slug"], season_num, ep_num)
                            if not ep_data.get("status"):
                                logger.error(f"Error loading Episode {ep_num}: {ep_data.get('message')}")
                                failed += 1
                                continue

                            embed = retry(ep_helper.get_embed_url)
                            if not embed.get("status"):
                                logger.error(f"Error unlocking stream for Episode {ep_num}")
                                failed += 1
                                continue

                            m3u8 = retry(ep_helper.get_m3u8_url)
                            if not m3u8.get("status") and mode == "download":
                                logger.error(f"Error getting M3U8 for Episode {ep_num}")
                                failed += 1
                                continue

                        if mode == "download":
                            current_res = "Default"
                            if m3u8.get("is_variant_playlist"):
                                best_v, is_exact = IdlixHelper.select_best_variant(m3u8["variant_playlist"], selected_quality_pref)
                                if best_v:
                                    ep_helper.set_m3u8_url(best_v["uri"])
                                    current_res = best_v.get("resolution", "-")
                                    if not is_exact and selected_quality_pref != "best":
                                        logger.warning(
                                            f"Target quality '{selected_quality_pref}' unavailable for Ep {ep_num}. "
                                            f"Falling back to {current_res}"
                                        )
                                    else:
                                        logger.success(f"Quality applied for Ep {ep_num}: {current_res}")

                            logger.info(f"Downloading {ep_data['video_name']} (with subtitles)...")
                            res_dl = ep_helper.download_m3u8(output_dir=output_dir, time_offset=time_offset)
                            if res_dl.get("status"):
                                logger.success(f"Downloaded Ep {ep_num}: {res_dl.get('path')}")
                                succeeded += 1
                            else:
                                logger.error(f"Download failed Ep {ep_num}: {res_dl.get('message')}")
                                failed += 1
                        elif mode == "subtitle":
                            logger.info(f"Downloading subtitles for {ep_data['video_name']}...")
                            subs = ep_helper.get_subtitles(download=True, output_dir=output_dir, time_offset=time_offset)
                            if subs:
                                logger.success(f"Downloaded {len(subs)} subtitle(s) for Ep {ep_num}")
                                succeeded += 1
                            else:
                                logger.warning(f"No subtitles available for Ep {ep_num}")
                                failed += 1

                    logger.info("=" * 60)
                    logger.info(f"BATCH FINISHED: {succeeded} Succeeded, {failed} Failed")
                    logger.info(f"Folder: {output_dir}")
                    logger.info("=" * 60)

                    def show_batch_done():
                        messagebox.showinfo(
                            "Batch Download Complete",
                            f"Batch download finished for Season {season_num}!\n\n"
                            f"Succeeded: {succeeded}\n"
                            f"Failed: {failed}\n\n"
                            f"Saved to: {output_dir}"
                        )

                    self.root.after(0, show_batch_done)
                    return

            logger.info(
                f"Media Ready | ID: {video_data['video_id']} | Title: {video_data['video_name']}"
            )

            # 2. embed URL
            embed = retry(idlix.get_embed_url)
            if not embed.get("status"):
                logger.error("Error getting embed URL")
                return

            logger.success(f"Embed: {embed['embed_url']}")

            # SUBTITLE ONLY
            if mode == "subtitle":
                logger.info(f"Downloading subtitles for {video_data['video_name']}...")
                if time_offset != 0.0:
                    logger.info(f"Sync offset applied: {time_offset:+.2f}s")
                subs = idlix.get_subtitles(download=True, time_offset=time_offset)
                if subs:
                    logger.success(f"Downloaded {len(subs)} subtitle file(s) (.srt):")
                    for sub in subs:
                        logger.info(f" - [{sub.get('label', sub.get('lang'))}] {sub.get('srt_path')}")
                else:
                    logger.warning("No subtitles available for this title.")
                return

            # 3. m3u8
            m3u8 = retry(idlix.get_m3u8_url)
            if not m3u8.get("status"):
                logger.error("Error getting M3U8 URL")
                return

            logger.success(f"M3U8: {m3u8['m3u8_url']}")

            # 4. variant playlist
            if m3u8.get("is_variant_playlist"):
                choices = [
                    f"{v['id']} - {v['resolution']}" for v in m3u8["variant_playlist"]
                ]

                selected = None

                def ask():
                    nonlocal selected
                    selected = self.ask_variant(choices)

                self.root.after(0, ask)
                while selected is None:
                    self.root.update()

                selected_id = selected.split(" - ")[0]

                for v in m3u8["variant_playlist"]:
                    if str(v["id"]) == selected_id:
                        idlix.set_m3u8_url(v["uri"])
                        logger.success(f"Variant selected: {v['resolution']}")
                        break
            else:
                logger.warning("No variant playlist.")

            # PLAY
            if mode == "play":
                subtitle = idlix.get_subtitle()

                subtitle_file = subtitle["subtitle"] if subtitle.get("status") else None

                self.start_ffplay(idlix.m3u8_url, subtitle_file)

            # DOWNLOAD
            else:
                logger.info("Starting download with subtitles...")
                result = idlix.download_m3u8(time_offset=time_offset)
                if result.get("status"):
                    sub_info = " (with embedded subtitles)" if result.get("subtitles_muxed") else ""
                    logger.success(f"Downloaded{sub_info}: {result['path']}")
                    if result.get("subtitles"):
                        logger.info(f"Subtitles saved alongside video ({len(result['subtitles'])} file(s))")
                else:
                    logger.error(f"Download failed: {result.get('message')}")

        threading.Thread(target=task, daemon=True).start()

    # ============================================================
    # ffplay controls
    # ============================================================
    def start_ffplay(self, m3u8_url, subtitle=None):

        self.stop_player()

        args = [
            "ffplay",
            "-allowed_segment_extensions", "ALL",
            "-extension_picky", "0",
            "-headers", "Referer: https://z2.idlixku.com/\r\nOrigin: https://z2.idlixku.com\r\n",
            "-i", m3u8_url,
            "-window_title", "IDLIX Player",
            "-loglevel", "panic"
        ]

        if subtitle:
            args += ["-vf", f"subtitles={subtitle}"]

        logger.info("Opening ffplay...")
        self.ffplay_process = subprocess.Popen(args)

    def stop_player(self):
        if self.ffplay_process and self.ffplay_process.poll() is None:
            try:
                self.ffplay_process.terminate()
                logger.info("ffplay terminated.")
            except:
                pass

    def open_download_folder(self):
        webbrowser.open(os.getcwd())

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete(1.0, tk.END)
        self.log_box.configure(state="disabled")


# ============================================================
# RUN APP
# ============================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = IdlixGUI(root)
    root.mainloop()
