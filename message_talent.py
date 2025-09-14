# message_talent.py — open each message modal, paste MESSAGE, then click Send
# Slowed pacing + periodic long pauses + robust 'Send' click

import asyncio
import os
import random
import re
from typing import Dict
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout
from common_logging import info, ok, warn, err

# =======================
# Config (env-overridable)
# =======================
START_URL = os.getenv("START_URL", "https://YOUR_JOB_RESPONSES_URL")  # e.g. https://www.voices.com/client/jobs/responses/123456
MESSAGE = os.getenv(
    "MESSAGE",
    "Hi there, we'd like to move forward with your audition. Please reply to this message to continue."
)
CDP_URL = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")  # :contentReference[oaicite:0]{index=0}
USE_CURRENT = os.getenv("USE_CURRENT_PAGE", "1").strip().lower() in ("1", "true", "yes")

# Toggle actual sending (set to "false" to dry-run: open, type, close without sending)
SEND_ENABLED = os.getenv("SEND_ENABLED", "true").lower() == "true"

# Timeouts & pacing (base values)
DEFAULT_TIMEOUT_MS   = int(os.getenv("DEFAULT_TIMEOUT_MS", "60000"))
BETWEEN_STEPS_MS     = int(os.getenv("BETWEEN_STEPS_MS", "700"))     # minor step delay
BETWEEN_ACTIONS_MS   = int(os.getenv("BETWEEN_ACTIONS_MS", "3000"))   # main per-talent delay (slower)
# Long pause controls
LONG_PAUSE_EVERY     = int(os.getenv("LONG_PAUSE_EVERY", "75"))       # pause every N talents
LONG_PAUSE_MIN_MS    = int(os.getenv("LONG_PAUSE_MIN_MS", "60000"))   # 60s
LONG_PAUSE_MAX_MS    = int(os.getenv("LONG_PAUSE_MAX_MS", "120000"))  # 120s

# =======================
# Live speed support
# =======================
def _read_speed_file() -> float:
    try:
        path = os.getenv("SPEED_FILE", "").strip()
        if path and os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                v = float((f.read() or '5').strip())
                return max(1.0, min(5.0, v))
    except Exception:
        pass
    try:
        return max(1.0, min(5.0, float(os.getenv("SPEED", "5.0"))))
    except Exception:
        return 5.0

def r(min_ms: int, max_ms: int) -> float:
    speed = _read_speed_file()
    lo = min_ms / speed
    hi = max_ms / speed
    return random.uniform(lo/1000, hi/1000)
# =======================
# Selectors
# =======================

# STRICT selectors for the 'Message' buttons (avoid "View Message")
MESSAGE_BUTTON_SELECTORS = [
    "a.btn.btn-default[role='button'][data-bs-toggle='modal'][data-bs-target='#job-responses-messaging-modal']",
    "a.btn.btn-default[role='button'][data-bs-toggle='modal']",
    # Intentionally avoiding broader fallbacks that could capture "View Message"
]  # :contentReference[oaicite:1]{index=1}

# Messaging modal (Voices)
MESSAGING_MODAL = "#job-responses-messaging-modal"

# Textarea (per DOM you shared)
MESSAGE_TEXTAREA = "#job-responses-messaging-modal-body"

# Primary Send button — we’ll build this in code with multiple robust fallbacks
# Kept for reference: previous approach targeted the modal + this button. :contentReference[oaicite:2]{index=2}

# Optional toast/success selectors (best-effort; safe if missing)
SUCCESS_MSG = ".toast-success, .alert-success, .success-message"
ERROR_MSG   = ".toast-error, .alert-danger, .error-message"

# =======================
# Humanization
# =======================
async def human_delay(base_ms: int = 300):
    await asyncio.sleep(r(base_ms, base_ms + 250))

async def step_pause():
    await asyncio.sleep(r(BETWEEN_STEPS_MS, BETWEEN_STEPS_MS + 400))

async def action_pause():
    await asyncio.sleep(r(BETWEEN_ACTIONS_MS, BETWEEN_ACTIONS_MS + 1000))

