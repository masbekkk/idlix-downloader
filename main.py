import os
import re
from src.idlixHelper import IdlixHelper, logger
from prettytable import PrettyTable
import inquirer
import threading
import time

RETRY_LIMIT = 3


def retry(func, *args, **kwargs):
    for _ in range(RETRY_LIMIT):
        result = func(*args, **kwargs)
        if result and result.get("status"):
            return result
        time.sleep(1)
    return {"status": False, "message": "Maximum retry reached"}


def play_m3u8_thread(idlix_helper):
    result = idlix_helper.play_m3u8()
    if result.get("status"):
        logger.success("Playing Success")
    else:
        logger.error("Error playing m3u8")


def print_batch_summary(records: list, output_dir: str = None):
    if not records:
        return
    table = PrettyTable()
    table.field_names = ["Ep", "Title", "Resolution", "Status", "Details / File"]
    table.align = "l"
    passed = 0
    failed = 0
    for r in records:
        table.add_row([
            r.get("ep", "-"),
            r.get("title", "-"),
            r.get("resolution", "-"),
            r.get("status", "-"),
            r.get("info", "-")
        ])
        if r.get("status") == "SUCCESS":
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print(f"BATCH DOWNLOAD SUMMARY (Success: {passed}, Failed: {failed})")
    if output_dir:
        print(f"Output Directory: {output_dir}")
    print("=" * 60)
    print(table)
    print("=" * 60 + "\n")


def process_series_batch(series_data: dict, season_num: int, target_episodes: list, mode: str, time_offset: float = 0.0):
    series_title = series_data.get("series_title") or series_data.get("slug", "Series")
    safe_series_title = re.sub(r'[\\/*?:"<>|]', '', series_title).strip()
    slug = series_data["slug"]
    output_dir = os.path.join(os.getcwd(), "downloads", safe_series_title, f"Season {season_num}")
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"Target download folder: {output_dir}")

    total_eps = len(target_episodes)
    selected_quality_pref = "best"
    probe_helper = None
    probe_data = None
    probe_m3u8 = None

    # Step 1: Prompt quality format ONCE if in download mode
    if mode == "download":
        first_ep = target_episodes[0]
        logger.info(f"Probing video stream quality using Episode {first_ep}...")
        probe_helper = IdlixHelper()
        probe_data = retry(probe_helper.get_episode_data, slug, season_num, first_ep)
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
            q_question = [
                inquirer.List(
                    "variant",
                    message=f"Select Video Quality format for this batch ({total_eps} episodes):",
                    choices=choices,
                    carousel=True
                )
            ]
            q_ans = inquirer.prompt(q_question)
            if not q_ans:
                logger.warning("Batch download cancelled.")
                return

            selected_raw = q_ans["variant"]
            if selected_raw.startswith("Auto"):
                selected_quality_pref = "best"
                logger.success("Quality format set to: Best Available (Auto)")
            else:
                selected_quality_pref = selected_raw.split(" - ")[1].strip()
                logger.success(f"Quality format set to: {selected_quality_pref} (applied to all episodes)")
        else:
            logger.info("Video has single quality stream. Default quality will be used for all episodes.")

    # Step 2: Sequential batch download loop
    summary_records = []
    logger.info(f"Starting batch processing of {total_eps} episode(s)...")

    for idx, ep_num in enumerate(target_episodes, 1):
        logger.info("-" * 60)
        logger.info(f"[{idx}/{total_eps}] Processing Season {season_num} Episode {ep_num}...")
        logger.info("-" * 60)

        # Reuse probe helper for first episode if already unlocked and probed
        if idx == 1 and probe_helper and probe_helper.m3u8_url and mode == "download":
            ep_helper = probe_helper
            ep_data = probe_data
            m3u8 = probe_m3u8
        else:
            ep_helper = IdlixHelper()
            ep_data = retry(ep_helper.get_episode_data, slug, season_num, ep_num)
            if not ep_data.get("status"):
                logger.error(f"Error loading Episode {ep_num}: {ep_data.get('message')}")
                summary_records.append({
                    "ep": ep_num,
                    "title": f"Episode {ep_num}",
                    "resolution": "-",
                    "status": "FAILED",
                    "info": ep_data.get("message", "Episode data error")
                })
                continue

            embed = retry(ep_helper.get_embed_url)
            if not embed.get("status"):
                logger.error(f"Error unlocking stream for Episode {ep_num}")
                summary_records.append({
                    "ep": ep_num,
                    "title": ep_data.get("video_name", f"Episode {ep_num}"),
                    "resolution": "-",
                    "status": "FAILED",
                    "info": embed.get("message", "Stream unlock timeout")
                })
                continue

            m3u8 = retry(ep_helper.get_m3u8_url)
            if not m3u8.get("status") and mode == "download":
                logger.error(f"Error getting M3U8 for Episode {ep_num}")
                summary_records.append({
                    "ep": ep_num,
                    "title": ep_data.get("video_name", f"Episode {ep_num}"),
                    "resolution": "-",
                    "status": "FAILED",
                    "info": m3u8.get("message", "M3U8 fetch failed")
                })
                continue

        # Match video quality automatically without prompting
        current_res = "Default"
        if mode == "download":
            if m3u8.get("is_variant_playlist"):
                best_v, is_exact = IdlixHelper.select_best_variant(m3u8["variant_playlist"], selected_quality_pref)
                if best_v:
                    ep_helper.set_m3u8_url(best_v["uri"])
                    current_res = best_v.get("resolution", "-")
                    if not is_exact and selected_quality_pref != "best":
                        logger.warning(
                            f"Target quality '{selected_quality_pref}' not available for Ep {ep_num}. "
                            f"Falling back to {current_res}"
                        )
                    else:
                        logger.success(f"Quality applied for Ep {ep_num}: {current_res}")

            logger.info(f"Downloading {ep_data['video_name']} (with subtitles)...")
            res_dl = ep_helper.download_m3u8(output_dir=output_dir, time_offset=time_offset)
            if res_dl.get("status"):
                logger.success(f"Downloaded Ep {ep_num}: {res_dl.get('path')}")
                summary_records.append({
                    "ep": ep_num,
                    "title": ep_data.get("video_name"),
                    "resolution": current_res,
                    "status": "SUCCESS",
                    "info": os.path.basename(res_dl.get("path", ""))
                })
            else:
                logger.error(f"Download failed Ep {ep_num}: {res_dl.get('message')}")
                summary_records.append({
                    "ep": ep_num,
                    "title": ep_data.get("video_name"),
                    "resolution": current_res,
                    "status": "FAILED",
                    "info": res_dl.get("message", "Download error")
                })
        elif mode == "subtitle":
            logger.info(f"Downloading subtitles for {ep_data['video_name']}...")
            subs = ep_helper.get_subtitles(download=True, output_dir=output_dir, time_offset=time_offset)
            if subs:
                logger.success(f"Downloaded {len(subs)} subtitle file(s) for Ep {ep_num}")
                summary_records.append({
                    "ep": ep_num,
                    "title": ep_data.get("video_name"),
                    "resolution": "N/A",
                    "status": "SUCCESS",
                    "info": f"{len(subs)} subtitle(s)"
                })
            else:
                logger.warning(f"No subtitles available for Ep {ep_num}")
                summary_records.append({
                    "ep": ep_num,
                    "title": ep_data.get("video_name"),
                    "resolution": "N/A",
                    "status": "NO_SUBS",
                    "info": "No subtitles"
                })

    print_batch_summary(summary_records, output_dir)


