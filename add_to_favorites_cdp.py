# add_to_favorites_cdp.py
import asyncio
import os
import random
from playwright.async_api import async_playwright

# ========= Config =========
START_URL = os.getenv("START_URL", "").strip()          # optional; if empty, uses current tab
CDP_URL = os.getenv("DEBUG_URL", "http://127.0.0.1:9222").strip()
SPEED = float(os.getenv("SPEED", "1.0"))
FIRST_HEART_DELAY_MS = int(os.getenv("FIRST_HEART_DELAY_MS", "0"))  # unscaled, default off
MAX_PAGES = int(os.getenv("MAX_PAGES", "999"))

# pacing
BETWEEN_STEPS_MS = int(700 / SPEED)
BETWEEN_FAVORITES_MS = int(1200 / SPEED)
BETWEEN_PAGES_MS = int(1500 / SPEED)

# selectors (adjust if your markup differs)
HEART_ICON = "button.add-to-favorites, i.fa-heart-o, i.fa-heart"
NEXT_PAGE_SELECTOR = """
    a[aria-label='Next']:not(.disabled):not([aria-disabled='true']),
    .pagination a:has(i.fa-angle-right):not(.disabled),
    .pagination button:has(i.fa-angle-right):not(:disabled)
"""

# ===== Logging =====
def info(msg): print(f"\x1b[36m[i]\x1b[0m {msg}")
def ok(msg):   print(f"\x1b[32m[✔]\x1b[0m {msg}")
def warn(msg): print(f"\x1b[33m[!]\\x1b[0m {msg}")
def err(msg):  print(f"\x1b[31m[×]\\x1b[0m {msg}")

# ===== Pacing =====
def r(min_ms, max_ms): return random.uniform(min_ms/1000, max_ms/1000)
async def step_pause(): await asyncio.sleep(r(BETWEEN_STEPS_MS, BETWEEN_STEPS_MS+400))
async def fav_pause():  await asyncio.sleep(r(BETWEEN_FAVORITES_MS, BETWEEN_FAVORITES_MS+800))
async def page_pause(): await asyncio.sleep(r(BETWEEN_PAGES_MS, BETWEEN_PAGES_MS+1000))

async def click_heart_buttons(page):
    stats = {"seen": 0, "hearted": 0, "skipped": 0}
    buttons = page.locator(HEART_ICON)
    count = await buttons.count()
    if count == 0:
        warn("No heart buttons found on this page")
        return stats
    stats["seen"] = count
    info(f"Found {count} talent cards")

    for i in range(count):
        current_btn = buttons.nth(i)
        try:
            await current_btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            await current_btn.click()
            stats["hearted"] += 1
            ok(f"Hearted talent {i+1}/{count}")
        except Exception as e:
            warn(f"Skipped talent {i+1}: {e}")
            stats["skipped"] += 1
        if i < count - 1:
            await fav_pause()
    return stats

async def go_to_next_page(page):
    try:
        next_link = page.locator(NEXT_PAGE_SELECTOR).first
        if await next_link.count() == 0:
            info("No next page link found")
            return False
        is_disabled = await next_link.get_attribute("aria-disabled")
        if is_disabled == "true":
            info("Next page disabled (last page)")
            return False
        await next_link.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
        await next_link.click()
        await page.wait_for_load_state("networkidle", timeout=12000)
        await page_pause()
        return True
    except Exception as e:
        warn(f"Next page failed: {e}")
        return False

async def attach_cdp_get_page(p):
    browser = await p.chromium.connect_over_cdp(CDP_URL)
    # Prefer a context that already has pages
    context = None
    for ctx in browser.contexts:
        if ctx.pages:
            context = ctx
            break
    if context is None:
        # fall back to first context if present
        if browser.contexts:
            context = browser.contexts[0]
        else:
            raise RuntimeError("No browser context found. Start Chrome with --remote-debugging-port and open a tab.")
    if not context.pages:
        raise RuntimeError("No open tabs found. Open a tab (Voices search page), then rerun.")
    return context.pages[0]

async def main():
    info("Add to Favorites — CDP attach mode")
    info(f"CDP: {CDP_URL}")
    if not START_URL:
        warn("START_URL not provided — will act on the current tab's page.")
    async with async_playwright() as p:
        page = await attach_cdp_get_page(p)

        # Navigate only if a START_URL is provided
        if START_URL:
            await page.goto(START_URL, wait_until="domcontentloaded")

        if FIRST_HEART_DELAY_MS > 0:
            # Initial delay disabled by default; use GUI pause when needed
            await asyncio.sleep(FIRST_HEART_DELAY_MS/1000)

        totals = {"seen": 0, "hearted": 0, "skipped": 0}
        page_num = 1
        while page_num <= MAX_PAGES:
            info(f"\n=== Page {page_num} ===")
            stats = await click_heart_buttons(page)
            for k in totals: totals[k] += stats[k]
            info(f"Page {page_num} results: {stats}")
            if not await go_to_next_page(page): break
            page_num += 1

        info("\n=== COMPLETE ===")
        info(f"Seen: {totals['seen']}")
        ok(f"Hearted: {totals['hearted']}")
        warn(f"Skipped: {totals['skipped']}")
        info("Done. (Attached browser remains open.)")

if __name__ == "__main__":
    asyncio.run(main())