async def long_pause():
    await asyncio.sleep(r(LONG_PAUSE_MIN_MS, LONG_PAUSE_MAX_MS))

# =========================
# Core Functions
# =========================

async def safe_click(loc: Locator, timeout: int = DEFAULT_TIMEOUT_MS) -> bool:
    """Safely click an element with error handling and retry logic."""
    for attempt in range(3):
        try:
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.scroll_into_view_if_needed()
            await human_delay(250)
            await loc.click(force=True)  # robust for overlays
            return True
        except Exception as e:
            warn(f"Click failed on attempt {attempt + 1}: {str(e)[:140]}")
            if attempt < 2:
                await human_delay(600)
    warn("Click failed after multiple attempts.")
    return False

def message_buttons_locator(page: Page) -> Locator:
    # Union of strict selectors (modal-trigger only)
    combo = ", ".join(MESSAGE_BUTTON_SELECTORS)
    return page.locator(combo)

def find_send_button(modal: Locator) -> Locator:
    """
    Build a robust locator for the 'Send' button inside the currently open modal.
    We try (in order):
      1) form#job-responses-messaging-modal-form footer primary submit
      2) any .modal-footer primary submit within this modal
      3) a button with name/text 'Send' (role-based)
    """
    candidates = [
        "form#job-responses-messaging-modal-form .modal-footer button.btn.btn-primary[type='submit']",
        ".modal-footer button.btn.btn-primary[type='submit']",
    ]
    # Chain them with commas to create a union (scoped to modal)
    union = ", ".join(candidates)
    loc = modal.locator(union)
    # Fallback to role+name if needed
    role_fallback = modal.get_by_role("button", name=re.compile(r"^\s*Send\s*$", re.I))
    return loc.first.or_(role_fallback.first)

async def open_fill_and_send(page: Page, message: str) -> bool:
    """Open modal, fill the textarea with message, click Send, confirm modal closed."""
    # Wait for modal visibility
    try:
        modal = page.locator(MESSAGING_MODAL).first
        await modal.wait_for(state="visible", timeout=10000)
        ok("Messaging modal opened.")
    except PWTimeout:
        warn("Messaging modal didn't appear in time.")
        return False

    # Type message into the textarea (scoped to modal)
    try:
        message_box = modal.locator(MESSAGE_TEXTAREA).first
        await message_box.wait_for(state="visible", timeout=8000)
        await message_box.click()
        await message_box.fill("")  # clear just in case
        await human_delay(300)
        await message_box.fill(message)
        ok("Message typed into textarea.")
    except Exception as e:
        warn(f"Failed to type message: {str(e)[:140]}")
        return False

    await human_delay(500)

    if SEND_ENABLED:
        # Build a fresh locator for Send (DOM can re-render after typing)
        send_btn = find_send_button(modal)

        # Wait until present & visible
        try:
            # Wait up to 10s for it to be visible
            await send_btn.wait_for(state="visible", timeout=10000)
        except PWTimeout:
            warn("Send button not visible in modal.")
            return False

        # If the app disables the button until text is present, wait until enabled
        for _ in range(10):
            try:
                if await send_btn.is_enabled():
                    break
            except Exception:
                pass
            await asyncio.sleep(0.3)

        # Scroll and click
        try:
            await send_btn.scroll_into_view_if_needed()
            await human_delay(250)
            if not await safe_click(send_btn, timeout=8000):
                warn("Could not click 'Send' button.")
                return False
            ok("Clicked 'Send'.")
        except Exception as e:
            warn(f"Failed clicking Send: {str(e)[:140]}")
            return False
    else:
        info("SEND_ENABLED=false — skipping the Send click.")

    # Wait for modal to disappear (success path)
    try:
        await modal.wait_for(state="hidden", timeout=15000)
        ok("Modal closed after action.")
    except PWTimeout:
        warn("Modal did not close in time. Message may not have been sent.")
        return False

    # Optional: watch for success toast (non-fatal if missing)
    try:
        await page.wait_for_selector(SUCCESS_MSG, timeout=2500)
        ok("Success indicator detected.")
    except Exception:
        pass

    return True

