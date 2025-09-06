import os
import sys
import json
import shlex
import subprocess
import threading
import tempfile
import webbrowser
import signal
from pathlib import Path
from urllib.parse import urlparse

import tkinter as tk
from tkinter import ttk, filedialog, messagebox


DEFAULT_START_URL = "https://www.voices.com/talents/search?keywords=&language_ids=1"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_SETTINGS_FILE = "voices_gui_settings.json"


def find_chrome_path() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LocalAppData", r"C:\\Users\\%USERNAME%\\AppData\\Local")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for p in candidates:
        try:
            if p.is_file():
                return p
        except Exception:
            pass
    return None


class ProcessRunner:
    def __init__(self, on_output, on_exit):
        self.proc: subprocess.Popen | None = None
        self.on_output = on_output
        self.on_exit = on_exit
        self._reader_thread: threading.Thread | None = None

    def start(self, args: list[str], cwd: Path | None = None, env: dict | None = None):
        if self.proc and self.proc.poll() is None:
            raise RuntimeError("Process already running")
        self.on_output(f"[run] {' '.join(shlex.quote(a) for a in args)}\n")
        self.proc = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
        )

        def _reader():
            try:
                assert self.proc and self.proc.stdout
                for line in self.proc.stdout:
                    self.on_output(line)
            except Exception as e:
                self.on_output(f"[reader-error] {e}\n")
            finally:
                code = None
                try:
                    if self.proc:
                        code = self.proc.wait()
                except Exception:
                    pass
                self.on_exit(code)

        self._reader_thread = threading.Thread(target=_reader, daemon=True)
        self._reader_thread.start()

    def stop(self):
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            if os.name == 'nt':
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            else:
                self.proc.terminate()
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Voices Inviter GUI")
        self.geometry("900x650")

        self.script_path = Path(__file__).parent / "invite_all.py"
        if not self.script_path.exists():
            messagebox.showerror("Missing script", f"Could not find invite_all.py next to {Path(__file__).name}")

        self.proc = ProcessRunner(self.append_log, self.on_proc_exit)
        # Default settings path next to this script
        self.settings_path = Path(__file__).parent / DEFAULT_SETTINGS_FILE

        # Variables
        self.var_start_url = tk.StringVar(value=DEFAULT_START_URL)
        self.var_cdp_url = tk.StringVar(value=DEFAULT_CDP_URL)
        self.var_attach_cdp = tk.BooleanVar(value=True)
        self.var_require_cdp = tk.BooleanVar(value=True)
        self.var_manual_login = tk.BooleanVar(value=False)
        self.var_headless = tk.BooleanVar(value=False)
        self.var_fast = tk.BooleanVar(value=False)
        self.var_slow_mo = tk.IntVar(value=70)
        self.var_scroll_passes = tk.IntVar(value=2)
        self.var_debug = tk.BooleanVar(value=False)
        self.var_dry_run = tk.BooleanVar(value=False)
        self.var_pause_file = tk.StringVar(value="")
        self.var_log_file = tk.StringVar(value=str(Path.cwd() / "invites_log.jsonl"))
        self.var_invited_db = tk.StringVar(value=str(Path.cwd() / "invited_ids.json"))
        self.var_job_id = tk.StringVar(value="")
        self.var_job_title = tk.StringVar(value="")
        # Removed: 'No job filter' (we always require a job id/title now)

        # Favorites mode
        self.var_use_favorites = tk.BooleanVar(value=False)
        self.var_fav_list_title = tk.StringVar(value="")

        # Chrome
        self.var_profile_dir = tk.StringVar(value="Default")
        self.var_use_temp_profile = tk.BooleanVar(value=True)

        # Credentials (optional)
        self.var_email = tk.StringVar(value="")
        self.var_password = tk.StringVar(value="")

        self.build_ui()
        # Attempt to auto-load previously saved settings
        try:
            self.load_settings()
        except Exception:
            pass

    def build_ui(self):
        pad = {"padx": 6, "pady": 4}

        frm = ttk.Frame(self)
        frm.pack(fill=tk.BOTH, expand=True)

        # Row 0: Start URL
        ttk.Label(frm, text="Start URL:").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_start_url, width=100).grid(row=0, column=1, columnspan=5, sticky="we", **pad)

        # Row 1: CDP / Attach / Manual login
        ttk.Label(frm, text="CDP URL:").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_cdp_url, width=36).grid(row=1, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Attach to running Chrome", variable=self.var_attach_cdp).grid(row=1, column=2, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Require CDP", variable=self.var_require_cdp).grid(row=1, column=3, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Manual login", variable=self.var_manual_login).grid(row=1, column=4, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Headless", variable=self.var_headless).grid(row=1, column=5, sticky="w", **pad)
        ttk.Button(frm, text="Test CDP", command=self.test_cdp).grid(row=1, column=6, sticky="w", **pad)

        # Row 2: Speed / Scroll / Debug
        ttk.Checkbutton(frm, text="Fast mode", variable=self.var_fast).grid(row=2, column=0, sticky="w", **pad)
        ttk.Label(frm, text="Slow-mo (ms):").grid(row=2, column=1, sticky="e", **pad)
        ttk.Spinbox(frm, from_=0, to=1000, increment=10, textvariable=self.var_slow_mo, width=8).grid(row=2, column=2, sticky="w", **pad)
        ttk.Label(frm, text="Scroll passes:").grid(row=2, column=3, sticky="e", **pad)
        ttk.Spinbox(frm, from_=0, to=10, increment=1, textvariable=self.var_scroll_passes, width=6).grid(row=2, column=4, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Debug logs", variable=self.var_debug).grid(row=2, column=5, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Dry-run", variable=self.var_dry_run).grid(row=2, column=6, sticky="w", **pad)

        # Row 3: Job filtering / Favorites
        ttk.Label(frm, text="Job ID:").grid(row=3, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_job_id, width=18).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(frm, text="Job Title contains:").grid(row=3, column=2, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_job_title, width=26).grid(row=3, column=3, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Use Favorites (heart)", variable=self.var_use_favorites).grid(row=3, column=4, sticky="w", **pad)
        ttk.Label(frm, text="Favorites list:").grid(row=3, column=5, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_fav_list_title, width=20).grid(row=3, column=6, sticky="w", **pad)

        # Row 4: Pause file
        ttk.Label(frm, text="Pause file:").grid(row=4, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_pause_file, width=60).grid(row=4, column=1, columnspan=4, sticky="we", **pad)
        ttk.Button(frm, text="Browse…", command=self.choose_pause_file).grid(row=4, column=5, sticky="w", **pad)

        # Row 5: Log file path
        ttk.Label(frm, text="Log file:").grid(row=5, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_log_file, width=60).grid(row=5, column=1, columnspan=4, sticky="we", **pad)
        ttk.Button(frm, text="Browse...", command=self.choose_log_file).grid(row=5, column=5, sticky="w", **pad)

        # Row 6: Invited DB path
        ttk.Label(frm, text="Invited DB:").grid(row=6, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_invited_db, width=46).grid(row=6, column=1, columnspan=3, sticky="we", **pad)
        ttk.Button(frm, text="Browse...", command=self.choose_invited_db).grid(row=6, column=4, sticky="w", **pad)
        ttk.Button(frm, text="Reset", command=self.reset_invited_db).grid(row=6, column=5, sticky="w", **pad)

        # Row 7: Chrome settings
        sep1 = ttk.Separator(frm)
        sep1.grid(row=7, column=0, columnspan=6, sticky="we", padx=6, pady=(4, 6))
        ttk.Label(frm, text="Chrome profile:").grid(row=8, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_profile_dir, width=16).grid(row=8, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Use temp user-data-dir (separate instance)", variable=self.var_use_temp_profile).grid(row=8, column=2, columnspan=3, sticky="w", **pad)
        ttk.Button(frm, text="Launch Chrome (debug)", command=self.launch_chrome).grid(row=8, column=5, sticky="e", **pad)

        # Row 9: Credentials
        sep2 = ttk.Separator(frm)
        sep2.grid(row=9, column=0, columnspan=6, sticky="we", padx=6, pady=(4, 6))
        ttk.Label(frm, text="VOICES_EMAIL:").grid(row=10, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_email, width=28).grid(row=10, column=1, sticky="w", **pad)
        ttk.Label(frm, text="VOICES_PASSWORD:").grid(row=10, column=2, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_password, show="*", width=28).grid(row=10, column=3, sticky="w", **pad)
        ttk.Button(frm, text="Open Log", command=self.open_log).grid(row=10, column=4, sticky="e", **pad)
        ttk.Button(frm, text="Open Start URL", command=self.open_url).grid(row=10, column=5, sticky="e", **pad)

        # Row 11: Actions (simplified)
        sep3 = ttk.Separator(frm)
        sep3.grid(row=11, column=0, columnspan=6, sticky="we", padx=6, pady=(4, 6))
        ttk.Label(frm, text="Mode:").grid(row=12, column=0, sticky="e", **pad)
        mode_cb = ttk.Combobox(frm, values=["Invite to Job", "Add to Favorites", "Message Responses"], state="readonly", width=24)
        mode_cb.configure(textvariable=getattr(self, 'var_mode', tk.StringVar(value="Invite to Job")))
        mode_cb.grid(row=12, column=1, sticky="w", **pad)
        # Keep Job URL, Job ID, Speed settings on main
        ttk.Label(frm, text="Job URL:").grid(row=13, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_start_url, width=70).grid(row=13, column=1, columnspan=4, sticky="we", **pad)
        ttk.Label(frm, text="Job ID:").grid(row=14, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_job_id, width=20).grid(row=14, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Fast mode", variable=self.var_fast).grid(row=14, column=2, sticky="w", **pad)
        ttk.Label(frm, text="Slow-mo (ms):").grid(row=14, column=3, sticky="e", **pad)
        ttk.Spinbox(frm, from_=0, to=1000, increment=10, textvariable=self.var_slow_mo, width=8).grid(row=14, column=4, sticky="w", **pad)

        # Run / Stop / Settings / Save
        ttk.Button(frm, text="Run", command=self.run_inviter).grid(row=15, column=0, sticky="w", **pad)
        ttk.Button(frm, text="Stop", command=self.stop_inviter).grid(row=15, column=1, sticky="w", **pad)
        ttk.Button(frm, text="Settings…", command=self.open_settings_dialog).grid(row=15, column=2, sticky="w", **pad)
        ttk.Button(frm, text="Save Settings", command=self.save_settings).grid(row=15, column=3, sticky="w", **pad)
        ttk.Button(frm, text="Save Settings", command=self.save_settings).grid(row=12, column=2, sticky="w", **pad)

        # Log area
        self.txt = tk.Text(frm, height=18, wrap="word")
        self.txt.grid(row=16, column=0, columnspan=6, sticky="nsew", padx=6, pady=6)
        yscroll = ttk.Scrollbar(frm, orient="vertical", command=self.txt.yview)
        yscroll.grid(row=16, column=6, sticky="ns")
        self.txt.configure(yscrollcommand=yscroll.set)

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(16, weight=1)

    def choose_pause_file(self):
        p = filedialog.asksaveasfilename(title="Choose pause file path", initialfile="PAUSE")
        if p:
            self.var_pause_file.set(p)

    def choose_log_file(self):
        p = filedialog.asksaveasfilename(title="Choose log file path", initialfile="invites_log.jsonl")
        if p:
            self.var_log_file.set(p)

    def choose_invited_db(self):
        p = filedialog.asksaveasfilename(title="Choose invited DB file", initialfile="invited_ids.json")
        if p:
            self.var_invited_db.set(p)

    def reset_invited_db(self):
        try:
            path = Path(self.var_invited_db.get().strip()) if self.var_invited_db.get().strip() else (Path.cwd() / "invited_ids.json")
            if path.exists():
                path.write_text("{}", encoding="utf-8")
                self.append_log(f"[db] Reset invited DB at {path}\n")
            else:
                self.append_log(f"[db] No invited DB file to reset at {path}; creating.\n")
                path.write_text("{}", encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Reset Invited DB failed", str(e))

    def parse_port_from_cdp(self) -> int:
        try:
            u = urlparse(self.var_cdp_url.get().strip())
            if u.port:
                return int(u.port)
            # default 9222
        except Exception:
            pass
        return 9222

    def open_url(self):
        url = self.var_start_url.get().strip()
        if url:
            webbrowser.open(url)

    def launch_chrome(self):
        chrome = find_chrome_path()
        if not chrome:
            messagebox.showerror("Chrome not found", "Could not find Chrome. Please install Google Chrome or launch it manually with --remote-debugging-port.")
            return
        port = self.parse_port_from_cdp()
        args = [
            str(chrome),
            f"--remote-debugging-port={port}",
        ]
        prof = self.var_profile_dir.get().strip()
        if prof:
            args.append(f"--profile-directory={prof}")
        if self.var_use_temp_profile.get():
            try:
                tmpdir = tempfile.mkdtemp(prefix="voices-chrome-")
                args.append(f"--user-data-dir={tmpdir}")
            except Exception:
                pass
        start_url = self.var_start_url.get().strip() or DEFAULT_START_URL
        args.append(start_url)
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.append_log(f"[chrome] Launched Chrome with remote debugging on port {port}.\n")
        except Exception as e:
            messagebox.showerror("Failed to launch Chrome", str(e))

    def open_log(self):
        path = self.var_log_file.get().strip() or str(Path.cwd() / "invites_log.jsonl")
        try:
            p = Path(path)
            if not p.exists():
                # Create empty file so OS can open it in default editor
                p.write_text("", encoding="utf-8")
            if os.name == 'nt':
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(p)])
            else:
                subprocess.Popen(['xdg-open', str(p)])
        except Exception as e:
            messagebox.showerror("Open Log failed", str(e))

    def test_cdp(self):
        def _worker():
            try:
                from playwright.sync_api import sync_playwright
            except Exception as e:
                self.append_log(f"[cdp] Playwright not available: {e}\n")
                return
            url = self.var_cdp_url.get().strip() or DEFAULT_CDP_URL
            self.append_log(f"[cdp] Testing CDP at {url}\n")
            try:
                with sync_playwright() as p:
                    browser = p.chromium.connect_over_cdp(url)
                    ctxs = browser.contexts
                    info_lines = [f"[cdp] Connected. Contexts: {len(ctxs)}\n"]
                    for i, ctx in enumerate(ctxs):
                        try:
                            pages = ctx.pages
                            info_lines.append(f"[cdp]  Context {i}: pages={len(pages)}\n")
                            for j, pg in enumerate(pages):
                                try:
                                    info_lines.append(f"[cdp]    Page {j}: {pg.title()} | {pg.url}\n")
                                except Exception:
                                    info_lines.append(f"[cdp]    Page {j}: (title unavailable) | {pg.url}\n")
                        except Exception:
                            info_lines.append(f"[cdp]  Context {i}: (error listing pages)\n")
                    for ln in info_lines:
                        self.append_log(ln)
                    try:
                        browser.close()
                    except Exception:
                        pass
            except Exception as e:
                self.append_log(f"[cdp] Failed to connect: {e}\n")

        threading.Thread(target=_worker, daemon=True).start()

    def run_inviter(self):
        # Build environment
        env = os.environ.copy()
        start_url = self.var_start_url.get().strip()
        if start_url:
            env["VOICES_START_URL"] = start_url
        cdp_url = self.var_cdp_url.get().strip() or DEFAULT_CDP_URL
        env["CHROME_CDP_URL"] = cdp_url
        if self.var_debug.get():
            env["VOICES_DEBUG"] = "1"
        else:
            env.pop("VOICES_DEBUG", None)
        if self.var_pause_file.get().strip():
            env["VOICES_PAUSE_FILE"] = self.var_pause_file.get().strip()
        # Auto-enable structured logs when debugging or dry-run
        log_path = (self.var_log_file.get() or "").strip()
        if log_path:
            env["VOICES_LOG_FILE"] = log_path
        invited_db = (self.var_invited_db.get() or "").strip()
        if invited_db:
            env["VOICES_INVITED_DB"] = invited_db

        # Optional credentials
        if self.var_email.get().strip():
            env["VOICES_EMAIL"] = self.var_email.get().strip()
        if self.var_password.get().strip():
            env["VOICES_PASSWORD"] = self.var_password.get().strip()

        # Build args
        python = sys.executable or "python"
        args: list[str] = [python, str(self.script_path)]

        if self.var_attach_cdp.get():
            if self.var_require_cdp.get():
                args.append("--require-cdp")
        else:
            args.append("--no-cdp")

        if self.var_manual_login.get():
            args.append("--manual-login")

        if self.var_fast.get():
            args.append("--fast")
        else:
            args.extend(["--slow-mo", str(int(self.var_slow_mo.get()))])

        if self.var_scroll_passes.get() >= 0:
            args.extend(["--scroll-passes", str(int(self.var_scroll_passes.get()))])

        job_id_str = self.var_job_id.get().strip()
        job_title_str = self.var_job_title.get().strip()
        # Always pass job filters if provided
        if job_id_str:
            args.extend(["--job-id", job_id_str])
        if job_title_str:
            args.extend(["--job-title", job_title_str])

        if self.var_headless.get():
            args.append("--headless")

        if self.var_dry_run.get():
            args.append("--dry-run")

        if log_path:
            args.extend(["--log-file", log_path])
        if invited_db:
            args.extend(["--invited-db", invited_db])

        # Favorites mode
        if self.var_use_favorites.get():
            args.append("--use-favorites")
            env["VOICES_USE_FAVORITES"] = "1"
        # Removed: prefer-create (we never create a new job via the modal)
        fav_title = (self.var_fav_list_title.get() or "").strip()
        if fav_title:
            args.extend(["--favorites-list", fav_title])
            env["VOICES_FAVORITES_LIST"] = fav_title

        # Always pass the explicit start URL too for clarity
        if start_url:
            args.extend(["--start-url", start_url])

        try:
            self.proc.start(args=args, cwd=self.script_path.parent, env=env)
        except Exception as e:
            messagebox.showerror("Run failed", str(e))

    def stop_inviter(self):
        self.proc.stop()

    def append_log(self, text: str):
        self.txt.insert(tk.END, text)
        self.txt.see(tk.END)

    def on_proc_exit(self, code: int | None):
        self.append_log(f"\n[exit] Process ended with code {code}.\n")

    def open_settings_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Settings")
        dlg.geometry("900x600")
        pad = {"padx": 6, "pady": 4}
        row = 0

        # CDP/Chrome & Execution
        ttk.Label(dlg, text="CDP URL:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(dlg, textvariable=self.var_cdp_url, width=36).grid(row=row, column=1, sticky="w", **pad)
        ttk.Checkbutton(dlg, text="Attach to running Chrome", variable=self.var_attach_cdp).grid(row=row, column=2, sticky="w", **pad)
        ttk.Checkbutton(dlg, text="Require CDP", variable=self.var_require_cdp).grid(row=row, column=3, sticky="w", **pad)
        ttk.Checkbutton(dlg, text="Manual login", variable=self.var_manual_login).grid(row=row, column=4, sticky="w", **pad)
        ttk.Checkbutton(dlg, text="Headless", variable=self.var_headless).grid(row=row, column=5, sticky="w", **pad)
        ttk.Button(dlg, text="Test CDP", command=self.test_cdp).grid(row=row, column=6, sticky="w", **pad)
        row += 1

        ttk.Label(dlg, text="Scroll passes:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Spinbox(dlg, from_=0, to=10, increment=1, textvariable=self.var_scroll_passes, width=6).grid(row=row, column=1, sticky="w", **pad)
        ttk.Checkbutton(dlg, text="Debug logs", variable=self.var_debug).grid(row=row, column=2, sticky="w", **pad)
        ttk.Checkbutton(dlg, text="Dry-run (invite mode)", variable=self.var_dry_run).grid(row=row, column=3, sticky="w", **pad)
        row += 1

        # Favorites
        ttk.Label(dlg, text="Favorites list title:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(dlg, textvariable=self.var_fav_list_title, width=30).grid(row=row, column=1, sticky="w", **pad)
        row += 1

        # Messaging
        ttk.Label(dlg, text="Message text:").grid(row=row, column=0, sticky="ne", **pad)
        txt = tk.Text(dlg, height=4, width=60, wrap="word")
        txt.grid(row=row, column=1, columnspan=4, sticky="we", **pad)
        txt.insert("1.0", self.var_message_text.get())
        def _sync_msg(*_):
            self.var_message_text.set(txt.get("1.0", "end").strip())
        txt.bind("<FocusOut>", lambda e: _sync_msg())
        row += 1

        # Paths
        ttk.Label(dlg, text="Pause file:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(dlg, textvariable=self.var_pause_file, width=50).grid(row=row, column=1, columnspan=3, sticky="we", **pad)
        ttk.Button(dlg, text="Browse…", command=self.choose_pause_file).grid(row=row, column=4, sticky="w", **pad)
        row += 1

        ttk.Label(dlg, text="Log file:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(dlg, textvariable=self.var_log_file, width=50).grid(row=row, column=1, columnspan=3, sticky="we", **pad)
        ttk.Button(dlg, text="Browse...", command=self.choose_log_file).grid(row=row, column=4, sticky="w", **pad)
        row += 1

        ttk.Label(dlg, text="Invited DB:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(dlg, textvariable=self.var_invited_db, width=40).grid(row=row, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(dlg, text="Browse...", command=self.choose_invited_db).grid(row=row, column=3, sticky="w", **pad)
        ttk.Button(dlg, text="Reset", command=self.reset_invited_db).grid(row=row, column=4, sticky="w", **pad)
        row += 1

        # Chrome profile
        ttk.Label(dlg, text="Chrome profile:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(dlg, textvariable=self.var_profile_dir, width=16).grid(row=row, column=1, sticky="w", **pad)
        ttk.Checkbutton(dlg, text="Use temp user-data-dir", variable=self.var_use_temp_profile).grid(row=row, column=2, columnspan=2, sticky="w", **pad)
        ttk.Button(dlg, text="Launch Chrome (debug)", command=self.launch_chrome).grid(row=row, column=4, sticky="e", **pad)
        row += 1

        # Credentials
        ttk.Label(dlg, text="VOICES_EMAIL:").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(dlg, textvariable=self.var_email, width=28).grid(row=row, column=1, sticky="w", **pad)
        ttk.Label(dlg, text="VOICES_PASSWORD:").grid(row=row, column=2, sticky="e", **pad)
        ttk.Entry(dlg, textvariable=self.var_password, show="*", width=28).grid(row=row, column=3, sticky="w", **pad)
        ttk.Button(dlg, text="Open Log", command=self.open_log).grid(row=row, column=4, sticky="e", **pad)
        ttk.Button(dlg, text="Open URL", command=self.open_url).grid(row=row, column=5, sticky="e", **pad)
        row += 1

        ttk.Button(dlg, text="Close", command=dlg.destroy).grid(row=row, column=0, sticky="w", **pad)

    # ---------------- Settings persistence ----------------
    def _collect_settings(self) -> dict:
        return {
            "mode": self.var_mode.get(),
            "start_url": self.var_start_url.get().strip(),
            "cdp_url": self.var_cdp_url.get().strip(),
            "attach_cdp": bool(self.var_attach_cdp.get()),
            "require_cdp": bool(self.var_require_cdp.get()),
            "manual_login": bool(self.var_manual_login.get()),
            "headless": bool(self.var_headless.get()),
            "fast": bool(self.var_fast.get()),
            "slow_mo": int(self.var_slow_mo.get()),
            "scroll_passes": int(self.var_scroll_passes.get()),
            "debug": bool(self.var_debug.get()),
            "dry_run": bool(self.var_dry_run.get()),
            "pause_file": self.var_pause_file.get().strip(),
            "log_file": self.var_log_file.get().strip(),
            "invited_db": self.var_invited_db.get().strip(),
            "job_id": self.var_job_id.get().strip(),
            "job_title": self.var_job_title.get().strip(),
            "message_text": self.var_message_text.get().strip(),
            "use_favorites": bool(self.var_use_favorites.get()),
            "favorites_list": self.var_fav_list_title.get().strip(),
            "profile_dir": self.var_profile_dir.get().strip(),
            "use_temp_profile": bool(self.var_use_temp_profile.get()),
            # Warning: stored in plain text
            "email": self.var_email.get().strip(),
            "password": self.var_password.get().strip(),
        }

    def _apply_settings(self, cfg: dict):
        def _set(var, key, cast=None):
            if key in cfg and cfg[key] is not None:
                val = cfg[key]
                if cast is not None:
                    try:
                        val = cast(val)
                    except Exception:
                        return
                var.set(val)

        _set(self.var_mode, "mode", str)
        _set(self.var_start_url, "start_url", str)
        _set(self.var_cdp_url, "cdp_url", str)
        _set(self.var_attach_cdp, "attach_cdp", bool)
        _set(self.var_require_cdp, "require_cdp", bool)
        _set(self.var_manual_login, "manual_login", bool)
        _set(self.var_headless, "headless", bool)
        _set(self.var_fast, "fast", bool)
        _set(self.var_slow_mo, "slow_mo", int)
        _set(self.var_scroll_passes, "scroll_passes", int)
        _set(self.var_debug, "debug", bool)
        _set(self.var_dry_run, "dry_run", bool)
        _set(self.var_pause_file, "pause_file", str)
        _set(self.var_log_file, "log_file", str)
        _set(self.var_invited_db, "invited_db", str)
        _set(self.var_job_id, "job_id", str)
        _set(self.var_job_title, "job_title", str)
        _set(self.var_message_text, "message_text", str)
        _set(self.var_use_favorites, "use_favorites", bool)
        _set(self.var_fav_list_title, "favorites_list", str)
        _set(self.var_profile_dir, "profile_dir", str)
        _set(self.var_use_temp_profile, "use_temp_profile", bool)
        _set(self.var_email, "email", str)
        _set(self.var_password, "password", str)

    def save_settings(self):
        try:
            cfg = self._collect_settings()
            self.settings_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            self.append_log(f"[settings] Saved to {self.settings_path}\n")
            if cfg.get("password"):
                self.append_log("[settings] Warning: password saved in plain text.\n")
        except Exception as e:
            messagebox.showerror("Save Settings failed", str(e))

    def load_settings(self):
        try:
            if not self.settings_path.exists():
                return
            cfg = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                return
            self._apply_settings(cfg)
            self.append_log(f"[settings] Loaded from {self.settings_path}\n")
        except Exception as e:
            messagebox.showerror("Load Settings failed", str(e))


if __name__ == "__main__":
    app = App()
    app.mainloop()
