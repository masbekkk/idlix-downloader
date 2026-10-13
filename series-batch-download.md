# Series Batch Download (Whole Season & Multi-Episode)

## Goal
Enhance IDLIX Downloader (both CLI and Tkinter GUI) to support downloading an entire season or multiple selected episodes of a TV series, prompting for the desired video quality format **only once** per batch and applying it automatically across all episodes.

---

## Project Type
- **Type:** CLI & Desktop GUI Application (Python 3, Tkinter, FFmpeg)
- **Primary Agents:** `backend-specialist` (Core & CLI logic) + `frontend-specialist` (Tkinter GUI components)

---

## Success Criteria
- [ ] Users can choose between downloading a Single Episode, Multiple Episodes (e.g. `1-5`, `1,3,7`), or Whole Season.
- [ ] Video quality selection prompt is displayed **only once** at the beginning of the batch.
- [ ] Subsequent episodes automatically match the selected quality (or fallback to the closest available quality if the exact resolution is unavailable).
- [ ] Batch downloads run sequentially with real-time progress logging (`[Ep X/Y] Processing...`).
- [ ] If any single episode fails, the process logs the error and continues downloading remaining episodes without crashing.
- [ ] Final summary is displayed showing successful and failed downloads.
- [ ] Both CLI (`main.py`) and GUI (`main_gui.py`) share consistent batch downloading capabilities.

---

## Tech Stack & Architecture
- **Language:** Python 3
- **Network / API:** `requests`, `curl_cffi`, `m3u8`
- **CLI Interaction:** `inquirer`, `prettytable`
- **GUI:** `tkinter`, `tkinter.ttk`, `tkinter.simpledialog`
- **Media Processing:** `ffmpeg` (segment stitching and subtitle muxing)
- **Core Engine:** `src/idlixHelper.py` (`IdlixHelper`)

---

## File Structure & Affected Files
```
IdlixDownloader-1.0.0/
├── series-batch-download.md         # This execution plan
├── src/
│   └── idlixHelper.py               # Smart quality matching & episode helpers
├── main.py                          # CLI series menu, episode range input & batch runner
├── main_gui.py                      # GUI season/episode multi-select dialog & batch task runner
├── tests/
│   └── test_series_batch.py         # Unit tests for range parser & quality resolution matching
└── readme.md                        # Documentation of series batch download feature
```

---

## Task Breakdown

### Task 1: Episode Range & Selection Parser Utility
- **Agent:** `backend-specialist`
- **Skills:** `@clean-code`, `@python-patterns`
- **Input:** User input string like `"1-5"`, `"1, 3, 5-7"`, or `"all"`, and available episode list.
- **Output:** Clean helper function `parse_episode_selection(input_str: str, available_episodes: list) -> list` returning validated, deduplicated, sorted list of episode numbers.
- **Verify:** Unit test with valid ranges (`1-4`), comma lists (`1,3`), mixed (`1-3, 5`), out-of-range bounds, and invalid formats.

---

### Task 2: Smart Quality Resolution Matcher in `src/idlixHelper.py`
- **Agent:** `backend-specialist`
- **Skills:** `@clean-code`, `@python-patterns`
- **Input:** Target quality specification selected by user (e.g. resolution height `1080`, label `"1080p"`, or `"best"`), and an episode's variant playlist items.
- **Output:** Helper method `select_best_variant(variant_list, target_preference) -> dict` in `IdlixHelper` that selects the exact match or nearest fallback resolution without prompting the user again.
- **Verify:** Unit test matching 1080p preference against playlists with `[1080p, 720p, 480p]`, `[720p, 480p]`, and single-resolution stream.

---

### Task 3: CLI Series Batch Flow in `main.py`
- **Agent:** `backend-specialist`
- **Skills:** `@clean-code`
- **Input:** Series root URL or episode URL detected in CLI.
- **Output:** 
  1. Updated series prompt:
     - "Download Whole Season ({N} episodes)"
     - "Download Multiple Episodes (range/list)"
     - "Download Single Episode"
  2. Quality prompt shown ONCE using the first episode's playlist (plus "Best Available" option).
  3. Batch loop iterating through all chosen episodes, calling `get_episode_data`, `get_embed_url`, `get_m3u8_url`, auto-setting the matched variant, and running `download_m3u8`.
- **Verify:** Run CLI interactive session with sample series URL, choose batch mode, select quality once, and verify sequence executes without repeated quality prompts.

---

### Task 4: GUI Multi-Episode & Whole Season Dialog in `main_gui.py`
- **Agent:** `frontend-specialist`
- **Skills:** `@clean-code`
- **Input:** Series detected in GUI download modal.
- **Output:**
  1. Interactive Season & Episode Selection dialog with:
     - Season dropdown / selector.
     - Mode buttons or checkboxes: "Whole Season", "Custom Selection" (checklist or range entry like `1-10`).
  2. Quality variant selector shown once before batch starts.
  3. Batch execution in background thread with real-time log updates (`[Batch 2/8] Downloading Ep 2...`).
- **Verify:** Open GUI via `python main_gui.py`, trigger series URL, test dialog options, verify single quality selection and threaded download logs.

---

### Task 5: Resiliency, Error Handling & Batch Summary
- **Agent:** `backend-specialist`
- **Skills:** `@clean-code`
- **Input:** Execution of multi-episode download queue.
- **Output:**
  - Catch stream unlock timeouts or missing segments per episode without terminating the remaining queue.
  - Print / display a final batch summary table:
    - Episode No | Title | Quality | Status (Success / Failed) | Output File
- **Verify:** Simulate a failing episode in test harness; verify remaining episodes continue downloading and summary displays correct counts.

---

### Task 6: Documentation & Final Verification
- **Agent:** `backend-specialist`
- **Skills:** `@clean-code`
- **Input:** Completed CLI and GUI implementations.
- **Output:** Updated `readme.md` detailing new series batch download capabilities and usage examples.
- **Verify:** Run automated verification tests, syntax checks, and review diffs.

---

## Phase X: Verification Checklist
- [x] Linting & syntax verification passes (`python -m py_compile main.py main_gui.py src/idlixHelper.py`).
- [x] Unit tests pass for episode range parser and quality matching algorithm.
- [x] CLI series batch flow tested and verified.
- [x] GUI series batch dialog tested and verified.
- [x] Video quality is confirmed to be prompted only once per batch.
- [x] Error isolation verified (a single episode failure does not kill batch).
- [x] Documentation updated in `readme.md`.

## ✅ PHASE X COMPLETE
- Lint: ✅ Pass (`py_compile` on `main.py`, `main_gui.py`, `src/idlixHelper.py`, `tests/test_series_batch.py`)
- Unit Tests: ✅ Pass (8 tests covering range parsing, fallback qualities, empty/whitespace edge cases)
- Date: 2026-10-07

