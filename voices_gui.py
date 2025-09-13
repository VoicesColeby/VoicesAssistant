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
from tkinter import ttk, filedialog, messagebox, scrolledtext


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

        # Consistent theming
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Status text
        self.status_var = tk.StringVar(value="Ready")

        self.script_path = Path(__file__).parent / "invite_all.py"
        if not self.script_path.exists():
            messagebox.showerror("Missing script", f"Could not find invite_all.py next to {Path(__file__).name}")

        self.proc = ProcessRunner(self.append_log, self.on_proc_exit)
        # Default settings path next to this script
        self.settings_path = Path(__file__).parent / DEFAULT_SETTINGS_FILE

        # Variables
        self.var_mode = tk.StringVar(value="Invite to Job")
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
        self.var_message_text = tk.StringVar(value="can you please complete this survey for your rate")
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

        # Row 0: Mode selection
        ttk.Label(frm, text="Mode:").grid(row=0, column=0, sticky="e", **pad)
        mode_cb = ttk.Combobox(frm, values=["Invite to Job", "Add to Favorites", "Message Responses"], state="readonly", width=24)
        mode_cb.configure(textvariable=self.var_mode)
        mode_cb.grid(row=0, column=1, sticky="w", **pad)

        # Row 1: Job/Search URL
        ttk.Label(frm, text="Job/Search URL:").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_start_url, width=90).grid(row=1, column=1, columnspan=4, sticky="we", **pad)

        # Row 2: Job ID and Speed
        ttk.Label(frm, text="Job ID:").grid(row=2, column=0, sticky="e", **pad)
        ttk.Entry(frm, textvariable=self.var_job_id, width=18).grid(row=2, column=1, sticky="w", **pad)
        ttk.Checkbutton(frm, text="Fast mode", variable=self.var_fast).grid(row=2, column=2, sticky="w", **pad)
        ttk.Label(frm, text="Slow-mo (ms):").grid(row=2, column=3, sticky="e", **pad)
        ttk.Spinbox(frm, from_=0, to=1000, increment=10, textvariable=self.var_slow_mo, width=8).grid(row=2, column=4, sticky="w", **pad)

        # Row 3: Message box
        ttk.Label(frm, text="Message:").grid(row=3, column=0, sticky="ne", **pad)
        self.msg_text = tk.Text(frm, height=4, width=90, wrap="word")
        self.msg_text.grid(row=3, column=1, columnspan=4, sticky="we", **pad)
        self.msg_text.insert("1.0", self.var_message_text.get())
        def _sync_msg(*_):
            self.var_message_text.set(self.msg_text.get("1.0", "end").strip())
        self.msg_text.bind("<FocusOut>", lambda e: _sync_msg())

        # Row 4: Actions frame
        actions = ttk.LabelFrame(frm, text="Actions")
        actions.grid(row=4, column=0, columnspan=6, sticky="ew", padx=6, pady=4)
        self.btn_run = ttk.Button(actions, text="Run", command=self.run_inviter)
        self.btn_run.pack(side=tk.LEFT, **pad)
        self.btn_stop = ttk.Button(actions, text="Stop", command=self.stop_inviter, state="disabled")
        self.btn_stop.pack(side=tk.LEFT, **pad)
        ttk.Button(actions, text="Settings…", command=self.open_settings_dialog).pack(side=tk.LEFT, **pad)
        ttk.Button(actions, text="Save Settings", command=self.save_settings).pack(side=tk.LEFT, **pad)
        ttk.Button(actions, text="Open Log", command=self.open_log).pack(side=tk.LEFT, **pad)

        # Row 5: Log frame
        log_frame = ttk.LabelFrame(frm, text="Log")
        log_frame.grid(row=5, column=0, columnspan=6, sticky="nsew", padx=6, pady=4)
        self.txt = scrolledtext.ScrolledText(log_frame, height=18, wrap="word")
        self.txt.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # Context menu for log
        self.txt_menu = tk.Menu(self, tearoff=False)
        self.txt_menu.add_command(label="Copy", command=lambda: self.txt.event_generate("<<Copy>>"))
        self.txt_menu.add_command(label="Clear", command=lambda: self.txt.delete("1.0", tk.END))
        self.txt.bind("<Button-3>", self._show_text_menu)

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(5, weight=1)

        # Status bar
        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.progress = ttk.Progressbar(status_frame, mode="indeterminate")
        self.progress.pack(side=tk.LEFT, padx=6, pady=2)
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

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
        if self.var_debug.get():
            env["VOICES_DEBUG"] = "1"
        else:
            env.pop("VOICES_DEBUG", None)
        if self.var_pause_file.get().strip():
            env["VOICES_PAUSE_FILE"] = self.var_pause_file.get().strip()
        # Structured logs / invited DB
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

        python = sys.executable or "python"
        mode = (getattr(self, 'var_mode', tk.StringVar(value='Invite to Job')).get() or "").strip()

        # Build args by mode
        if mode == "Add to Favorites":
            script = Path(__file__).parent / "favorites_add.py"
            args = [python, str(script), "--url", start_url]
            fav_title = (self.var_fav_list_title.get() or "").strip()
            if fav_title:
                args.extend(["--list", fav_title])
            # Speed
            args.extend(["--slow-mo", str(int(self.var_slow_mo.get()))])
            if self.var_headless.get():
                args.append("--headless")

        elif mode == "Message Responses":
            script = Path(__file__).parent / "message_responses.py"
            args = [python, str(script), "--url", start_url]
            msg_text = (getattr(self, 'var_message_text', tk.StringVar(value='')).get() or "").strip()
            if msg_text:
                args.extend(["--text", msg_text])
            # Speed
            args.extend(["--slow-mo", str(int(self.var_slow_mo.get()))])
            if self.var_headless.get():
                args.append("--headless")

        else:  # Invite to Job (default) -> use invite_simple.py
            script = Path(__file__).parent / "invite_simple.py"
            args = [python, str(script)]
            # Filters
            job_id_str = self.var_job_id.get().strip()
            if job_id_str:
                args.extend(["--job-id", job_id_str])
            if start_url:
                args.extend(["--start-url", start_url])
            # Speed
            args.extend(["--slow-mo", str(int(self.var_slow_mo.get()))])
            if self.var_headless.get():
                args.append("--headless")

        try:
            self.proc.start(args=args, cwd=self.script_path.parent, env=env)
            self.btn_run.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.progress.start(10)
            self.status_var.set("Running...")
        except Exception as e:
            messagebox.showerror("Run failed", str(e))

    def stop_inviter(self):
        self.proc.stop()
        self.btn_stop.config(state="disabled")
        self.status_var.set("Stopping...")

    def append_log(self, text: str):
        self.txt.insert(tk.END, text)
        self.txt.see(tk.END)

    def on_proc_exit(self, code: int | None):
        self.append_log(f"\n[exit] Process ended with code {code}.\n")
        self.btn_run.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.progress.stop()
        self.status_var.set(f"Exit code {code}")

    def _show_text_menu(self, event):
        try:
            self.txt_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.txt_menu.grab_release()

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
        ttk.Button(dlg, text="Browseâ€¦", command=self.choose_pause_file).grid(row=row, column=4, sticky="w", **pad)
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