def process_movie(idlix_helper, url: str, mode: str, time_offset: float = 0.0):
    video_data = retry(idlix_helper.get_video_data, url)
    if not video_data.get("status"):
        logger.error("Error getting video data")
        return

    # Handle TV series root URL (prompt for Season and Episode/Batch)
    if video_data.get("is_series"):
        seasons = video_data.get("seasons", [])
        if not seasons:
            logger.error("No seasons found for this series")
            return

        season_choices = [
            f"Season {s.get('seasonNumber', i+1)}: {s.get('name', '')}"
            for i, s in enumerate(seasons)
        ]
        s_question = [
            inquirer.List(
                "season",
                message=f"Select Season for {video_data.get('series_title')}",
                choices=season_choices,
                carousel=True
            )
        ]
        s_answer = inquirer.prompt(s_question)
        if not s_answer:
            return
        selected_season_idx = season_choices.index(s_answer["season"])
        season_num = seasons[selected_season_idx].get("seasonNumber", selected_season_idx + 1)

        logger.info(f"Fetching episodes for Season {season_num}...")
        eps_data = idlix_helper.get_season_episodes(video_data["slug"], season_num)
        episodes = eps_data.get("episodes", [])
        if not episodes:
            logger.error(f"No episodes found for Season {season_num}")
            return

        # If playing, prompt for single episode to play
        if mode == "play":
            ep_choices = [
                f"Ep {e.get('episodeNumber')}: {e.get('name', 'Episode ' + str(e.get('episodeNumber')))}"
                for e in episodes
            ]
            e_question = [
                inquirer.List(
                    "episode",
                    message=f"Select Episode to Play (Season {season_num})",
                    choices=ep_choices,
                    carousel=True
                )
            ]
            e_answer = inquirer.prompt(e_question)
            if not e_answer:
                return
            selected_ep_idx = ep_choices.index(e_answer["episode"])
            ep_num = episodes[selected_ep_idx].get("episodeNumber")

            video_data = idlix_helper.get_episode_data(video_data["slug"], season_num, ep_num)
            if not video_data.get("status"):
                logger.error("Error loading selected episode")
                return
        else:
            # Mode is "download" or "subtitle" -> Offer batch or single selection
            mode_choices = [
                f"Download Whole Season {season_num} ({len(episodes)} episodes)",
                "Download Multiple Episodes (range/list e.g. 1-5, 8)",
                "Download Single Episode"
            ]
            m_question = [
                inquirer.List(
                    "scope",
                    message=f"Choose Episode selection for Season {season_num}:",
                    choices=mode_choices,
                    carousel=True
                )
            ]
            m_answer = inquirer.prompt(m_question)
            if not m_answer:
                return

            chosen_scope = m_answer["scope"]
            if chosen_scope.startswith("Download Whole Season"):
                target_episodes = [e.get("episodeNumber", i + 1) for i, e in enumerate(episodes)]
            elif chosen_scope.startswith("Download Multiple Episodes"):
                r_question = [
                    inquirer.Text(
                        "range",
                        message=f"Enter episode numbers or range (e.g. 1-{len(episodes)} or 1,3,5):"
                    )
                ]
                r_answer = inquirer.prompt(r_question)
                if not r_answer or not r_answer.get("range"):
                    logger.warning("No range provided.")
                    return
                try:
                    target_episodes = IdlixHelper.parse_episode_selection(r_answer["range"], episodes)
                except ValueError as err:
                    logger.error(f"Invalid episode selection: {err}")
                    return
                if not target_episodes:
                    logger.error("No valid episodes found matching your input.")
                    return
            else:
                # Single episode
                ep_choices = [
                    f"Ep {e.get('episodeNumber')}: {e.get('name', 'Episode ' + str(e.get('episodeNumber')))}"
                    for e in episodes
                ]
                e_question = [
                    inquirer.List(
                        "episode",
                        message=f"Select Episode (Season {season_num})",
                        choices=ep_choices,
                        carousel=True
                    )
                ]
                e_answer = inquirer.prompt(e_question)
                if not e_answer:
                    return
                selected_ep_idx = ep_choices.index(e_answer["episode"])
                target_episodes = [episodes[selected_ep_idx].get("episodeNumber")]

            # Run series batch downloader with single quality prompt
            process_series_batch(video_data, season_num, target_episodes, mode, time_offset)
            return

    # Normal Movie Flow (or single episode playback)
    logger.info(
        f"Media Ready | ID: {video_data['video_id']} | Title: {video_data['video_name']}"
    )

    embed = retry(idlix_helper.get_embed_url)
    if not embed.get("status"):
        logger.error("Error getting embed URL")
        return

    logger.success(f"Getting embed URL: {embed['embed_url']}")

    # If subtitle only mode → download subtitles and return immediately
    if mode == "subtitle":
        logger.info(f"Downloading subtitles for {video_data['video_name']}...")
        if time_offset != 0.0:
            logger.info(f"Sync offset applied: {time_offset:+.2f}s")
        subs = idlix_helper.get_subtitles(download=True, time_offset=time_offset)
        if subs:
            logger.success(f"Downloaded {len(subs)} subtitle file(s) (.srt):")
            for sub in subs:
                logger.info(f" - [{sub.get('label', sub.get('lang'))}] {sub.get('srt_path')}")
        else:
            logger.warning("No subtitles available for this movie/episode.")
        return

    m3u8 = retry(idlix_helper.get_m3u8_url)
    if not m3u8.get("status"):
        logger.error("Error getting M3U8 URL")
        return

    logger.success(f"Getting m3u8 URL | {m3u8['m3u8_url']}")

    if m3u8.get("is_variant_playlist"):
        logger.warning("This video has a variant playlist")

        choices = [
            f"{v['id']} - {v['resolution']}" for v in m3u8["variant_playlist"]
        ]

        question = [
            inquirer.List(
                "variant",
                message="Select variant",
                choices=choices,
                carousel=True
            )
        ]
        answer = inquirer.prompt(question)

        selected_id = answer["variant"].split(" - ")[0]

        for v in m3u8["variant_playlist"]:
            if str(v["id"]) == selected_id:
                idlix_helper.set_m3u8_url(v["uri"])
                logger.success(f"Selected variant: {v['resolution']}")
                break
    else:
        logger.warning("This video has no variant playlist")

    # 5. If play → play with subtitle
    if mode == "play":
        subtitle = idlix_helper.get_subtitle()
        if subtitle.get("status"):
            logger.success("Subtitle downloaded")
        else:
            logger.warning("Subtitle unavailable")

        logger.info(f"Playing {video_data['video_name']} ...")

        th = threading.Thread(target=play_m3u8_thread, args=(idlix_helper,))
        th.daemon = True
        th.start()

        # avoid hang forever
        th.join(timeout=5)

    # 6. If download
    else:
        logger.info(f"Starting download for {video_data['video_name']} (with subtitles)...")
        result = idlix_helper.download_m3u8(time_offset=time_offset)
        if result.get("status"):
            logger.success(f"Downloading {video_data['video_name']} success: {result['path']}")
            if result.get("subtitles_muxed"):
                logger.success("Subtitles successfully embedded into MP4 container (mov_text)")
            if result.get("subtitles"):
                logger.info(f"Saved {len(result['subtitles'])} external subtitle file(s) (.srt) matching movie name")
        else:
            logger.error(f"Error downloading m3u8: {result.get('message')}")


