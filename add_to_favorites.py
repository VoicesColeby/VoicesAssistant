import asyncio
import os
import random
from playwright.async_api import async_playwright

# ================== Config ==================
START_URL = os.getenv("START_URL", "https://www.voices.com/talents/search")
CDP_URL = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")
SPEED = float(os.getenv("SPEED", "1.0"))
SPEED_FILE = os.getenv("SPEED_FILE", "").strip()
FIRST_HEART_DELAY_MS = int(os.getenv("FIRST_HEART_DELAY_MS", "30000"))  # unscaled
MAX_PAGES = int(os.getenv("MAX_PAGES", "999"))

# pacing (base values; live speed scaling applied via r())
BASE_BETWEEN_STEPS_MS = 700
BASE_BETWEEN_FAVORITES_MS = 1200
BASE_BETWEEN_PAGES_MS = 1500

# selectors
HEART_ICON = "button.add-to-favorites, i.fa-heart-o, i.fa-heart"  # adjust to match real markup
NEXT_PAGE_SELECTOR = """
    a[aria-label='Next']:not(.disabled):not([aria-disabled='true']),
    .pagination a:has(i.fa-angle-right):not(.disabled),
    .pagination button:has(i.fa-angle-right):not(:disabled)
"""

# ============== Logging helpers ==============
def info(msg): print(f"\x1b[36m[i]\x1b[0m {msg}")
def ok(msg):   print(f"\x1b[32m[✔]\x1b[0m {msg}")
def warn(msg): print(f"\x1b[33m[!]\x1b[0m {msg}")
def err(msg):  print(f"\x1b[31m[×]\x1b[0m {msg}")

# ============== Randomized pacing (live) ==============
def _read_speed_file() -> float:
    try:
        if SPEED_FILE and os.path.exists(SPEED_FILE):
            with open(SPEED_FILE, 'r', encoding='utf-8') as f:
                v = float((f.read() or '5').strip())
                return max(1.0, min(5.0, v))
    except Exception:
        pass
    try:
        return max(1.0, min(5.0, float(os.getenv("SPEED", str(SPEED)))))
    except Exception:
        return 5.0

def r(min_ms, max_ms):
    s = _read_speed_file()
    lo = min_ms / s
    hi = max_ms / s
    return random.uniform(lo/1000, hi/1000)

async def step_pause(): await asyncio.sleep(r(BASE_BETWEEN_STEPS_MS, BASE_BETWEEN_STEPS_MS+400))
async def fav_pause():  await asyncio.sleep(r(BASE_BETWEEN_FAVORITES_MS, BASE_BETWEEN_FAVORITES_MS+800))
async def page_pause(): await asyncio.sleep(r(BASE_BETWEEN_PAGES_MS, BASE_BETWEEN_PAGES_MS+1000))

# ============== Core ==============
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
        if i < count-1:
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
            info("Next page link disabled (last page)")
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

# ============== Main ==============
async def main():
    info("Starting 'Add to Favorites'")
    info(f"URL: {START_URL}")
    info(f"CDP: {CDP_URL}")
    info(f"SPEED: {SPEED}")
    info(f"FIRST_HEART_DELAY_MS: {FIRST_HEART_DELAY_MS} (unscaled, first page only)")

    async with async_playwright() as p:
        # Robust connection
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            info("Attached to existing Chrome via CDP")
            # If user prefers current page, try to keep the current tab and URL
            try:
                if use_current:
                    # Prefer an existing voices.com page if available
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
                        try:
                            globals()['FIRST_HEART_DELAY_MS'] = 0
                        except Exception:
                            pass
                        info("Using current page; will keep existing URL.")
            except Exception:
                pass
        except Exception as cdp_err:
            warn(f"Could not attach over CDP ({cdp_err}). Falling back...")
            user_data = os.getenv("CHROME_USER_DATA", "").strip()
            if user_data:
                info(f"Launching persistent context with CHROME_USER_DATA={user_data}")
                context = await p.chromium.launch_persistent_context(user_data, headless=False, args=[])
                page = context.pages[0] if context.pages else await context.new_page()
            else:
                info("Launching fresh browser (you may need to log in)")
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context()
                page = await context.new_page()

        # Navigate
        await page.goto(START_URL, wait_until="domcontentloaded")
        if FIRST_HEART_DELAY_MS > 0:
            info(f"Initial delay {FIRST_HEART_DELAY_MS}ms — select list if needed...")
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
        info("Done. Browser stays open.")

if __name__ == "__main__":
    asyncio.run(main())
