# VoicesAssist - Agent & Developer Guide

This document explains how the VoicesAssist helper is put together so agents, technical owners, and contributors can configure, troubleshoot, and extend it with confidence.

## Repository structure
- `main_gui.py` - Tkinter desktop shell that launches the automation scripts, streams logs, and exposes controls such as pause/cancel and the speed slider.
- `invite_to_job.py`, `add_to_favorites.py`, `message_talent.py`, `import_invites.py`, `export_responses.py` - Playwright-based flows that interact with Voices.com once a debug browser is available.
- `common_logging.py` - Shared helpers for consistent console output (ANSI aware, GUI friendly).
- `assets/` - UI artwork (Voices favicon) used by the GUI when Pillow is installed.
- `logs/` - Rotating output folder for screenshots, CSVs, and troubleshooting captures.
- `voices_debug_profile/` - Chrome/Edge user data directory created when the GUI launches the debug browser.
- `gui_state.json`, `speed.cfg` - Runtime state persisted between launches.

## Environment and tooling
1. Create a virtual environment and install dependencies:
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install --upgrade pip
   pip install playwright pillow tkinterdnd2 psutil
   python -m playwright install chromium
   ```
   `psutil` enables pause/resume from the GUI; `pillow` improves icon scaling; `tkinterdnd2` adds optional drag-and-drop support. All Playwright scripts target Chromium but can attach to Chrome or Edge via CDP.
2. Launch the GUI with `python main_gui.py`. The **Open Voices** button starts Chrome with `--remote-debugging-port=9222` and a persistent profile stored in `voices_debug_profile/`.
3. All scripts expect an authenticated tab to already be open. The GUI enforces `USE_CURRENT_PAGE=1` by default so the scripts attach to the active Voices.com tab instead of navigating away.

## Runtime architecture
- Each automation is a standalone async Playwright script. The GUI launches the selected script as a subprocess, pipes stdout back into the console pane, and watches for lines such as `Processing talent X of Y` to drive the progress bar.
- Environment variables drive configuration. The GUI injects the debug URL, optional message text, CSV path, and shared speed controls before spawning the subprocess.
- `speed.cfg` is rewritten whenever the slider moves. Scripts call `_read_speed_file()` (where implemented) so you can nudge pacing during a run without restarting.
- Pausing uses `psutil.Process.suspend()/resume()` on Windows. When `psutil` is missing the GUI disables pause and informs the user.
- `gui_state.json` stores per-action dictionaries (`invite`, `favorites`, `message`, `import_invites`) so the helper can prefill fields when a session resumes.

## Automation scripts at a glance
| Script | Primary use | Important env vars |
| --- | --- | --- |
| `invite_to_job.py` | Invite all visible talents from a search or profile page | `START_URL` (fallback navigation), `DEBUG_URL`, `SKIP_FIRST_TALENT`, `MAX_PAGES`, pacing values. First run waits for the user to pick a job in the modal and then reuses that selection. |
| `add_to_favorites.py` | Click heart/favorite buttons across listing pages | `START_URL`, `DEBUG_URL`, `SPEED`, `SPEED_FILE`, `FIRST_HEART_DELAY_MS`, `MAX_PAGES`, `AUTO_DISMISS_DROPDOWN`. Honors `USE_CURRENT_PAGE`. |
| `message_talent.py` | Send or dry-run batch messages on job response cards | `START_URL`, `DEBUG_URL`, `MESSAGE`, `SEND_ENABLED`, pacing controls, `USE_CURRENT_PAGE`. Uses the shared speed file to stretch or shrink delays. |
| `import_invites.py` | Invite a list of usernames from CSV | `CSV_PATH`, `JOB_QUERY` (job number only), `DEBUG_URL`. Navigates to each profile in turn and follows the invite flow. |
| `export_responses.py` | Optional: export job responses to CSV | `START_URL`, `OUTPUT_FILE`, `DEBUG_URL`. Saves data under `logs/` by default. |

Each script connects to the existing debug browser with `async_playwright().chromium.connect_over_cdp()`, falling back to launching Chromium if connection fails. Keep this pattern if you add new flows.

## GUI implementation notes
- Action buttons map to keys (`invite`, `favorites`, `message`, `import_invites`). `show_input_fields()` populates context-specific widgets and uses `prefill_saved_fields()` to restore values from `gui_state.json`.
- `_execute_script_thread()` builds the environment, writes `speed.cfg`, and spawns `[sys.executable, script_path]`. When you add a new script, register its env inputs there and in `show_input_fields()`.
- Console formatting strips ANSI codes and normalises glyphs so the Tkinter text widget stays clean across locales.
- Progress updates look for `Processing talent X of Y`. Emit that phrase (or adjust the regex) if your new automation can report deterministic progress.
- Pausing relies on suspending the subprocess and its children. If a new script spawns further processes, make sure they are children of the main Playwright process so the pause tree stays intact.

## Extending or supporting new flows
1. Add the new Playwright script beside the others. Prefer the shared helpers (`common_logging.info/warn/ok/err`) and respect `SPEED`/`SPEED_FILE` if pacing needs to be adjustable.
2. Update `main_gui.py`:
   - Add a button in the 2x2 grid with a unique action key.
   - Handle the key inside `show_input_fields()` and `_execute_script_thread()`.
   - Provide tooltips and `save_fields()` support if the action stores state.
3. Document any additional dependencies or environment variables so support staff know what to set.
4. When shipping to non-technical teammates consider packaging with PyInstaller, but bake `psutil`, `playwright`, and browser channels into the build - frozen apps cannot install missing packages on demand.

## Debugging tips
- Run scripts directly from the terminal during development, e.g.:
  ```powershell
  $env:DEBUG_URL = "http://127.0.0.1:9222"
  $env:START_URL = "https://www.voices.com/talents/search?..."
  python invite_to_job.py
  ```
  Use `USE_CURRENT_PAGE=0` to force navigation when you want to test the full flow.
- Set `PYTHONASYNCIODEBUG=1` for additional asyncio diagnostics.
- Grab raw CDP traffic with `PLAYWRIGHT_CLI_LOG=1 npx playwright test` if you need to troubleshoot selectors.
- Automation-related screenshots and CSVs are dropped into `logs/`; clear the folder between runs when comparing behaviour.

Keep this guide alongside the user-facing README so both audiences have the context they need.