def show_featured_table(featured):
    table = PrettyTable()
    table.align = "l"
    table.title = "Featured Movie List"
    table.field_names = ["No", "Title", "Year", "Type", "URL"]

    for i, movie in enumerate(featured):
        table.add_row([
            i + 1,
            movie["title"],
            movie["year"],
            movie["type"],
            movie["url"]
        ])

    print(table)


def main():
    status_exit = False

    while not status_exit:
        idlix = IdlixHelper()
        home = retry(idlix.get_home)

        if not home.get("status") or len(home.get("featured_movie", [])) == 0:
            logger.error(f"Error fetching home: {home.get('message')}")
            break

        featured = home["featured_movie"]
        show_featured_table(featured)

        # Main Menu
        question = [
            inquirer.List(
                "action",
                message="Select action",
                choices=[
                    "Download Featured Movie",
                    "Play Featured Movie",
                    "Download Subtitles Only (Featured)",
                    "Download Movie by URL",
                    "Play Movie by URL",
                    "Download Subtitles Only by URL",
                    "Shift / Sync Existing Subtitle File (.srt)",
                    "Exit"
                ],
                carousel=True
            )
        ]
        answer = inquirer.prompt(question)
        action = answer["action"]
        if action in [
            "Download Featured Movie",
            "Play Featured Movie",
            "Download Subtitles Only (Featured)"
        ]:
            # Select movie
            movie_question = [
                inquirer.List(
                    "movie",
                    message="Select movie",
                    choices=[i["title"] for i in featured],
                    carousel=True
                )
            ]
            choice = inquirer.prompt(movie_question)

            selected = next(
                (m for m in featured if m["title"] == choice["movie"]),
                None
            )

            if not selected:
                logger.error("Movie not found")
                continue

            time_offset = 0.0
            if "Subtitles Only" in action:
                mode = "subtitle"
                offset_inp = input("Enter subtitle sync offset in seconds (e.g. -1.2 to display earlier, 0.0 for original): ").strip()
                if offset_inp:
                    try:
                        time_offset = float(offset_inp)
                    except ValueError:
                        logger.warning("Invalid offset number, using 0.0s")
            elif "Download" in action:
                mode = "download"
            else:
                mode = "play"

            process_movie(idlix, selected["url"], mode, time_offset=time_offset)


        elif action == "Download Movie by URL":
            url = input("Enter movie URL: ").strip()
            process_movie(idlix, url, "download")

        elif action == "Play Movie by URL":
            url = input("Enter movie URL: ").strip()
            process_movie(idlix, url, "play")

        elif action == "Download Subtitles Only by URL":
            url = input("Enter movie URL: ").strip()
            offset_inp = input("Enter subtitle sync offset in seconds (e.g. -1.2 to display earlier, 0.0 for original): ").strip()
            time_offset = 0.0
            if offset_inp:
                try:
                    time_offset = float(offset_inp)
                except ValueError:
                    logger.warning("Invalid offset number, using 0.0s")
            process_movie(idlix, url, "subtitle", time_offset=time_offset)

        elif action == "Shift / Sync Existing Subtitle File (.srt)":
            import os
            srt_path = input("Enter path to existing .srt file: ").strip()
            if os.path.exists(srt_path):
                offset_inp = input("Enter offset in seconds (e.g. -1.2 to shift earlier, +1.5 to delay): ").strip()
                try:
                    offset_val = float(offset_inp)
                    out_path = IdlixHelper.shift_srt_file(srt_path, offset_val)
                    logger.success(f"Shifted subtitle saved successfully: {out_path}")
                except ValueError:
                    logger.error("Invalid offset number")
                except Exception as e:
                    logger.error(f"Error shifting subtitle: {e}")
            else:
                logger.error(f"File not found: {srt_path}")

        # Exit
        else:
            logger.info("Exiting...")
            status_exit = True


if __name__ == "__main__":
    main()
