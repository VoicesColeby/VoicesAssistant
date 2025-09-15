"""Entry point for the Voices automation helper GUI."""

from __future__ import annotations

import tkinter as tk

from gui import VoicesAutomationApp


def main() -> None:
    """Create the Tk root window and launch the automation app."""
    try:
        from tkinterdnd2 import TkinterDnD  # type: ignore

        root = TkinterDnD.Tk()
    except Exception:
        root = tk.Tk()
    VoicesAutomationApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