async def handle_single_talent(page: Page, message_button: Locator, message: str) -> str:
    """
    For one talent: click the Message button, wait for modal, paste message, hit Send.
    Returns: 'sent', 'failed', or 'skipped'.
    """
    # Double-check attribute guard (avoid "View Message" even if selector missed something)
    try:
        has_modal_toggle = await message_button.get_attribute("data-bs-toggle")
        if (has_modal_toggle or "").lower() != "modal":
            return 'skipped'
    except Exception:
        pass

    info("Clicking 'Message'…")
    if not await safe_click(message_button, timeout=8000):
        warn("Failed to click 'Message' button.")
        return 'skipped'

    await human_delay(350)

    if await open_fill_and_send(page, message):
        return 'sent'
    return 'failed'

async def process_all_responses(page: Page, message: str) -> Dict[str, int]:
    """Process all talent responses on this page (open modal, type, send)."""
    stats = {"seen": 0, "sent": 0, "skipped": 0, "failed": 0}

    info("Waiting for 'Message' buttons to become visible…")
    try:
        await page.wait_for_selector(", ".join(MESSAGE_BUTTON_SELECTORS), timeout=DEFAULT_TIMEOUT_MS)
        ok("Found 'Message' buttons. Starting to process responses.")
    except PWTimeout:
        warn("No 'Message' buttons found on this page. Exiting.")
        return stats

    buttons = message_buttons_locator(page)
    count = await buttons.count()
    if count == 0:
        warn("No 'Message' buttons found on this page.")
        return stats

    stats["seen"] = count
    info(f"Found {count} talent responses to process.")

    for i in range(count):
        info(f"\nProcessing talent {i+1}/{count}")
        btn = buttons.nth(i)
        result = await handle_single_talent(page, btn, message)

        if result == 'sent':
            stats["sent"] += 1
        elif result == 'skipped':
            stats["skipped"] += 1
        else:
            stats["failed"] += 1

        # Per-talent delay
        await action_pause()

        # Periodic long pause
        if (i + 1) % LONG_PAUSE_EVERY == 0 and (i + 1) < count:
            info(f"Taking a long pause after {i + 1} messages…")
            await long_pause()

    return stats

# =========================
# Main
# =========================
async def main():
    info("Starting 'Message Talent' automation (send)…")
    info(f"URL: {START_URL}")
    info(f"CDP URL: {CDP_URL}")
    info(f"SEND_ENABLED = {SEND_ENABLED}  (set SEND_ENABLED=false to dry-run)")

    async with async_playwright() as p:
        # Attach to a running debug browser and ensure we have a usable context and page
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        # Prefer an existing open voices.com tab when requested
        try:
            if USE_CURRENT:
                all_pages = []
                for ctx in browser.contexts:
                    for pg in ctx.pages:
                        all_pages.append((ctx, pg))
                if all_pages:
                    def page_rank(item):
                        _, pg = item
                        url = (pg.url or "").lower()
                        score = 0
                        if url.startswith("http"):
                            score += 10
                        if "voices.com" in url:
                            score += 5
                        if url.startswith("about:") or url.startswith("chrome"):
                            score -= 5
                        return score
                    context, page = sorted(all_pages, key=page_rank)[-1]
                cur = (page.url or '').strip()
                if cur:
                    globals()['START_URL'] = cur
                    info("Using current page; will keep existing URL.")
        except Exception:
            pass

        info(f"Navigating to URL: {START_URL}")
        try:
            await page.goto(START_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            info("Waiting briefly for dynamic content…")
            await asyncio.sleep(5)
            ok("Proceeding with element search.")
        except PWTimeout:
            warn("Page navigation took longer than expected but proceeding anyway.")

        await step_pause()

        try:
            totals = await process_all_responses(page, MESSAGE)
            info(
                f"\nSent messages to {totals['sent']} talents "
                f"(seen: {totals['seen']}, skipped: {totals['skipped']}, failed: {totals['failed']})."
            )
        except Exception as e:
            err(f"An error occurred: {str(e)}")

        info("\nDone! Browser remains open.")

if __name__ == "__main__":
    asyncio.run(main())

