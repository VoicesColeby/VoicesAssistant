"""Application assembly for the Voices automation helper GUI."""

from __future__ import annotations

import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Dict

from .actions import AutomationMixin
from .state import StateMixin
from .theme import ThemeMixin
from .widgets import WidgetMixin


class VoicesAutomationApp(ThemeMixin, WidgetMixin, AutomationMixin, StateMixin):
    """Main Tkinter application composed from feature mixins."""

    def __init__(self, master: tk.Misc):
        self.master = master
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        master.title("Voices Helper")
        master.geometry("800x600")
        master.minsize(800, 600)
        try:
            master.resizable(True, True)
        except Exception:
            pass

        self.colors: Dict[str, str] = {
            "bg": "#F0F0F0",
            "panel": "#FFFFFF",
            "text": "#111827",
            "muted": "#6B7280",
            "accent": "#2563EB",
            "accent_hover": "#3B82F6",
            "accent_active": "#1D4ED8",
            "btn_bg": "#E5E7EB",
            "btn_hover": "#D1D5DB",
            "btn_active": "#9CA3AF",
        }
        self.spacing = {"section": 12, "row": 8, "inline": 8}
        self.fonts = {
            "title": tkfont.Font(family="Segoe UI", size=16, weight="bold"),
            "heading": tkfont.Font(family="Segoe UI", size=13, weight="bold"),
            "body": tkfont.Font(family="Segoe UI", size=11),
            "button": tkfont.Font(family="Segoe UI", size=11, weight="bold"),
            "mono": tkfont.Font(family="Consolas", size=11),
        }
        self._init_theme()

        self.actions_order = ["invite", "favorites", "message", "import_invites"]
        self.action_labels = {
            "invite": "Invite",
            "favorites": "Favorites",
            "message": "Message",
            "import_invites": "Import Invites",
        }

        self.selected_action: str | None = None
        self.input_fields: Dict[str, tk.Widget] = {}
        self.process = None
        self.browser_process = None
        self.process_lock = threading.Lock()
        self.is_paused = False
        self.use_current_page_var = tk.BooleanVar(value=True)
        self.current_action: str | None = None
        self._status_overrides: Dict[str, str] = {}

        self.status_vars = {
            action: tk.StringVar(master=self.master)
            for action in self.actions_order
        }

        self._init_ttk_theme()
        for action in self.actions_order:
            self.update_status(action, "Ready")

        self.create_widgets()
        self.load_saved_fields()
        self.apply_saved_settings()
