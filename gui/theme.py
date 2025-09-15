"""GUI theming helpers and shared styling mixins."""

from __future__ import annotations

import math
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk


class ThemeMixin:
    """Provide styling helpers for :class:`VoicesAutomationApp`."""

    def _init_theme(self) -> None:
        """Apply the base Tk theme and window defaults."""
        try:
            self.colors["bg"] = "#F0F0F0"
            self.master.configure(bg=self.colors["bg"])  # type: ignore[attr-defined]
            self.master.option_add("*Font", self.fonts["body"])  # type: ignore[attr-defined]
            self.master.option_add("*Background", self.colors["bg"])  # type: ignore[attr-defined]
            self.master.option_add("*foreground", self.colors["text"])  # type: ignore[attr-defined]
        except Exception:
            # Best effort styling – ignore Tk availability issues (e.g., on headless tests).
            pass

    def _init_ttk_theme(self) -> None:
        """Configure ttk widgets for the custom colour palette."""
        try:
            style = ttk.Style()
            style.theme_use("clam")

            style.configure("TFrame", background=self.colors["bg"])  # type: ignore[attr-defined]
            style.configure(
                "Panel.TFrame",
                background=self.colors["panel"],
                relief="groove",
                borderwidth=1,
            )
            style.configure(
                "TLabelframe",
                background=self.colors["panel"],
                foreground=self.colors["text"],
                relief="groove",
                borderwidth=1,
            )
            style.configure(
                "TLabelframe.Label",
                background=self.colors["panel"],
                foreground=self.colors["text"],
                font=self.fonts["heading"],
            )
            style.configure(
                "TLabel",
                background=self.colors["bg"],
                foreground=self.colors["text"],
            )
            style.configure(
                "TCheckbutton",
                background=self.colors["bg"],
                foreground=self.colors["text"],
                padding=6,
            )
            style.configure(
                "TEntry",
                fieldbackground="#FFFFFF",
                padding=(20, 14),
                focuscolor=self.colors["accent"],
                focusborderwidth=2,
            )

            style.configure(
                "Secondary.TButton",
                background=self.colors["btn_bg"],
                foreground=self.colors["text"],
                padding=(20, 14),
                relief="flat",
                font=self.fonts["button"],
                focuscolor=self.colors["accent"],
                focusborderwidth=2,
            )
            style.map(
                "Secondary.TButton",
                background=[
                    ("active", self.colors["btn_hover"]),
                    ("pressed", self.colors["btn_active"]),
                ],
                relief=[("pressed", "flat"), ("!pressed", "flat")],
            )

            style.configure(
                "Primary.TButton",
                background=self.colors["accent"],
                foreground="#FFFFFF",
                padding=(20, 14),
                relief="flat",
                font=self.fonts["button"],
                focuscolor=self.colors["accent"],
                focusborderwidth=2,
            )
            style.map(
                "Primary.TButton",
                background=[
                    ("active", self.colors["accent_hover"]),
                    ("pressed", self.colors["accent_active"]),
                ],
                relief=[("pressed", "flat"), ("!pressed", "flat")],
            )

            style.configure(
                "Selected.TButton",
                background=self.colors.get("selected", "#10B981"),
                foreground="#FFFFFF",
                padding=(20, 14),
                relief="flat",
                font=self.fonts["button"],
                focuscolor=self.colors["accent"],
                focusborderwidth=2,
            )
            style.map(
                "Selected.TButton",
                background=[
                    ("active", self.colors.get("selected_hover", "#059669")),
                    ("pressed", self.colors.get("selected_active", "#047857")),
                ],
                relief=[("pressed", "flat"), ("!pressed", "flat")],
            )

            style.configure(
                "Danger.TButton",
                background="#FCA5A5",
                foreground="#FFFFFF",
                padding=(20, 14),
                relief="flat",
                font=self.fonts["button"],
                focuscolor=self.colors["accent"],
                focusborderwidth=2,
            )
            style.map(
                "Danger.TButton",
                background=[("active", "#F87171"), ("pressed", "#EF4444")],
                relief=[("pressed", "flat"), ("!pressed", "flat")],
            )
        except Exception:
            pass

    def _load_logo_image(self, max_side: int = 28):
        """Attempt to load and resize the Voices logo."""
        try:
            base_dir = getattr(self, "base_dir", os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base_dir, "assets", "Favicon_Voices_WhiteOnBlue.png")
            if not os.path.exists(path):
                return None

            try:
                from PIL import Image, ImageTk  # type: ignore

                img = Image.open(path)
                img = img.convert("RGBA")
                w, h = img.size
                if w <= 0 or h <= 0:
                    return None
                scale = min(max_side / float(w), max_side / float(h))
                new_w = max(1, int(round(w * scale)))
                new_h = max(1, int(round(h * scale)))
                img = img.resize((new_w, new_h), Image.LANCZOS)
                return ImageTk.PhotoImage(img)
            except Exception:
                img = tk.PhotoImage(file=path)
                try:
                    w, h = img.width(), img.height()
                    factor = int(
                        math.ceil(
                            max(1.0, max(w / float(max_side), h / float(max_side)))
                        )
                    )
                    if factor > 1:
                        img = img.subsample(factor, factor)
                except Exception:
                    pass
                return img
        except Exception:
            return None

    def _style_frame(self, frame, as_panel: bool = False) -> None:
        try:
            if as_panel:
                frame.configure(style="Panel.TFrame")
            else:
                frame.configure(style="TFrame")
        except Exception:
            pass

    def _bind_hover(self, widget, base: str, hover: str, active: str) -> None:
        def on_enter(_event):
            if str(widget.cget("state")) != "disabled":
                widget.configure(bg=hover)

        def on_leave(_event):
            if str(widget.cget("state")) != "disabled":
                widget.configure(bg=base)

        def on_press(_event):
            if str(widget.cget("state")) != "disabled":
                widget.configure(bg=active)

        def on_release(_event):
            if str(widget.cget("state")) != "disabled":
                widget.configure(bg=hover)

        try:
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<ButtonPress-1>", on_press)
            widget.bind("<ButtonRelease-1>", on_release)
        except Exception:
            pass

    def _style_button(self, btn, kind: str = "secondary") -> None:
        try:
            btn.configure(
                style="Primary.TButton" if kind == "primary" else "Secondary.TButton"
            )
        except Exception:
            pass

    def _style_checkbutton(self, cb) -> None:
        try:
            cb.configure(
                bg=self.colors["bg"],  # type: ignore[attr-defined]
                fg=self.colors["text"],
                activebackground=self.colors["bg"],
            )
        except Exception:
            pass

    def _style_label(self, label, heading: bool = False) -> None:
        try:
            label.configure(
                bg=self.colors["bg"],
                fg=self.colors["text"],
                font=self.fonts["heading" if heading else "body"],
            )
        except Exception:
            pass

    def _style_entry(self, entry) -> None:
        try:
            entry.configure(
                bg="#FFFFFF",
                fg=self.colors["text"],
                insertbackground=self.colors["text"],
                relief=tk.FLAT,
                bd=1,
                highlightthickness=1,
                highlightbackground="#D1D5DB",
                highlightcolor=self.colors["accent"],
            )
        except Exception:
            pass

    def _style_text(self, txt) -> None:
        try:
            txt.configure(
                bg="#FFFFFF",
                fg=self.colors["text"],
                insertbackground=self.colors["text"],
                relief=tk.FLAT,
                bd=1,
                highlightthickness=1,
                highlightbackground="#D1D5DB",
                highlightcolor=self.colors["accent"],
                font=self.fonts["body"],
            )
        except Exception:
            pass
