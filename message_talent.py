# message_talent.py — open (but do not send) message modals for each talent

import asyncio
import os
import random
from typing import Dict
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout

# =======================
# Config (env-overridable)
# =======================
START_URL = os.getenv("START_URL", "https://YOUR_JOB_RESPONSES_URL")
CDP_URL = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")

# Timeouts & pacing
DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", "60000"))
BETWEEN_STEPS_MS = int(os.getenv("BETWEEN_STEPS_MS", "600"))
BETWEEN_ACTIONS_MS = int(os.getenv("BETWEEN_ACTIONS_MS", "1200"))

# =======================
# Selectors
# =======================

# The 'Message' button for each talent (attribute-driven; resilient to text/whitespace changes)
MESSAGE_BUTTON_SELECTORS = [
    "a.btn.btn-default[role='button'][data-bs-toggle='modal'][data-bs-target='#job-responses-messaging-modal']",
    "a.btn.btn-default[role='button'][data-bs-toggle='modal']",
    "a.btn.btn-default[role='button']",
]

# Messaging modal
MESSAGING_MODAL = "#job-responses-messaging-modal"

# Common ways to close a Bootstrap modal
MODAL_CLOSE_SELECTORS = [
    "#job-responses-messaging-modal button.btn-close",
    "#job-responses-messaging-modal [data-bs-dismiss='modal']",
    ".modal.show button.btn-close",
    ".modal.show [data-bs-dismiss='modal']",
]

# =======================
# Logging
# =======================
def info(msg: str): print(f"\x1b[36m[i]\x1b[0m {msg}")
def ok(msg: str): print(f"\x1b[32m[✔]\x1b[0m {msg}")
def warn(msg: str): print(f"\x1b[33m[!]\x1b[0m {msg}")
def err(msg: str): print(f"\x1b[31m[×]\x1b[0m {msg}")

# =======================
# Humanization
# =======================
def r(min_ms: int, max_ms: int) -> float:
    return random.uniform(min_ms / 1000, max_ms / 1000)

async def human_delay(base_ms: int = 300):
    await asyncio.sleep(r(base_ms, base_ms + 200))

async def step_pause():
    await asyncio.sleep(r(BETWEEN_STEPS_MS, BETWEEN_STEPS_MS + 300))

async def action_pause():
    await asyncio.sleep(r(BETWEEN_ACTIONS_MS, BETWEEN_ACTIONS_MS + 600))

# =========================
# Core Functions
# =========================

async def safe_click(loc: Locator, timeout: int = DEFAULT_TIMEOUT_MS) -> bool:
    """Safely click an element with error handling and retry logic"""
    for attempt in range(3):
        try:
            await loc.wait_for(state="visible", timeout=timeout)
            await loc.scroll_into_view_if_needed()
            await human_delay(200)
            # More robust: sometimes Bootstrap overlays or small offsets block normal clicks
            await loc.click(force=True)
            return True
        except Exception as e:
            warn(f"Click failed on attempt {attempt + 1}: {str(e)[:100]}")
            if attempt < 2:
                await human_delay(500)
    warn("Click failed after multiple attempts.")
    return False

def message_buttons_locator(page: Page) -> Locator:
    # Build a union of selectors so we catch minor DOM variations
    combo = ", ".join(MESSAGE_BUTTON_SELECTORS)
    return page.locator(combo)

async def open_then_close_modal(page: Page) -> bool:
    """Wait for Voices messaging modal to be visible, then close it cleanly."""
    try:
        modal = page.locator(MESSAGING_MODAL).first
        await modal.wait_for(state="visible", timeout=8000)
        ok("Messaging modal opened.")
    except PWTimeout:
        warn("Messaging modal didn't appear in time.")
        return False

    # Try to close via a close button or data-bs-dismiss
    for sel in MODAL_CLOSE_SELECTORS:
        btn = page.locator(sel).first
        try:
            if await btn.count() > 0:
                await safe_click(btn, timeout=3000)
                break
        except Exception:
            continue

    # Fallback: press Escape to dismiss
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass

    # Confirm closed
    try:
        await page.locator(MESSAGING_MODAL).first.wait_for(state="hidden", timeout=8000)
        ok("Modal closed.")
        return True
    except PWTimeout:
        warn("Modal did not close as expected.")
        return False

async def ping_single_talent(page: Page, message_button: Locator) -> str:
    """
    For one talent: click the Message button, wait for the modal to open, then close it.
    Returns: 'opened', 'failed', or 'skipped'.
    """
    info("Clicking 'Message'…")
    if not await safe_click(message_button, timeout=5000):
        warn("Failed to click 'Message' button.")
        return 'skipped'

    await human_delay(250)

    if await open_then_close_modal(page):
        return 'opened'
    return 'failed'

async def process_all_responses(page: Page) -> Dict[str, int]:
    """Process all talent responses on the single page (open & close message modals)."""
    stats = {"seen": 0, "opened": 0, "skipped": 0, "failed": 0}

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
        result = await ping_single_talent(page, btn)

        if result == 'opened':
            stats["opened"] += 1
        elif result == 'skipped':
            stats["skipped"] += 1
        else:
            stats["failed"] += 1

        await action_pause()

    return stats

# =========================
# Main
# =========================
async def main():
    info("Starting 'Message Talent' automation (open-only)…")
    info(f"URL: {START_URL}")
    info(f"CDP URL: {CDP_URL}")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

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
            totals = await process_all_responses(page)
            info(f"\nOpened message modals for {totals['opened']} talents "
                 f"(seen: {totals['seen']}, skipped: {totals['skipped']}, failed: {totals['failed']}).")
        except Exception as e:
            err(f"An error occurred: {str(e)}")

        info("\nDone! Browser remains open.")

if __name__ == "__main__":
    asyncio.run(main())
