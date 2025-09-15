"""Persistence helpers for saving and restoring GUI state."""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import scrolledtext


class StateMixin:
    """Provide save/load helpers for persisted GUI fields."""

    @property
    def state_path(self) -> str:
        base_dir = getattr(self, "base_dir", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "gui_state.json")

    def collect_current_fields(self) -> dict[str, str]:
        data: dict[str, str] = {}
        for key, widget in self.input_fields.items():  # type: ignore[attr-defined]
            if hasattr(widget, "get"):
                if isinstance(widget, scrolledtext.ScrolledText):
                    data[key] = widget.get("1.0", tk.END).strip()
                else:
                    data[key] = widget.get().strip()
        return data

    def save_fields(self) -> None:
        if not self.selected_action:  # type: ignore[attr-defined]
            from tkinter import messagebox

            messagebox.showinfo("Save Message", "Select an action first.")
            return

        settings: dict[str, str] = {}
        payload = {
            "_selected": self.selected_action,
            self.selected_action: self.collect_current_fields(),
            "_settings": settings,
        }

        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
            else:
                existing = {}
        except Exception:
            existing = {}

        existing.update(payload)
        try:
            with open(self.state_path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            if self.selected_action == "message":
                self.update_console("[i] Saved message.\n")  # type: ignore[attr-defined]
            else:
                self.update_console("[i] Saved fields.\n")  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - console logging
            self.update_console(f"[x] Failed to save: {exc}\n")  # type: ignore[attr-defined]

    def load_saved_fields(self) -> None:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path, "r", encoding="utf-8") as fh:
                    self._saved_state = json.load(fh)
            else:
                self._saved_state = {}
        except Exception:
            self._saved_state = {}

    def prefill_saved_fields(self) -> None:
        if not hasattr(self, "_saved_state"):
            self._saved_state = {}

        state = self._saved_state.get(self.selected_action, {}) if self.selected_action else {}
        for key, widget in self.input_fields.items():  # type: ignore[attr-defined]
            val = state.get(key, "")
            try:
                if isinstance(widget, scrolledtext.ScrolledText):
                    widget.delete("1.0", tk.END)
                    if val:
                        widget.insert("1.0", val)
                else:
                    widget.delete(0, tk.END)
                    widget.insert(0, val)
            except Exception:
                pass

    def apply_saved_settings(self) -> None:
        return
