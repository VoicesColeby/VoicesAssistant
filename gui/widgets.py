"""Widget construction and layout helpers for the GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, scrolledtext, simpledialog, ttk


class Tooltip:
    """Simple tooltip helper used throughout the UI."""

    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.tip = None
        try:
            widget.bind("<Enter>", self._show)
            widget.bind("<Leave>", self._hide)
        except Exception:
            pass

    def _show(self, _evt=None):  # noqa: D401 - behaviour mirrors legacy helper
        try:
            if self.tip:
                return
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            lbl = ttk.Label(
                self.tip,
                text=self.text,
                background="#FFFFE0",
                relief=tk.SOLID,
                borderwidth=1,
            )
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


class WidgetMixin:
    """Widget creation helpers shared by the main application class."""

    tooltip_class = Tooltip

    # --- Tooltip ---------------------------------------------------------
    def _create_tooltip(self, widget, text: str):
        try:
            return self.tooltip_class(widget, text)
        except Exception:
            return None

    # --- Layout ----------------------------------------------------------
    def create_widgets(self) -> None:
        self.master.grid_rowconfigure(0, weight=0)
        self.master.grid_rowconfigure(1, weight=1)
        self.master.grid_rowconfigure(2, weight=0)
        self.master.grid_columnconfigure(0, weight=1)

        action_frame = ttk.Frame(
            self.master, padding=(12, self.spacing["section"], 12, 0)
        )
        self._style_frame(action_frame)
        action_frame.grid(row=0, column=0, sticky="ew")

        left_container = ttk.Frame(action_frame)
        left_container.pack(side=tk.LEFT, expand=True, fill="x")
        left_container.grid_columnconfigure(0, weight=1)

        grid = ttk.Frame(left_container)
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1, uniform="actions")
        grid.grid_columnconfigure(1, weight=1, uniform="actions")
        grid.grid_rowconfigure(0, weight=1)
        grid.grid_rowconfigure(1, weight=1)

        self.invite_button = ttk.Button(
            grid,
            text="Invite",
            command=lambda: self.show_input_fields("invite"),
            takefocus=True,
        )
        self._style_button(self.invite_button, "secondary")
        self.invite_button.grid(
            row=0,
            column=0,
            padx=self.spacing["inline"],
            pady=self.spacing["row"],
            sticky="nsew",
        )
        self._create_tooltip(
            self.invite_button,
            "Prepare fields to invite talents to a job. Open the job page in Voices first.",
        )

        self.favorites_button = ttk.Button(
            grid,
            text="Favorites",
            command=lambda: self.show_input_fields("favorites"),
            takefocus=True,
        )
        self._style_button(self.favorites_button, "secondary")
        self.favorites_button.grid(
            row=0,
            column=1,
            padx=self.spacing["inline"],
            pady=self.spacing["row"],
            sticky="nsew",
        )
        self._create_tooltip(
            self.favorites_button,
            "Add talents to your Favorites list. Make sure a Voices talent page is loaded.",
        )

        self.message_button = ttk.Button(
            grid,
            text="Message",
            command=lambda: self.show_input_fields("message"),
            takefocus=True,
        )
        self._style_button(self.message_button, "secondary")
        self.message_button.grid(
            row=1,
            column=0,
            padx=self.spacing["inline"],
            pady=self.spacing["row"],
            sticky="nsew",
        )
        self._create_tooltip(
            self.message_button,
            "Compose and send a message to talents. Requires a Voices messaging page.",
        )

        self.import_button = ttk.Button(
            grid,
            text="Import Invites",
            command=lambda: self.show_input_fields("import_invites"),
            takefocus=True,
        )
        self._style_button(self.import_button, "secondary")
        self.import_button.grid(
            row=1,
            column=1,
            padx=self.spacing["inline"],
            pady=self.spacing["row"],
            sticky="nsew",
        )
        self._create_tooltip(
            self.import_button,
            "Bulk invite talents from a CSV of usernames. Select the file before running.",
        )

        self.mode_buttons = {
            "invite": self.invite_button,
            "favorites": self.favorites_button,
            "message": self.message_button,
            "import_invites": self.import_button,
        }

        status_frame = ttk.Frame(left_container)
        status_frame.pack(fill=tk.X, expand=True, padx=4, pady=(0, self.spacing["row"]))
        status_frame.grid_columnconfigure(0, weight=1)
        status_frame.grid_columnconfigure(1, weight=1)
        for idx, action in enumerate(self.actions_order):
            label = ttk.Label(
                status_frame,
                textvariable=self.status_vars[action],
                anchor="w",
            )
            row = idx // 2
            col = idx % 2
            label.grid(
                row=row,
                column=col,
                sticky="w",
                padx=self.spacing["inline"],
                pady=(0, 2),
            )

        self.voices_logo_img = self._load_logo_image()
        if self.voices_logo_img is not None:
            self.open_button_top = ttk.Button(
                action_frame,
                image=self.voices_logo_img,
                command=self.open_browser,
                takefocus=True,
            )
        else:
            self.open_button_top = ttk.Button(
                action_frame,
                text="Open Voices",
                command=self.open_browser,
                takefocus=True,
            )
        self._style_button(self.open_button_top, "secondary")
        self.open_button_top.pack(side=tk.RIGHT, padx=self.spacing["inline"])
        self._create_tooltip(
            self.open_button_top,
            "Open the Voices website in your default browser.",
        )

        content = ttk.Frame(self.master, padding=(12, self.spacing["section"]))
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=1)

        left_col = ttk.Frame(content)
        left_col.grid(row=0, column=0, sticky="nsew")
        left_col.grid_rowconfigure(0, weight=1)
        left_col.grid_columnconfigure(0, weight=1)

        right_col = ttk.Frame(content)
        right_col.grid(row=0, column=1, sticky="nsew")
        right_col.grid_rowconfigure(0, weight=1)
        right_col.grid_columnconfigure(0, weight=1)

        self.input_frame = ttk.Frame(right_col, padding=(0, 0))
        self._style_frame(self.input_frame, as_panel=True)
        self.input_frame.grid(row=0, column=0, sticky="nsew")

        self.console_frame = ttk.LabelFrame(left_col, text="Console Output", padding=8)
        try:
            self.console_frame.configure()
        except Exception:
            pass
        self.console_frame.grid(
            row=0,
            column=0,
            padx=self.spacing["inline"],
            pady=(self.spacing["section"] // 2, self.spacing["section"] // 2),
            sticky="nsew",
        )
        self.console_frame.grid_rowconfigure(0, weight=1)
        self.console_frame.grid_columnconfigure(0, weight=1)

        self.console_container = ttk.Frame(self.console_frame)
        self.console_container.grid(row=0, column=0, sticky="nsew")
        self.console_container.grid_rowconfigure(0, weight=1)
        self.console_container.grid_columnconfigure(0, weight=1)

        self.console_text = scrolledtext.ScrolledText(
            self.console_container, wrap=tk.WORD, state=tk.DISABLED
        )
        try:
            self.console_text.configure(
                bg="#FFFFFF",
                fg=self.colors["text"],
                font=self.fonts["mono"],
                relief=tk.FLAT,
                bd=1,
            )
        except Exception:
            pass
        self.console_text.configure(takefocus=True)
        self.console_text.grid(row=0, column=0, sticky="nsew")

        self.progress_bar = ttk.Progressbar(
            self.console_frame, orient=tk.HORIZONTAL, mode="determinate", maximum=1
        )
        self.progress_bar.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(self.spacing["row"], 0),
        )

        transport = ttk.Frame(
            self.master,
            padding=(12, self.spacing["section"], 12, self.spacing["section"]),
        )
        self._style_frame(transport)
        transport.grid(row=2, column=0, sticky="ew")

        self.play_pause_button = ttk.Button(
            transport,
            text="▶ Start",
            command=self.play_pause,
            takefocus=True,
        )
        self._style_button(self.play_pause_button, "primary")
        self.play_pause_button.pack(side=tk.LEFT, padx=self.spacing["inline"])
        self._create_tooltip(
            self.play_pause_button,
            "Execute the selected action. Ensure required inputs and the Voices page are ready.",
        )

        self.pause_button = ttk.Button(
            transport,
            text="⏸ Pause",
            state=tk.DISABLED,
            command=self.toggle_pause,
            takefocus=True,
        )
        self._style_button(self.pause_button, "secondary")
        self.pause_button.pack(side=tk.LEFT, padx=self.spacing["inline"])
        self._create_tooltip(
            self.pause_button,
            "Temporarily halt the automation; click again to resume.",
        )

        self.cancel_button = ttk.Button(
            transport,
            text="⏹ Cancel",
            state=tk.DISABLED,
            command=self.cancel_run,
            takefocus=True,
        )
        try:
            self.cancel_button.configure(style="Danger.TButton")
        except Exception:
            self._style_button(self.cancel_button, "secondary")
        self.cancel_button.pack(side=tk.LEFT, padx=self.spacing["inline"])
        self._create_tooltip(
            self.cancel_button,
            "Stop the current automation and reset progress.",
        )

        speed_row = ttk.Frame(transport)
        speed_row.pack(side=tk.RIGHT, padx=self.spacing["inline"])

        self.speed_var = tk.DoubleVar(value=5.0)
        ttk.Label(speed_row, text="Speed").pack(side=tk.LEFT)

        def _on_speed(val):
            try:
                self.speed_var.set(float(val))
                self._write_speed_file(self.speed_var.get())
            except Exception:
                pass

        ttk.Scale(
            speed_row,
            from_=1.0,
            to=5.0,
            variable=self.speed_var,
            orient=tk.HORIZONTAL,
            length=180,
            command=_on_speed,
            takefocus=True,
        ).pack(side=tk.LEFT, padx=(self.spacing["inline"], 0))

        def _validate_speed(value: str) -> bool:
            try:
                v = float(value)
                self.speed_var.set(v)
                self._write_speed_file(v)
                return True
            except Exception:
                return False

        vcmd = (self.master.register(_validate_speed), "%P")
        ttk.Entry(
            speed_row,
            textvariable=self.speed_var,
            width=5,
            justify="center",
            validate="focusout",
            validatecommand=vcmd,
        ).pack(side=tk.LEFT, padx=(self.spacing["inline"], 0))

    def show_input_fields(self, action: str) -> None:
        for widget in self.input_frame.winfo_children():
            widget.destroy()

        self.input_fields = {}
        self.selected_action = action

        try:
            self.set_selected_mode(action)
        except Exception:
            pass

        try:
            self.input_frame.grid()
        except Exception:
            pass

        if action in {"invite", "favorites"}:
            helper_label = ttk.Label(
                self.input_frame,
                text="Open the relevant Voices page, then click Start.",
                anchor="center",
                justify=tk.CENTER,
                wraplength=360,
            )
            self._style_label(helper_label)
            helper_label.pack(
                fill=tk.X,
                padx=self.spacing["inline"],
                pady=(self.spacing["row"], 0),
            )
        if action == "invite":
            pass
        elif action == "favorites":
            pass
        elif action == "message":
            self.create_entry("Message:", "message", is_textarea=True)
            btn_row = ttk.Frame(self.input_frame)
            self._style_frame(btn_row, as_panel=True)
            btn_row.pack(fill=tk.X, pady=(6, 2))
            save_msg_btn = ttk.Button(
                btn_row, text="💾 Save Message", command=self.save_fields, takefocus=True
            )
            save_msg_btn.pack(side=tk.LEFT)
            try:
                save_msg_btn.config(text="Save Message")
            except Exception:
                pass
            self._style_button(save_msg_btn, "secondary")
        elif action == "import_invites":
            try:
                self.input_frame.grid_remove()
            except Exception:
                pass

            try:
                job = simpledialog.askstring("Job #", "Enter the Job # to invite talents to:")
            except Exception:
                job = None
            self._import_job_number = (job or "").strip()

            try:
                path = filedialog.askopenfilename(
                    title="Select CSV",
                    filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
                )
            except Exception:
                path = ""
            self._import_csv_path = path or ""

        self.prefill_saved_fields()

    def set_selected_mode(self, action: str) -> None:
        for name, btn in getattr(self, "mode_buttons", {}).items():
            try:
                btn.configure(
                    style="Selected.TButton" if name == action else "Secondary.TButton"
                )
            except Exception:
                pass

    def create_entry(self, label_text: str, var_name: str, is_textarea: bool = False) -> None:
        row_frame = ttk.Frame(self.input_frame)
        self._style_frame(row_frame, as_panel=True)
        row_frame.pack(fill=tk.X, pady=2)

        label = ttk.Label(row_frame)
        label.configure(text=label_text, anchor="w", width=20)
        label.pack(side=tk.LEFT, padx=5)

        if is_textarea:
            text_widget = scrolledtext.ScrolledText(
                row_frame, height=5, width=50, takefocus=True
            )
            self._style_text(text_widget)
            text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)
            label["for"] = text_widget
            self.input_fields[var_name] = text_widget
        else:
            entry = ttk.Entry(row_frame, width=50, takefocus=True)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            label["for"] = entry
            self.input_fields[var_name] = entry
            if var_name == "url":
                open_btn = ttk.Button(
                    row_frame, text="Open Voices", command=self.open_browser, takefocus=True
                )
                open_btn.pack(side=tk.LEFT, padx=8)
                self._style_button(open_btn, "secondary")
