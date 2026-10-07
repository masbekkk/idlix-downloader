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


def process_movie(idlix_helper, url: str, mode: str, time_offset: float = 0.0):
    video_data = retry(idlix_helper.get_video_data, url)
    if not video_data.get("status"):
        logger.error("Error getting video data")
        return

    # Handle TV series root URL (prompt for Season and Episode)
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
        ep_num = episodes[selected_ep_idx].get("episodeNumber")

        video_data = idlix_helper.get_episode_data(video_data["slug"], season_num, ep_num)
        if not video_data.get("status"):
            logger.error("Error loading selected episode")
            return

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
