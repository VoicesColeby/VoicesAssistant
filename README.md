# Voices Assistant Automation

This project automates bulk invitations for talent on [Voices.com](https://www.voices.com/) and ships with a Tk-based desktop GUI for configuring and launching the Playwright workflows. The automation mimics human interaction patterns so you can invite large batches of talent reliably while keeping visibility into each step through the console logs and GUI status panels.

## Installation

Follow these steps to set up the project on a fresh machine:

1. **Install Python 3.9 or newer.** The tooling depends on modern async features that are available in currently supported CPython releases.
2. **(Optional) Create and activate a virtual environment.** This keeps the automation's dependencies isolated from the rest of your system.
3. **Install the Python packages listed in `requirements.txt`:**

   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

   The dependency list covers:

   - `pillow` for loading and resizing logo assets in the GUI
   - `playwright` for browser automation
   - `psutil` for process monitoring (pause and resume helpers)
   - `tkinterdnd2` to provide drag-and-drop support in the Tk interface

4. **Download the Playwright browser binaries:**

   ```bash
   playwright install
   ```

   This only needs to be done once per machine and ensures the Chromium browser that the scripts drive is available locally.

## Next steps

With the dependencies installed you can:

- Launch the GUI with `python main_gui.py` for an interactive experience.
- Consult `user_guide.txt` for the environment variables and Chrome debugging setup required to run the command-line automation scripts.

The `Agent Documentation.txt` and `Technical Documentation.txt` files provide deeper insights into how the automation flows operate if you need to customise or extend the behaviours.
