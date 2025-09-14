"""
Common logging helpers for CLI output with simple ANSI colors.

Functions:
- info(msg): Cyan info tag
- ok(msg):   Green check tag
- warn(msg): Yellow warning tag
- err(msg):  Red error tag

Keep output stable and flush immediately for GUI piping.
"""

def _print(tag: str, color: str, msg: str) -> None:
    try:
        print(f"\x1b[{color}{tag}\x1b[0m {msg}", flush=True)
    except Exception:
        # Fallback without ANSI if console does not support it
        print(f"{tag.strip('[]')} {msg}", flush=True)


def info(msg: str) -> None:
    _print("[i]", "36m", msg)  # cyan


def ok(msg: str) -> None:
    _print("[\u2713]", "32m", msg)  # green check


def warn(msg: str) -> None:
    _print("[!]", "33m", msg)  # yellow


def err(msg: str) -> None:
    _print("[x]", "31m", msg)  # red

