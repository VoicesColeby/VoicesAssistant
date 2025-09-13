
import tkinter as tk
from tkinter import scrolledtext, messagebox
from tkinter import ttk
import tkinter.font as tkfont
import subprocess
import threading
import sys
import os
import json
import csv
import urllib.parse
import webbrowser
import math
import re
import time

class VoicesAutomationApp:
    def __init__(self, master):
        self.master = master
        master.title("Voices Helper")
        master.geometry("680x520")
        try:
            master.resizable(False, False)
        except Exception:
            pass

        # --- Theme: colors and fonts ---
        self.colors = {
            'bg': '#F3F4F6',
            'panel': '#FFFFFF',
            'text': '#111827',
            'muted': '#6B7280',
            'accent': '#2563EB',
            'accent_hover': '#3B82F6',
            'accent_active': '#1D4ED8',
            'btn_bg': '#E5E7EB',
            'btn_hover': '#D1D5DB',
            'btn_active': '#9CA3AF',
        }
        self.spacing = {
            'section': 16,
            'row': 8,
            'inline': 10,
        }
        self.fonts = {
            'title': tkfont.Font(family='Segoe UI', size=16, weight='bold'),
            'heading': tkfont.Font(family='Segoe UI', size=13, weight='bold'),
            'body': tkfont.Font(family='Segoe UI', size=11),
            'button': tkfont.Font(family='Segoe UI', size=11, weight='bold'),
            'mono': tkfont.Font(family='Consolas', size=11),
        }
        self._init_theme()

        self.selected_action = None
        self.input_fields = {}
        self.process = None
        self.browser_process = None
        self.process_lock = threading.Lock()
        self.is_paused = False
        # Removed: close_browser_var, regular_mode_var per simplification
        # Default to using the already-opened page for all actions
        self.use_current_page_var = tk.BooleanVar(value=True)

        # Initialize ttk theme and styling
        self._init_theme()
        self._init_ttk_theme()
        self.create_widgets()
        self.load_saved_fields()
        self.apply_saved_settings()

    # Simple tooltip helper
    class _Tooltip:
        def __init__(self, widget, text):
            self.widget = widget
            self.text = text
            self.tip = None
            try:
                widget.bind('<Enter>', self._show)
                widget.bind('<Leave>', self._hide)
            except Exception:
                pass
        def _show(self, _evt=None):
            try:
                if self.tip:
                    return
                x = self.widget.winfo_rootx() + 20
                y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
                self.tip = tk.Toplevel(self.widget)
                self.tip.wm_overrideredirect(True)
                self.tip.wm_geometry(f'+{x}+{y}')
                lbl = ttk.Label(self.tip, text=self.text, background='#FFFFE0', relief=tk.SOLID, borderwidth=1)
                lbl.pack(ipadx=6, ipady=3)
            except Exception:
                self.tip = None
        def _hide(self, _evt=None):
            try:
                if self.tip:
                    self.tip.destroy()
                    self.tip = None
            except Exception:
                pass

    @property
    def speed_file_path(self) -> str:
        try:
            return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'speed.cfg')
        except Exception:
            return 'speed.cfg'

    def _write_speed_file(self, value: float = None):
        try:
            v = float(value) if value is not None else float(getattr(self, 'speed_var', tk.DoubleVar(value=5.0)).get())
        except Exception:
            v = 5.0
        try:
            with open(self.speed_file_path, 'w', encoding='utf-8') as f:
                f.write(f"{v:.2f}")
        except Exception:
            pass

    def _init_theme(self):
        try:
            self.master.configure(bg=self.colors['bg'])
            # Set sensible defaults
            self.master.option_add('*Font', self.fonts['body'])
            self.master.option_add('*Background', self.colors['bg'])
            self.master.option_add('*foreground', self.colors['text'])
        except Exception:
            pass

    def _init_ttk_theme(self):
        try:
            style = ttk.Style()
            # Use 'clam' to reliably control button colors across states
            theme = 'clam'
            style.theme_use(theme)

            # Base styles
            style.configure('TFrame', background=self.colors['bg'])
            style.configure('TLabelframe', background=self.colors['panel'], foreground=self.colors['text'])
            style.configure('TLabelframe.Label', background=self.colors['panel'], foreground=self.colors['text'], font=self.fonts['heading'])
            style.configure('TLabel', background=self.colors['bg'], foreground=self.colors['text'])
            style.configure('TCheckbutton', background=self.colors['bg'], foreground=self.colors['text'], padding=6)
            style.configure('TEntry', fieldbackground='#FFFFFF', padding=6)

            # Secondary (light gray) button
            style.configure('Secondary.TButton', background=self.colors['btn_bg'], foreground=self.colors['text'], padding=(14, 8), relief='flat', font=self.fonts['button'])
            style.map('Secondary.TButton',
                      background=[('active', self.colors['btn_hover']), ('pressed', self.colors['btn_active'])],
                      relief=[('pressed', 'flat'), ('!pressed', 'flat')])

            # Primary button with accent
            style.configure('Primary.TButton', background=self.colors['accent'], foreground='#FFFFFF', padding=(18, 10), relief='flat', font=self.fonts['button'])
            style.map('Primary.TButton',
                      background=[('active', self.colors['accent_hover']), ('pressed', self.colors['accent_active'])],
                      relief=[('pressed', 'flat'), ('!pressed', 'flat')])

            # Selected mode button (distinct color)
            style.configure('Selected.TButton', background=self.colors.get('selected', '#10B981'), foreground='#FFFFFF', padding=(14, 8), relief='flat', font=self.fonts['button'])
            style.map('Selected.TButton',
                      background=[('active', self.colors.get('selected_hover', '#059669')), ('pressed', self.colors.get('selected_active', '#047857'))],
                      relief=[('pressed', 'flat'), ('!pressed', 'flat')])

            # Danger (light red) button
            style.configure('Danger.TButton', background='#FCA5A5', foreground='#FFFFFF', padding=(14, 8), relief='flat', font=self.fonts['button'])
            style.map('Danger.TButton',
                      background=[('active', '#F87171'), ('pressed', '#EF4444')],
                      relief=[('pressed', 'flat'), ('!pressed', 'flat')])
        except Exception:
            pass

    def _load_logo_image(self, max_side: int = 28):
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(base_dir, 'assets', 'Favicon_Voices_WhiteOnBlue.png')
            if not os.path.exists(path):
                return None

            # Prefer high-quality resize via Pillow if available
            try:
                from PIL import Image, ImageTk  # type: ignore
                img = Image.open(path)
                img = img.convert('RGBA')
                w, h = img.size
                if w <= 0 or h <= 0:
                    return None
                scale = min(max_side / float(w), max_side / float(h))
                new_w = max(1, int(round(w * scale)))
                new_h = max(1, int(round(h * scale)))
                img = img.resize((new_w, new_h), Image.LANCZOS)
                return ImageTk.PhotoImage(img)
            except Exception:
                # Fallback to Tk's PhotoImage with integer subsample (nearest-neighbor)
                img = tk.PhotoImage(file=path)
                try:
                    w, h = img.width(), img.height()
                    # Compute integer factor so the larger side is near max_side
                    factor = int(math.ceil(max(1.0, max(w / float(max_side), h / float(max_side)))))
                    if factor > 1:
                        img = img.subsample(factor, factor)
                except Exception:
                    pass
                return img
        except Exception:
            return None

    def _style_frame(self, frame, as_panel=False):
        try:
            frame.configure(bg=(self.colors['panel'] if as_panel else self.colors['bg']))
        except Exception:
            pass

    def _bind_hover(self, widget, base, hover, active):
        def on_enter(_):
            if str(widget.cget('state')) != 'disabled':
                widget.configure(bg=hover)
        def on_leave(_):
            if str(widget.cget('state')) != 'disabled':
                widget.configure(bg=base)
        def on_press(_):
            if str(widget.cget('state')) != 'disabled':
                widget.configure(bg=active)
        def on_release(_):
            if str(widget.cget('state')) != 'disabled':
                widget.configure(bg=hover)
        try:
            widget.bind('<Enter>', on_enter)
            widget.bind('<Leave>', on_leave)
            widget.bind('<ButtonPress-1>', on_press)
            widget.bind('<ButtonRelease-1>', on_release)
        except Exception:
            pass

    def _style_button(self, btn, kind='secondary'):
        try:
            btn.configure(style=('Primary.TButton' if kind == 'primary' else 'Secondary.TButton'))
        except Exception:
            pass

    def _style_checkbutton(self, cb):
        try:
            cb.configure(bg=self.colors['bg'], fg=self.colors['text'], activebackground=self.colors['bg'])
        except Exception:
            pass

    def _style_label(self, label, heading=False):
        try:
            label.configure(
                bg=self.colors['bg'],
                fg=self.colors['text'],
                font=(self.fonts['heading'] if heading else self.fonts['body'])
            )
        except Exception:
            pass

    def _style_entry(self, entry):
        try:
            entry.configure(
                bg='#FFFFFF', fg=self.colors['text'],
                insertbackground=self.colors['text'],
                relief=tk.FLAT, bd=1,
                highlightthickness=1,
                highlightbackground='#D1D5DB',
                highlightcolor=self.colors['accent']
            )
        except Exception:
            pass

    def _style_text(self, txt):
        try:
            txt.configure(
                bg='#FFFFFF', fg=self.colors['text'],
                insertbackground=self.colors['text'],
                relief=tk.FLAT, bd=1,
                highlightthickness=1,
                highlightbackground='#D1D5DB',
                highlightcolor=self.colors['accent'],
                font=self.fonts['body']
            )
        except Exception:
            pass

    def create_widgets(self):
        # Action Buttons Frame
        action_frame = ttk.Frame(self.master, padding=(12, self.spacing['section'], 12, 0))
        self._style_frame(action_frame)
        action_frame.pack(fill=tk.X)
        grid = ttk.Frame(action_frame)
        grid.pack(side=tk.LEFT)
        # 2x2 grid of action buttons
        self.invite_button = ttk.Button(grid, text="Invite to Job", width=20, command=lambda: self.show_input_fields("invite"))
        self._style_button(self.invite_button, 'secondary')
        self.invite_button.grid(row=0, column=0, padx=self.spacing['inline'], pady=6, sticky='w')
        self._Tooltip(
            self.invite_button,
            "Prepare fields to invite talents to a job. Open the job page in Voices first.",
        )
        self.favorites_button = ttk.Button(grid, text="Add to Favorites", width=20, command=lambda: self.show_input_fields("favorites"))
        self._style_button(self.favorites_button, 'secondary')
        self.favorites_button.grid(row=0, column=1, padx=self.spacing['inline'], pady=6, sticky='w')
        self._Tooltip(
            self.favorites_button,
            "Add talents to your Favorites list. Make sure a Voices talent page is loaded.",
        )
        self.message_button = ttk.Button(grid, text="Message Talent", width=20, command=lambda: self.show_input_fields("message"))
        self._style_button(self.message_button, 'secondary')
        self.message_button.grid(row=1, column=0, padx=self.spacing['inline'], pady=6, sticky='w')
        self._Tooltip(
            self.message_button,
            "Compose and send a message to talents. Requires a Voices messaging page.",
        )
        # New: Import Invites (CSV of usernames)
        self.import_button = ttk.Button(grid, text="Import Invites", width=20, command=lambda: self.show_input_fields("import_invites"))
        self._style_button(self.import_button, 'secondary')
        self.import_button.grid(row=1, column=1, padx=self.spacing['inline'], pady=6, sticky='w')
        self._Tooltip(
            self.import_button,
            "Bulk invite talents from a CSV of usernames. Select the file before running.",
        )
        # Track mode buttons for highlight toggling
        self.mode_buttons = {
            'invite': self.invite_button,
            'favorites': self.favorites_button,
            'message': self.message_button,
            'import_invites': self.import_button,
        }
        # Voices logo button on the right
        self.voices_logo_img = self._load_logo_image()
        if self.voices_logo_img is not None:
            self.open_button_top = ttk.Button(action_frame, image=self.voices_logo_img, command=self.open_browser)
        else:
            self.open_button_top = ttk.Button(action_frame, text="Open Voices", width=16, command=self.open_browser)
        self._style_button(self.open_button_top, 'secondary')
        self.open_button_top.pack(side=tk.RIGHT, padx=self.spacing['inline'])
        self._Tooltip(
            self.open_button_top,
            "Open the Voices website in your default browser.",
        )

        # Content area: left (inputs) and right (console)
        content = ttk.Frame(self.master, padding=(12, self.spacing['section']))
        content.pack(fill=tk.BOTH, expand=True)
        left_col = ttk.Frame(content)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_col = ttk.Frame(content)
        right_col.pack(side=tk.RIGHT, fill=tk.Y)
        # Input Fields Frame in right column (console on the left)
        self.input_frame = ttk.Frame(right_col, padding=(0, 0))
        self._style_frame(self.input_frame, as_panel=True)
        self.input_frame.pack(fill=tk.BOTH, expand=True)

        # (settings row removed; controls moved to transport area)

        # Console Output
        self.console_frame = ttk.LabelFrame(left_col, text="Console Output", padding=8)
        try:
            self.console_frame.configure()
        except Exception:
            pass
        # Fix console size: about half width and a bit less tall
        self.console_frame.pack(padx=8, pady=(self.spacing['section']//2, self.spacing['section']//2), side=tk.LEFT)
        self.console_container = ttk.Frame(self.console_frame, width=320, height=210)
        self.console_container.pack(fill=tk.BOTH, expand=False)
        self.console_container.pack_propagate(False)
        self.console_text = scrolledtext.ScrolledText(self.console_container, wrap=tk.WORD, state=tk.DISABLED, height=12, width=38)
        try:
            self.console_text.configure(bg='#FFFFFF', fg=self.colors['text'], font=self.fonts['mono'], relief=tk.FLAT, bd=1)
        except Exception:
            pass
        self.console_text.pack(fill=tk.BOTH, expand=True)

        # Progress bar for script execution
        self.progress_bar = ttk.Progressbar(
            self.console_frame, orient=tk.HORIZONTAL, mode='determinate', maximum=1
        )
        self.progress_bar.pack(fill=tk.X, pady=(self.spacing['row'], 0))

        # Transport Controls at bottom
        transport = ttk.Frame(self.master, padding=(12, self.spacing['section'], 12, self.spacing['section']))
        self._style_frame(transport)
        transport.pack(side=tk.BOTTOM, fill=tk.X)

        # Core transport controls: Run, Pause, Cancel
        self.play_pause_button = ttk.Button(transport, text="▶ Start", width=24, command=self.play_pause)
        self._style_button(self.play_pause_button, 'primary')
        self.play_pause_button.pack(side=tk.LEFT, padx=self.spacing['inline'])
        self._Tooltip(
            self.play_pause_button,
            "Execute the selected action. Ensure required inputs and the Voices page are ready.",
        )

        self.pause_button = ttk.Button(transport, text="⏸ Pause", width=10, state=tk.DISABLED, command=self.toggle_pause)
        self._style_button(self.pause_button, 'secondary')
        self.pause_button.pack(side=tk.LEFT, padx=self.spacing['inline'])
        self._Tooltip(
            self.pause_button,
            "Temporarily halt the automation; click again to resume.",
        )

        self.cancel_button = ttk.Button(transport, text="⏹ Cancel", width=10, state=tk.DISABLED, command=self.cancel_run)
        try:
            self.cancel_button.configure(style='Danger.TButton')
        except Exception:
            self._style_button(self.cancel_button, 'secondary')
        self.cancel_button.pack(side=tk.LEFT, padx=self.spacing['inline'])
        self._Tooltip(
            self.cancel_button,
            "Stop the current automation and reset progress.",
        )

        # Speed slider on the right with dynamic label and endpoints
        speed_row = ttk.Frame(transport)
        speed_row.pack(side=tk.RIGHT, padx=self.spacing['inline'])
        self.speed_var = tk.DoubleVar(value=5.0)  # 1.0 slow .. 5.0 fast
        self.speed_value_label = ttk.Label(speed_row, text="Speed: 5.0")
        self.speed_value_label.pack(side=tk.TOP, anchor='e')

        def _on_speed(val):
            try:
                v = float(val)
                self.speed_value_label.config(text=f"Speed: {v:.1f}")
            except Exception:
                pass

        lblrow = ttk.Frame(speed_row)
        lblrow.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(lblrow, text="Slow").pack(side=tk.LEFT)
        ttk.Label(lblrow, text="Fast").pack(side=tk.RIGHT)
        ttk.Scale(speed_row, from_=1.0, to=5.0, variable=self.speed_var, orient=tk.HORIZONTAL, length=180, command=_on_speed).pack(side=tk.TOP)

        # Removed global Save Fields button; Save Message lives on Message tab

    def show_input_fields(self, action):
        # Clear previous fields
        for widget in self.input_frame.winfo_children():
            widget.destroy()

        self.input_fields = {}
        self.selected_action = action
        # Highlight selected mode
        try:
            self.set_selected_mode(action)
        except Exception:
            pass

        # Create new fields based on the selected action
        # Per new flow: only Start URL is required for all actions.
        if action == "invite":
            pass
        elif action == "favorites":
            pass
        elif action == "message":
            self.create_entry("Message:", "message", is_textarea=True)
            # Add Save Message button for this tab
            btn_row = ttk.Frame(self.input_frame)
            self._style_frame(btn_row, as_panel=True)
            btn_row.pack(fill=tk.X, pady=(6, 2))
            save_msg_btn = ttk.Button(btn_row, text="💾 Save Message", width=18, command=self.save_fields)
            save_msg_btn.pack(side=tk.LEFT)
            try:
                save_msg_btn.config(text="Save Message")
            except Exception:
                pass
            self._style_button(save_msg_btn, 'secondary')

        elif action == "import_invites":
            self._import_csv_var = tk.StringVar(value="")
            # Create a simple drop/select area
            panel = ttk.Frame(self.input_frame)
            self._style_frame(panel, as_panel=True)
            panel.pack(fill=tk.BOTH, expand=True, pady=6)
            hint = ttk.Label(panel, text="Drop CSV here or click to select", anchor="center")
            hint.pack(fill=tk.BOTH, expand=True, padx=8, pady=16)
            def _browse_csv():
                p = filedialog.askopenfilename(title="Select CSV", filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
                if p:
                    try:
                        self._import_csv_var.set(p)
                        hint.config(text=f"Selected: {os.path.basename(p)}")
                    except Exception:
                        pass
            # Click to select
            try:
                hint.bind('<Button-1>', lambda e: _browse_csv())
            except Exception:
                pass
            # Optional drag-and-drop support via tkinterdnd2 if available
            try:
                from tkinterdnd2 import DND_FILES  # type: ignore
                def _on_drop(event):
                    try:
                        # event.data may contain one or more paths; take first
                        raw = event.data.strip()
                        if raw.startswith('{') and raw.endswith('}'):
                            raw = raw[1:-1]
                        path = raw.split()[0]
                        if path:
                            self._import_csv_var.set(path)
                            hint.config(text=f"Selected: {os.path.basename(path)}")
                    except Exception:
                        pass
                hint.drop_target_register(DND_FILES)
                hint.dnd_bind('<<Drop>>', _on_drop)
            except Exception:
                pass
            # Immediately prompt for selection to streamline flow
            _browse_csv()

        # Prefill from saved values if available
        self.prefill_saved_fields()

    def set_selected_mode(self, action: str):
        for name, btn in (getattr(self, 'mode_buttons', {}) or {}).items():
            try:
                btn.configure(style=('Selected.TButton' if name == action else 'Secondary.TButton'))
            except Exception:
                pass

    def create_entry(self, label_text, var_name, is_textarea=False):
        row_frame = ttk.Frame(self.input_frame)
        self._style_frame(row_frame, as_panel=True)
        row_frame.pack(fill=tk.X, pady=2)

        label = ttk.Label(row_frame, text=label_text, width=20, anchor="w")
        label.pack(side=tk.LEFT, padx=5)

        if is_textarea:
            text_widget = scrolledtext.ScrolledText(row_frame, height=5, width=50)
            self._style_text(text_widget)
            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
            self.input_fields[var_name] = text_widget
        else:
            entry = ttk.Entry(row_frame, width=50)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            self.input_fields[var_name] = entry
            if var_name == 'url':
                open_btn = ttk.Button(row_frame, text="Open Voices", command=self.open_browser, width=18)
                open_btn.pack(side=tk.LEFT, padx=8)
                self._style_button(open_btn, 'secondary')

    def run_automation(self):
        if not self.selected_action:
            messagebox.showerror("Error", "Please select an action first.")
            return

        # Validate required inputs before starting
        try:
            # Message text required for message action
            if self.selected_action == "message":
                msg_widget = self.input_fields.get('message')
                msg_val = (msg_widget.get('1.0', tk.END) if (msg_widget and hasattr(msg_widget, 'get')) else '').strip()
                if not msg_val:
                    messagebox.showwarning("Missing Message", "Please enter a message before continuing.")
                    return
        except Exception:
            messagebox.showwarning("Validation Error", "Could not validate inputs. Please check fields and try again.")
            return

        # Clear console and set to writing mode
        self.console_text.config(state=tk.NORMAL)
        self.console_text.delete(1.0, tk.END)
        self.console_text.config(state=tk.DISABLED)

        # Reset progress bar for new run
        self._reset_progressbar()

        # Start the automation in a new thread to keep the GUI responsive
        try:
            self.apply_controls_state(running=True)
        except Exception:
            # Fallback to original if present
            try:
                self.set_controls_state(running=True)
            except Exception:
                pass
        t = threading.Thread(target=self._execute_script_thread, daemon=True)
        t.start()

    def _ensure_psutil(self):
        try:
            import psutil  # type: ignore
            return psutil
        except Exception:
            pass
        exe = sys.executable
        # If running as a frozen EXE, we cannot install dynamically
        if getattr(sys, "frozen", False):
            messagebox.showwarning(
                "Pause Unavailable",
                (
                    "Pausing requires the 'psutil' package, which isn't bundled in this build.\n\n"
                    "Please run from source with Python and install psutil, or rebuild including psutil."
                ),
            )
            return None
        # Offer to install psutil for the exact interpreter in use
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
                    subprocess.check_call([exe, "-m", "pip", "install", "psutil"])  # nosec - user-approved install
                    import psutil  # type: ignore
                    return psutil
                except Exception as e:
                    messagebox.showerror(
                        "Install Failed",
                        f"Could not install psutil using:\n{exe} -m pip install psutil\n\nError: {e}",
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
            # As a last resort, just inform the user
            messagebox.showwarning(
                "Pause Unavailable",
                (
                    "Pausing requires the 'psutil' package. Install with:\n"
                    f"\"{exe}\" -m pip install psutil\n"
                    "Or: py -m pip install psutil"
                ),
            )
            return None

    def _execute_script_thread(self):
        try:
            # Get inputs from GUI
            script_path = ""
            env = os.environ.copy()

            if self.selected_action == "invite":
                # Fixed script name; no JOB_QUERY needed anymore
                script_path = "invite_to_job.py"
            elif self.selected_action == "favorites":
                script_path = "add_to_favorites.py"
            elif self.selected_action == "message":
                script_path = "message_talent.py"
                env['MESSAGE'] = self.input_fields['message'].get("1.0", tk.END).strip()
            elif self.selected_action == "import_invites":
                self._run_import_invites(env)
                return

            # Ensure the CDP URL is always set (attach to your debugging browser)
            # Always use default debug URL unless overridden via environment
            if 'DEBUG_URL' not in env or not env['DEBUG_URL']:
                env['DEBUG_URL'] = "http://127.0.0.1:9222"

            # Log the command and parameters
            self.update_console(f"[i] Starting script: {script_path}\n")
            # Using current tab only (no navigation)
            self.update_console("[i] Tip: Click 'Open Voices' to sign in, then click 'Start Helper' to begin.\n")
            if self.selected_action == "message":
                self.update_console(f"[i] MESSAGE: {env.get('MESSAGE')}\n")
            if self.selected_action == "invite":
                env['SKIP_FIRST_TALENT'] = '1'
                self.update_console("[i] Invite flow: will skip the first talent (assumed manual).\n")

            # Always use the current page; do not navigate
            env['USE_CURRENT_PAGE'] = '1'
            self.update_console("[i] Using current browser tab; no navigation.\n")

            # Apply speed slider across flows via env overrides
            try:
                s = float(getattr(self, 'speed_var', tk.DoubleVar(value=5.0)).get())
                s = max(1.0, min(5.0, s))
            except Exception:
                s = 5.0
            # Generic SPEED for scripts that support it (e.g., add_to_favorites)
            env['SPEED'] = f"{s:.2f}"
            # Live speed via SPEED_FILE (no per-script overrides here)
            try:
                self._write_speed_file(s)
                env['SPEED_FILE'] = self.speed_file_path
            except Exception:
                pass

            # Run the script as a subprocess
            creationflags = 0
            try:
                # On Windows, create a new process group
                creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            except Exception:
                pass

            with self.process_lock:
                env['PYTHONUNBUFFERED'] = '1'
                env['PYTHONIOENCODING'] = 'utf-8'
                self.process = subprocess.Popen(
                    [sys.executable, script_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    creationflags=creationflags,
                )
            process = self.process

            # Read and update the console in real-time
            for line in process.stdout:
                self.update_console(line)

            process.wait()
            rc = process.returncode
            self.update_console("[i] Script finished.\n")
            try:
                if rc == 0:
                    messagebox.showinfo("Finished", "Completed successfully.")
                else:
                    messagebox.showinfo("Finished", f"Completed with exit code: {rc}")
            except Exception:
                pass

        except FileNotFoundError:
            self.update_console(f"[x] Error: Could not find the script file '{script_path}'. Please make sure it is in the same directory as this application.\n")
        except Exception as e:
            self.update_console(f"[x] An unexpected error occurred: {e}\n")
        finally:
            with self.process_lock:
                self.process = None
                self.is_paused = False
            try:
                self.apply_controls_state(running=False)
            except Exception:
                try:
                    self.set_controls_state(running=False)
                except Exception:
                    pass
            # Reset progress bar when run completes
            self._reset_progressbar()

    # ===== Browser bootstrap =====
    def get_debug_port(self) -> int:
        # Default debug port
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
        pf = os.environ.get('PROGRAMFILES', r"C:\\Program Files")
        pfx86 = os.environ.get('PROGRAMFILES(X86)', r"C:\\Program Files (x86)")
        local = os.environ.get('LOCALAPPDATA', r"C:\\Users\\%USERNAME%\\AppData\\Local")
        candidates += [
            os.path.join(pf, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(pfx86, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(local, 'Google', 'Chrome', 'Application', 'chrome.exe'),
            os.path.join(pf, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
            os.path.join(pfx86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
        ]
        for path in candidates:
            try:
                if os.path.exists(path):
                    return path
            except Exception:
                continue
        return ''

    def start_browser(self):
        # For convenience; opens with field URL if present
        start_widget = self.input_fields.get('url')
        url = start_widget.get().strip() if (start_widget and hasattr(start_widget, 'get')) else ''
        return self.start_browser_with_url(url)

    def start_browser_with_url(self, url: str = ""):
        exe = self.find_browser_exe()
        if not exe:
            messagebox.showwarning("Browser Not Found", "Could not locate Chrome/Edge executables. Falling back to default browser open.")
            self.open_regular_browser(url)
            return

        # Prepare a persistent user data dir next to this script
        profile_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'voices_debug_profile')
        os.makedirs(profile_dir, exist_ok=True)
        port = self.get_debug_port()
        open_url = url if url else 'about:blank'
        args = [
            exe,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            open_url,
        ]
        try:
            creationflags = 0
            try:
                creationflags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            except Exception:
                pass
            self.browser_process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)
            self.update_console(f"[i] Launched debug browser on port {port}. Log in, then click Start.\n")
        except Exception as e:
            self.update_console(f"[x] Failed to launch browser: {e}\n")

    def open_regular_browser(self, url: str = ""):
        try:
            open_url = url if url else 'about:blank'
            webbrowser.open(open_url)
            self.update_console(f"[i] Opened in regular browser: {open_url}\n")
        except Exception as e:
            self.update_console(f"[x] Failed to open regular browser: {e}\n")

    def open_browser(self):
        # Single entry point for user: always open debug browser at Voices.com
        default_url = 'https://www.voices.com/'
        self.start_browser_with_url(default_url)

    # Removed custom browser path UI to keep things simple

    ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

    def _supports_unicode(self) -> bool:
        if getattr(self, "_unicode_supported", None) is None:
            try:
                f = tkfont.nametofont(self.console_text.cget("font"))
                tests = ("✖", "✓", "⚠", "•")
                self._unicode_supported = all(f.measure(ch) > 0 for ch in tests)
            except Exception:
                self._unicode_supported = False
        return self._unicode_supported

    def _format_console_line(self, text: str) -> str:
        # Ensure str and basic normalization
        try:
            s = str(text)
        except Exception:
            s = "" if text is None else f"{text}"

        # Strip ANSI escape sequences (colors, cursor moves)
        s = self.ANSI_RE.sub("", s)

        # Remove stray control chars except tab/newline
        s = "".join(ch for ch in s if ch == "\n" or ch == "\t" or ord(ch) >= 32)

        # Rephrase specific patterns for clarity
        s = re.sub(r"(?i)\bProcessing talent\s+(\d+)\s*/\s*(\d+)\b", r"Processing talent \1 of \2", s)

        # Replace symbolic UI glyphs with words for portability
        s = s.replace("▶", "Start")
        s = s.replace("⏸", "Pause")
        s = s.replace("⏹", "Stop")

        # Replace our simple tags with clean status indicators
        use_unicode = self._supports_unicode()
        if s.lstrip().startswith("[x]"):
            s = s.replace("[x]", "✖" if use_unicode else "ERR", 1)
        elif s.lstrip().startswith("[i]"):
            # Promote known-success messages to ✓/OK
            if re.search(r"(?i)\b(saved|finished|opened|launched|canceled|paused|resumed)\b", s):
                s = s.replace("[i]", "✓" if use_unicode else "OK", 1)
            else:
                s = s.replace("[i]", "•" if use_unicode else "INFO", 1)
        elif s.lstrip().startswith("[!]"):
            s = s.replace("[!]", "⚠" if use_unicode else "WARN", 1)

        # Guarantee newline termination for consistent display
        if not s.endswith("\n"):
            s += "\n"
        return s

    def update_console(self, text):
        cleaned = self._format_console_line(text)
        # Update progress bar if line matches "Processing talent X of Y"
        try:
            m = re.search(r"Processing talent (\d+) of (\d+)", cleaned)
            if m:
                cur = int(m.group(1))
                total = int(m.group(2))
                self.progress_bar['maximum'] = total
                self.progress_bar['value'] = cur
        except Exception:
            pass
        self.console_text.config(state=tk.NORMAL)
        self.console_text.insert(tk.END, cleaned)
        self.console_text.see(tk.END)
        self.console_text.config(state=tk.DISABLED)

    def _reset_progressbar(self):
        try:
            self.progress_bar['value'] = 0
            self.progress_bar['maximum'] = 1
        except Exception:
            pass

    def _run_import_invites(self, base_env: dict):
        # Ask for CSV if not provided via UI
        path = getattr(self, '_import_csv_var', None)
        csv_path = ''
        try:
            csv_path = (path.get() if path else '')
        except Exception:
            csv_path = ''
        if not csv_path:
            try:
                p = filedialog.askopenfilename(title="Select CSV", filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")])
                csv_path = p or ''
            except Exception:
                csv_path = ''
        if not csv_path or not os.path.exists(csv_path):
            messagebox.showwarning("CSV Required", "Please select a CSV file with a 'username' column.")
            return

        # Parse CSV and collect usernames
        try:
            with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                # Find username column (case-insensitive)
                fieldmap = { (c or '').strip().lower(): c for c in (reader.fieldnames or []) }
                ucol = fieldmap.get('username')
                if not ucol:
                    messagebox.showerror("CSV Error", "Could not find a 'username' column in the CSV.")
                    return
                usernames = [ (row.get(ucol) or '').strip() for row in reader ]
        except Exception as e:
            messagebox.showerror("CSV Error", f"Failed to read CSV: {e}")
            return
        usernames = [u for u in usernames if u]
        if not usernames:
            messagebox.showinfo("No Users", "No usernames found in the CSV.")
            return

        total = len(usernames)
        self.update_console(f"[i] Importing {total} usernames from CSV...\n")

        # Ensure debug URL
        env = base_env.copy()
        if 'DEBUG_URL' not in env or not env['DEBUG_URL']:
            env['DEBUG_URL'] = "http://127.0.0.1:9222"

        # We'll navigate explicitly; some scripts honor START_URL
        env['USE_CURRENT_PAGE'] = '0'

        # Loop each username and invite via profile URL
        self._stop_import = False
        successes = []
        failures = []
        for idx, username in enumerate(usernames, start=1):
            if getattr(self, '_stop_import', False):
                self.update_console("[i] Import canceled.\n")
                break
            profile_url = f"https://www.voices.com/profile/{username}"
            self.update_console(f"[i] ({idx} of {total}) Inviting: {username}\n")
            # Choose script that can navigate to START_URL
            script_path = "invite_to_job_cdp.py" if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'invite_to_job_cdp.py')) else "invite_to_job.py"
            run_env = env.copy()
            run_env['START_URL'] = profile_url

            # Start subprocess
            creationflags = 0
            try:
                creationflags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            except Exception:
                pass
            with self.process_lock:
                run_env['PYTHONUNBUFFERED'] = '1'
                run_env['PYTHONIOENCODING'] = 'utf-8'
                self.process = subprocess.Popen(
                    [sys.executable, script_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=run_env,
                    creationflags=creationflags,
                )
            proc = self.process
            try:
                for line in proc.stdout:
                    self.update_console(line)
            except Exception:
                pass
            finally:
                try:
                    proc.wait(timeout=10)
                except Exception:
                    pass
            rc = None
            try:
                rc = proc.returncode
            except Exception:
                rc = None
            if rc == 0:
                successes.append(username)
                self.update_console(f"[i] Invited: {username}\n")
            else:
                failures.append((username, rc))
                self.update_console(f"[x] Failed to invite: {username} (code={rc})\n")
            # Apply pacing based on speed slider (1 slow .. 5 fast)
            try:
                speed = float(getattr(self, 'speed_var', tk.DoubleVar(value=5.0)).get())
                delay = max(0.0, (6.0 - speed) * 0.4)
                if delay > 0:
                    time.sleep(delay)
            except Exception:
                pass
        # Summary
        total_done = len(successes) + len(failures)
        self.update_console(f"[i] Import invites finished. {len(successes)} succeeded, {len(failures)} failed.\n")
        if failures:
            failed_list = ", ".join([u for (u, _) in failures[:10]])
            more = "" if len(failures) <= 10 else f" (+{len(failures)-10} more)"
            self.update_console(f"[x] Failed usernames: {failed_list}{more}\n")
            try:
                base, ext = os.path.splitext(csv_path)
                out_path = base + "_failures.csv"
                with open(out_path, 'w', encoding='utf-8', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["username", "code"])
                    for (u, code) in failures:
                        writer.writerow([u, code if code is not None else ""])
                self.update_console(f"[i] Wrote failures CSV: {out_path}\n")
            except Exception as e:
                self.update_console(f"[x] Failed to write failures CSV: {e}\n")
        # Final popup summary
        try:
            if failures:
                messagebox.showinfo("Import Invites Summary", f"Finished.\nSuccesses: {len(successes)}\nFailures: {len(failures)}\nA failures CSV has been saved next to your source file.")
            else:
                messagebox.showinfo("Import Invites Summary", f"Finished.\nAll {len(successes)} usernames invited successfully.")
        except Exception:
            pass

    # ===== Controls =====
    def apply_controls_state(self, running: bool):
        """Enable/disable transport controls based on running/paused state."""

        # --- Not running ---
        if not running:
            try:
                self.play_pause_button.config(state=tk.NORMAL, text="▶ Start")
            except Exception:
                pass
            try:
                self.pause_button.config(state=tk.DISABLED, text="⏸ Pause")
            except Exception:
                pass
            try:
                self.cancel_button.config(state=tk.DISABLED)
            except Exception:
                pass
            self.is_paused = False
            return

        # --- Paused ---
        if self.is_paused:
            try:
                self.play_pause_button.config(state=tk.DISABLED)
            except Exception:
                pass
            try:
                self.pause_button.config(state=tk.NORMAL, text="▶ Resume")
            except Exception:
                pass
            try:
                self.cancel_button.config(state=tk.NORMAL)
            except Exception:
                pass
            return

        # --- Running (active) ---
        try:
            self.play_pause_button.config(state=tk.DISABLED)
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

    def set_controls_state(self, running: bool):
        if running:
            self.play_pause_button.config(state=tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL, text="⏸ Pause")
            self.cancel_button.config(state=tk.NORMAL)
        else:
            self.play_pause_button.config(state=tk.NORMAL)
            self.pause_button.config(state=tk.DISABLED, text="⏸ Pause")
            self.cancel_button.config(state=tk.DISABLED)
            self.is_paused = False

    def play_pause(self):
        with self.process_lock:
            proc = self.process
        if not proc or proc.poll() is not None:
            self.run_automation()
            try:
                self.apply_controls_state(running=True)
            except Exception:
                pass
        else:
            self.toggle_pause()

    def _walk_children(self, psutil_proc):
        try:
            for child in psutil_proc.children(recursive=True):
                yield child
        except Exception:
            return

    def toggle_pause(self):
        with self.process_lock:
            proc = self.process
        if not proc or proc.poll() is not None:
            return
        psutil = self._ensure_psutil()
        if psutil is None:
            return

        p = psutil.Process(proc.pid)
        try:
            if not self.is_paused:
                for ch in self._walk_children(p):
                    ch.suspend()
                p.suspend()
                self.is_paused = True
                self.pause_button.config(text="▶ Resume")
                self.update_console("[i] Paused.\n")
            else:
                for ch in self._walk_children(p):
                    ch.resume()
                p.resume()
                self.is_paused = False
                self.pause_button.config(text="⏸ Pause")
                self.update_console("[i] Resumed.\n")
        except Exception as e:
            self.update_console(f"[x] Pause/Resume error: {e}\n")
        self.apply_controls_state(running=True)

    def cancel_run(self):
        with self.process_lock:
            proc = self.process
        if not proc or proc.poll() is not None:
            return
        # Signal import loops to stop after current task
        try:
            self._stop_import = True
        except Exception:
            pass
        try:
            psutil = self._ensure_psutil()
            if psutil is None:
                raise RuntimeError("psutil not available")
            p = psutil.Process(proc.pid)
            # Terminate children first
            for ch in self._walk_children(p):
                try:
                    ch.terminate()
                except Exception:
                    pass
            p.terminate()
            try:
                p.wait(timeout=5)
            except Exception:
                # Force kill if needed
                for ch in self._walk_children(p):
                    try:
                        ch.kill()
                    except Exception:
                        pass
                p.kill()
            self.update_console("[i] Canceled run.\n")
        except Exception:
            # Fallback without psutil
            try:
                proc.terminate()
            except Exception:
                pass
            self.update_console("[i] Canceled run (basic).\n")
        finally:
            try:
                self.apply_controls_state(running=False)
            except Exception:
                try:
                    self.set_controls_state(running=False)
                except Exception:
                    pass

    def _try_close_browser(self):
        bp = self.browser_process
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
        self.browser_process = None
        self.update_console("[i] Debug browser closed.\n")

    # Removed legacy open_start_url; using Open Voices top button to launch debug browser

    # ===== Save/Load fields =====
    @property
    def state_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gui_state.json')

    def collect_current_fields(self):
        data = {}
        for key, widget in self.input_fields.items():
            if hasattr(widget, 'get'):
                if isinstance(widget, scrolledtext.ScrolledText):
                    data[key] = widget.get('1.0', tk.END).strip()
                else:
                    data[key] = widget.get().strip()
        return data

    def save_fields(self):
        if not self.selected_action:
            messagebox.showinfo("Save Message", "Select an action first.")
            return
        settings = {}
        payload = {
            "_selected": self.selected_action,
            self.selected_action: self.collect_current_fields(),
            "_settings": settings,
        }
        # Merge with existing state
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            else:
                existing = {}
        except Exception:
            existing = {}
        existing.update(payload)
        try:
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=2)
            if self.selected_action == 'message':
                self.update_console("[i] Saved message.\n")
            else:
                self.update_console("[i] Saved fields.\n")
        except Exception as e:
            self.update_console(f"[x] Failed to save: {e}\n")

    def load_saved_fields(self):
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    self._saved_state = json.load(f)
            else:
                self._saved_state = {}
        except Exception:
            self._saved_state = {}

    def prefill_saved_fields(self):
        if not hasattr(self, '_saved_state'):
            self._saved_state = {}
        state = self._saved_state.get(self.selected_action, {}) if self.selected_action else {}
        for key, widget in self.input_fields.items():
            val = state.get(key, '')
            try:
                if isinstance(widget, scrolledtext.ScrolledText):
                    widget.delete('1.0', tk.END)
                    if val:
                        widget.insert('1.0', val)
                else:
                    widget.delete(0, tk.END)
                    widget.insert(0, val)
            except Exception:
                pass

    def apply_saved_settings(self):
        # No settings to apply at the moment (use current page is always on)
        return

if __name__ == "__main__":
    root = tk.Tk()
    app = VoicesAutomationApp(root)
    root.mainloop()

