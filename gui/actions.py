"""Automation logic and control-flow mixin for the GUI."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from typing import Dict, Optional

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox


ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


class AutomationMixin:
    """Encapsulate process management and console handling."""

    # --- Speed control ---------------------------------------------------
    @property
    def speed_file_path(self) -> str:
        base_dir = getattr(self, "base_dir", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "speed.cfg")

    def _write_speed_file(self, value: Optional[float] = None) -> None:
        try:
            if value is not None:
                speed_val = float(value)
            else:
                speed_val = float(getattr(self, "speed_var", tk.DoubleVar(value=5.0)).get())
        except Exception:
            speed_val = 5.0

        try:
            with open(self.speed_file_path, "w", encoding="utf-8") as fh:
                fh.write(f"{speed_val:.2f}")
        except Exception:
            pass

    # --- Status helpers --------------------------------------------------
    def update_status(self, action: str, status: str) -> None:
        try:
            prefix = self.action_labels.get(action, action.title())  # type: ignore[attr-defined]
            var = self.status_vars.get(action)  # type: ignore[attr-defined]
            if var is not None:
                var.set(f"{prefix}: {status}")
        except Exception:
            pass

    # --- Automation ------------------------------------------------------
    def run_automation(self) -> None:
        if not self.selected_action:  # type: ignore[attr-defined]
            messagebox.showerror("Error", "Please select an action first.")
            return

        action = self.selected_action

        if action == "message":
            try:
                msg_widget = self.input_fields.get("message")  # type: ignore[attr-defined]
                message_text = (
                    msg_widget.get("1.0", tk.END).strip()
                    if (msg_widget and hasattr(msg_widget, "get"))
                    else ""
                )
            except Exception:
                message_text = ""
            if not message_text:
                messagebox.showwarning(
                    "Missing Message", "Please enter a message before continuing."
                )
                self.update_status(action, "Awaiting message")
                return
        else:
            message_text = ""

        self.console_text.config(state=tk.NORMAL)  # type: ignore[attr-defined]
        self.console_text.delete(1.0, tk.END)
        self.console_text.config(state=tk.DISABLED)
        self._reset_progressbar()

        context: Dict[str, str] = {}
        if action == "message":
            context["message"] = message_text
        elif action == "import_invites":
            context["csv_path"] = getattr(self, "_import_csv_path", "")
            context["job_number"] = getattr(self, "_import_job_number", "")

        self.current_action = action  # type: ignore[attr-defined]
        overrides = getattr(self, "_status_overrides", None)
        if overrides is not None:
            overrides.pop(action, None)
        self.update_status(action, "Running...")

        thread = threading.Thread(
            target=self._execute_script_thread,
            args=(action, context),
            daemon=True,
        )
        thread.start()
        self.apply_controls_state(running=True)

    def _ensure_psutil(self):  # pragma: no cover - runtime installation prompt
        try:
            import psutil  # type: ignore

            return psutil
        except Exception:
            pass

        exe = sys.executable
        if getattr(sys, "frozen", False):
            messagebox.showwarning(
                "Pause Unavailable",
                (
                    "Pausing requires the 'psutil' package, which isn't bundled in this build.\n\n"
                    "Please run from source with Python and install psutil, or rebuild including psutil."
                ),
            )
            return None

        try:
            if messagebox.askyesno(
                "Install psutil?",
                (
                    "Pausing requires the 'psutil' package.\n\n"
                    f"Install now for this Python?\n{exe}\n\n"
                    "You can also install manually with:\n"
                    f"\n\t\"{exe}\" -m pip install psutil\n"
                    "or\n\tpy -m pip install psutil"
                ),
            ):
                try:
                    subprocess.check_call([exe, "-m", "pip", "install", "psutil"])
                    import psutil  # type: ignore

                    return psutil
                except Exception as exc:  # pragma: no cover - UI feedback only
                    messagebox.showerror(
                        "Install Failed",
                        f"Could not install psutil using:\n{exe} -m pip install psutil\n\nError: {exc}",
                    )
                    return None
            else:
                messagebox.showwarning(
                    "Pause Unavailable",
                    (
                        "Pausing requires the 'psutil' package.\n\n"
                        f"Install for this Python:\n\"{exe}\" -m pip install psutil\n"
                        "Or: py -m pip install psutil"
                    ),
                )
                return None
        except Exception:
            messagebox.showwarning(
                "Pause Unavailable",
                (
                    "Pausing requires the 'psutil' package. Install with:\n"
                    f"\"{exe}\" -m pip install psutil\n"
                    "Or: py -m pip install psutil"
                ),
            )
            return None

    def _execute_script_thread(self, action: str, context: Dict[str, str]) -> None:
        status_text = "Completed"
        script_path = ""
        try:
            env = os.environ.copy()

            base_dir = getattr(self, "base_dir", os.path.dirname(os.path.abspath(__file__)))
            if action == "invite":
                script_path = os.path.join(base_dir, "invite_to_job.py")
            elif action == "favorites":
                script_path = os.path.join(base_dir, "add_to_favorites.py")
            elif action == "message":
                script_path = os.path.join(base_dir, "message_talent.py")
                env["MESSAGE"] = context.get("message", "")
            elif action == "import_invites":
                script_path = os.path.join(base_dir, "import_invites.py")
                csv_path = context.get("csv_path", "") or ""
                job_val = context.get("job_number", "") or ""
                job_digits = re.sub(r"\D", "", job_val)
                if not csv_path or not os.path.exists(csv_path):
                    messagebox.showwarning(
                        "CSV Required",
                        "Please select a CSV file with a 'username' column.",
                    )
                    status_text = "CSV file required"
                    return
                if not job_digits:
                    messagebox.showwarning(
                        "Job # Required",
                        "Enter a numeric Job # to invite talents to (e.g., 805775)",
                    )
                    status_text = "Job number required"
                    return
                env["CSV_PATH"] = csv_path
                env["JOB_QUERY"] = job_digits

            if "DEBUG_URL" not in env or not env["DEBUG_URL"]:
                env["DEBUG_URL"] = "http://127.0.0.1:9222"

            self.update_console(f"[i] Starting script: {os.path.basename(script_path)}\n")
            self.update_console(
                "[i] Tip: Click 'Open Voices' to sign in, then click 'Start Helper' to begin.\n"
            )

            if action == "message":
                self.update_console(f"[i] MESSAGE: {env.get('MESSAGE')}\n")
            if action == "invite":
                env["SKIP_FIRST_TALENT"] = "1"
                self.update_console("[i] Invite flow: will skip the first talent (assumed manual).\n")
            if action == "import_invites":
                self.update_console(f"[i] CSV: {env.get('CSV_PATH')}\n")
                self.update_console(f"[i] Job #: {env.get('JOB_QUERY')}\n")

            if action == "import_invites":
                env["USE_CURRENT_PAGE"] = "0"
                self.update_console("[i] Import flow: will navigate to each profile from CSV.\n")
            else:
                env["USE_CURRENT_PAGE"] = "1"
                self.update_console("[i] Using current browser tab; no navigation.\n")

            try:
                speed = float(getattr(self, "speed_var", tk.DoubleVar(value=5.0)).get())
                speed = max(1.0, min(5.0, speed))
            except Exception:
                speed = 5.0
            env["SPEED"] = f"{speed:.2f}"
            try:
                self._write_speed_file(speed)
                env["SPEED_FILE"] = self.speed_file_path
            except Exception:
                pass

            creationflags = 0
            try:
                creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            except Exception:
                pass

            with self.process_lock:  # type: ignore[attr-defined]
                env["PYTHONUNBUFFERED"] = "1"
                env["PYTHONIOENCODING"] = "utf-8"
                self.process = subprocess.Popen(  # type: ignore[attr-defined]
                    [sys.executable, script_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    creationflags=creationflags,
                    cwd=base_dir,
                )
            process = self.process  # type: ignore[attr-defined]

            for line in process.stdout:  # type: ignore[union-attr]
                self.update_console(line)

            process.wait()
            rc = process.returncode
            self.update_console("[i] Script finished.\n")
            if rc == 0:
                status_text = "Completed successfully"
                try:
                    messagebox.showinfo("Finished", "Completed successfully.")
                except Exception:
                    pass
            else:
                status_text = f"Finished with exit code: {rc}"
                try:
                    messagebox.showinfo("Finished", f"Completed with exit code: {rc}")
                except Exception:
                    pass
        except FileNotFoundError:
            status_text = "Script missing"
            self.update_console(
                f"[x] Error: Could not find the script file '{script_path}'. Please make sure it is in the same directory as this application.\n"
            )
        except Exception as exc:
            status_text = "Unexpected error"
            self.update_console(f"[x] An unexpected error occurred: {exc}\n")
        finally:
            with self.process_lock:  # type: ignore[attr-defined]
                self.process = None  # type: ignore[attr-defined]
                self.is_paused = False  # type: ignore[attr-defined]
            self.apply_controls_state(running=False)
            self._reset_progressbar()
            overrides = getattr(self, "_status_overrides", None)
            if overrides and action in overrides:
                status_text = overrides.pop(action)
            self.update_status(action, status_text)
            self.current_action = None  # type: ignore[attr-defined]

    # --- Browser helpers -------------------------------------------------
    def get_debug_port(self) -> int:
        val = "http://127.0.0.1:9222"
        try:
            url = urllib.parse.urlparse(val)
            if url.port:
                return int(url.port)
        except Exception:
            pass
        return 9222

    def find_browser_exe(self) -> str:
        candidates = []
        pf = os.environ.get("PROGRAMFILES", r"C:\\Program Files")
        pfx86 = os.environ.get("PROGRAMFILES(X86)", r"C:\\Program Files (x86)")
        local = os.environ.get(
            "LOCALAPPDATA", r"C:\\Users\\%USERNAME%\\AppData\\Local"
        )
        candidates += [
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pfx86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pfx86, "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
        for path in candidates:
            try:
                if os.path.exists(path):
                    return path
            except Exception:
                continue
        return ""

    def start_browser(self):
        start_widget = self.input_fields.get("url")  # type: ignore[attr-defined]
        url = start_widget.get().strip() if (start_widget and hasattr(start_widget, "get")) else ""
        return self.start_browser_with_url(url)

    def start_browser_with_url(self, url: str = ""):
        exe = self.find_browser_exe()
        if not exe:
            messagebox.showwarning(
                "Browser Not Found",
                "Could not locate Chrome/Edge executables. Falling back to default browser open.",
            )
            self.open_regular_browser(url)
            return

        base_dir = getattr(self, "base_dir", os.path.dirname(os.path.abspath(__file__)))
        profile_dir = os.path.join(base_dir, "voices_debug_profile")
        os.makedirs(profile_dir, exist_ok=True)
        port = self.get_debug_port()
        open_url = url if url else "about:blank"
        args = [
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            open_url,
        ]
        try:
            creationflags = 0
            try:
                creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            except Exception:
                pass
            self.browser_process = subprocess.Popen(  # type: ignore[attr-defined]
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self.update_console(
                f"[i] Launched debug browser on port {port}. Log in, then click Start.\n"
            )
        except Exception as exc:
            self.update_console(f"[x] Failed to launch browser: {exc}\n")

    def open_regular_browser(self, url: str = ""):
        try:
            open_url = url if url else "about:blank"
            webbrowser.open(open_url)
            self.update_console(f"[i] Opened in regular browser: {open_url}\n")
        except Exception as exc:
            self.update_console(f"[x] Failed to open regular browser: {exc}\n")

    def open_browser(self):
        default_url = "https://www.voices.com/"
        self.start_browser_with_url(default_url)

    # --- Console handling ------------------------------------------------
    def _supports_unicode(self) -> bool:
        if getattr(self, "_unicode_supported", None) is None:
            try:
                fnt = tkfont.nametofont(self.console_text.cget("font"))  # type: ignore[attr-defined]
                tests = ("✖", "✓", "⚠", "•")
                self._unicode_supported = all(fnt.measure(ch) > 0 for ch in tests)
            except Exception:
                self._unicode_supported = False
        return self._unicode_supported

    def _format_console_line(self, text: str) -> str:
        try:
            s = str(text)
        except Exception:
            s = "" if text is None else f"{text}"

        s = ANSI_RE.sub("", s)
        s = "".join(ch for ch in s if ch == "\n" or ch == "\t" or ord(ch) >= 32)
        s = re.sub(r"(?i)\bProcessing talent\s+(\d+)\s*/\s*(\d+)\b", r"Processing talent \1 of \2", s)
        s = s.replace("▶", "Start").replace("⏸", "Pause").replace("⏹", "Stop")

        use_unicode = self._supports_unicode()
        if s.lstrip().startswith("[x]"):
            s = s.replace("[x]", "✖" if use_unicode else "ERR", 1)
        elif s.lstrip().startswith("[i]"):
            if re.search(r"(?i)\b(saved|finished|opened|launched|canceled|paused|resumed)\b", s):
                s = s.replace("[i]", "✓" if use_unicode else "OK", 1)
            else:
                s = s.replace("[i]", "•" if use_unicode else "INFO", 1)
        elif s.lstrip().startswith("[!]"):
            s = s.replace("[!]", "⚠" if use_unicode else "WARN", 1)

        if not s.endswith("\n"):
            s += "\n"
        return s

    def update_console(self, text: str) -> None:
        cleaned = self._format_console_line(text)
        try:
            match = re.search(r"Processing talent (\d+) of (\d+)", cleaned)
            if match:
                cur = int(match.group(1))
                total = int(match.group(2))
                self.progress_bar["maximum"] = total  # type: ignore[attr-defined]
                self.progress_bar["value"] = cur  # type: ignore[attr-defined]
        except Exception:
            pass

        self.console_text.config(state=tk.NORMAL)  # type: ignore[attr-defined]
        self.console_text.insert(tk.END, cleaned)
        self.console_text.see(tk.END)
        self.console_text.config(state=tk.DISABLED)

    def _reset_progressbar(self) -> None:
        try:
            self.progress_bar["value"] = 0  # type: ignore[attr-defined]
            self.progress_bar["maximum"] = 1  # type: ignore[attr-defined]
        except Exception:
            pass

    # --- Controls --------------------------------------------------------
    def apply_controls_state(self, running: bool) -> None:
        if not running:
            try:
                self.play_pause_button.config(state=tk.NORMAL, text="▶ Start")  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.pause_button.config(state=tk.DISABLED, text="⏸ Pause")  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                self.cancel_button.config(state=tk.DISABLED)  # type: ignore[attr-defined]
            except Exception:
                pass
            self.is_paused = False  # type: ignore[attr-defined]
            return

        if self.is_paused:  # type: ignore[attr-defined]
            try:
                self.play_pause_button.config(state=tk.NORMAL, text="▶ Resume")
            except Exception:
                pass
            try:
                self.pause_button.config(state=tk.DISABLED, text="⏸ Pause")
            except Exception:
                pass
            try:
                self.cancel_button.config(state=tk.NORMAL)
            except Exception:
                pass
            return

        try:
            self.play_pause_button.config(state=tk.DISABLED, text="▶ Start")
        except Exception:
            pass
        try:
            self.pause_button.config(state=tk.NORMAL, text="⏸ Pause")
        except Exception:
            pass
        try:
            self.cancel_button.config(state=tk.NORMAL)
        except Exception:
            pass

    def set_controls_state(self, running: bool) -> None:
        if running:
            self.play_pause_button.config(state=tk.DISABLED, text="▶ Start")  # type: ignore[attr-defined]
            self.pause_button.config(state=tk.NORMAL, text="⏸ Pause")  # type: ignore[attr-defined]
            self.cancel_button.config(state=tk.NORMAL)  # type: ignore[attr-defined]
        else:
            self.play_pause_button.config(state=tk.NORMAL, text="▶ Start")  # type: ignore[attr-defined]
            self.pause_button.config(state=tk.DISABLED, text="⏸ Pause")  # type: ignore[attr-defined]
            self.cancel_button.config(state=tk.DISABLED)  # type: ignore[attr-defined]
            self.is_paused = False  # type: ignore[attr-defined]

    def play_pause(self) -> None:
        with self.process_lock:  # type: ignore[attr-defined]
            proc = self.process
        if not proc or proc.poll() is not None:
            self.run_automation()
            try:
                self.apply_controls_state(running=True)
            except Exception:
                pass
        else:
            self.toggle_pause()

    def _walk_children(self, psutil_proc):  # pragma: no cover - psutil specific
        try:
            for child in psutil_proc.children(recursive=True):
                yield child
        except Exception:
            return

    def toggle_pause(self) -> None:
        with self.process_lock:  # type: ignore[attr-defined]
            proc = self.process
        if not proc or proc.poll() is not None:
            return
        psutil = self._ensure_psutil()
        if psutil is None:
            return

        p = psutil.Process(proc.pid)
        try:
            if not self.is_paused:  # type: ignore[attr-defined]
                for ch in self._walk_children(p):
                    ch.suspend()
                p.suspend()
                self.is_paused = True  # type: ignore[attr-defined]
                self.update_console("[i] Paused.\n")
                if getattr(self, "current_action", None):
                    self.update_status(self.current_action, "Paused")  # type: ignore[arg-type]
            else:
                for ch in self._walk_children(p):
                    ch.resume()
                p.resume()
                self.is_paused = False  # type: ignore[attr-defined]
                self.update_console("[i] Resumed.\n")
                if getattr(self, "current_action", None):
                    self.update_status(self.current_action, "Running...")  # type: ignore[arg-type]
        except Exception as exc:
            self.update_console(f"[x] Pause/Resume error: {exc}\n")
        self.apply_controls_state(running=True)

    def cancel_run(self) -> None:
        with self.process_lock:  # type: ignore[attr-defined]
            proc = self.process
        if not proc or proc.poll() is not None:
            return
        action = getattr(self, "current_action", None)
        try:
            psutil = self._ensure_psutil()
            if psutil is None:
                raise RuntimeError("psutil not available")
            p = psutil.Process(proc.pid)
            for ch in self._walk_children(p):
                try:
                    ch.terminate()
                except Exception:
                    pass
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                for ch in self._walk_children(p):
                    try:
                        ch.kill()
                    except Exception:
                        pass
                p.kill()
            self.update_console("[i] Canceled run.\n")
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
            self.update_console("[i] Canceled run (basic).\n")
        finally:
            if action:
                overrides = getattr(self, "_status_overrides", None)
                if overrides is None:
                    overrides = {}
                    self._status_overrides = overrides  # type: ignore[attr-defined]
                overrides[action] = "Canceled"
                self.update_status(action, "Canceled")
            self.apply_controls_state(running=False)

    def _try_close_browser(self) -> None:
        bp = getattr(self, "browser_process", None)
        if not bp:
            return
        try:
            bp.terminate()
        except Exception:
            pass
        try:
            bp.wait(timeout=3)
        except Exception:
            try:
                import psutil  # type: ignore

                p = psutil.Process(bp.pid)
                for ch in p.children(recursive=True):
                    try:
                        ch.kill()
                    except Exception:
                        pass
                p.kill()
            except Exception:
                try:
                    bp.kill()
                except Exception:
                    pass
        self.browser_process = None  # type: ignore[attr-defined]
        self.update_console("[i] Debug browser closed.\n")
