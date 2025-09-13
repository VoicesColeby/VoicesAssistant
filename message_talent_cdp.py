
import asyncio
import os
import random
from playwright.async_api import async_playwright

# ===== Config =====
START_URL = os.getenv(\"START_URL\", \"\").strip()
MESSAGE = os.getenv(\"MESSAGE\", \"\").strip()
CDP_URL = os.getenv(\"DEBUG_URL\", \"http://127.0.0.1:9222\").strip()

DEFAULT_TIMEOUT_MS = int(os.getenv(\"DEFAULT_TIMEOUT_MS\", \"15000\"))
INITIAL_DELAY_MS   = int(os.getenv(\"INITIAL_DELAY_MS\", \"30000\"))  # let human adjust selections

BETWEEN_STEPS_MS   = int(os.getenv(\"BETWEEN_STEPS_MS\", \"700\"))
BETWEEN_SENDS_MS   = int(os.getenv(\"BETWEEN_SENDS_MS\", \"1800\"))
BETWEEN_PAGES_MS   = int(os.getenv(\"BETWEEN_PAGES_MS\", \"2000\"))
MAX_PAGES          = int(os.getenv(\"MAX_PAGES\", \"999\"))

# ===== Selectors (adjust as needed) =====
MESSAGE_BUTTON = \"button:has-text('Message'), .message-button\"
TEXTAREA = \"textarea[name='message'], .message-textarea, #message\"
SEND_BUTTON = \"button:has-text('Send'), .send-message\"

NEXT_PAGE_SELECTOR = \"\"\"
    a[aria-label='Next']:not(.disabled):not([aria-disabled='true']),
    .pagination a:has(i.fa-angle-right):not(.disabled),
    .pagination button:has(i.fa-angle-right):not(:disabled)
\"\"\"

# ===== Logging =====
def info(msg):  print(f\"\\x1b[36m[i]\\x1b[0m {msg}\")
def ok(msg):    print(f\"\\x1b[32m[✔]\\x1b[0m {msg}\")
def warn(msg):  print(f\"\\x1b[33m[!]\\x1b[0m {msg}\")
def err(msg):   print(f\"\\x1b[31m[×]\\x1b[0m {msg}\")

def r(min_ms: int, max_ms: int) -> float:
    import random
    return random.uniform(min_ms/1000, max_ms/1000)

async def step_pause():
    await asyncio.sleep(r(BETWEEN_STEPS_MS, BETWEEN_STEPS_MS + 400))

async def send_pause():
    await asyncio.sleep(r(BETWEEN_SENDS_MS, BETWEEN_SENDS_MS + 900))

async def page_pause():
    await asyncio.sleep(r(BETWEEN_PAGES_MS, BETWEEN_PAGES_MS + 1000))

async def safe_click(page, selector: str) -> bool:
    try:
        loc = page.locator(selector).first
        await loc.wait_for(state=\"visible\", timeout=DEFAULT_TIMEOUT_MS)
        await loc.scroll_into_view_if_needed()
        await loc.click()
        return True
    except Exception as e:
        warn(f\"Click failed on {selector}: {e}\")
        return False

async def process_current_page(page):
    stats = {\"seen\": 0, \"sent\": 0, \"skipped\": 0}
    buttons = page.locator(MESSAGE_BUTTON)
    count = await buttons.count()
    if count == 0:
        warn(\"No 'Message' buttons found on this page\")
        return stats
    stats[\"seen\"] = count
    info(f\"Found {count} talents with message button\")

    for i in range(count):
        btn = buttons.nth(i)
        try:
            await btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            await btn.click()
            await step_pause()

            # Fill textarea
            ta = page.locator(TEXTAREA).first
            await ta.wait_for(state=\"visible\", timeout=DEFAULT_TIMEOUT_MS)
            await ta.fill(MESSAGE)
            await step_pause()

            # Send
            if await safe_click(page, SEND_BUTTON):
                ok(f\"Sent message to talent {i+1}/{count}\")
                stats[\"sent\"] += 1
            else:
                stats[\"skipped\"] += 1

        except Exception as e:
            warn(f\"Skipped talent {i+1}: {e}\")
            stats[\"skipped\"] += 1

        if i < count - 1:
            await send_pause()

    return stats

async def go_to_next_page(page):
    try:
        next_link = page.locator(NEXT_PAGE_SELECTOR).first
        if await next_link.count() == 0:
            info(\"No next page link found\")
            return False
        is_disabled = await next_link.get_attribute(\"aria-disabled\")
        if is_disabled == \"true\":
            info(\"Next page link disabled (last page)\")
            return False
        await next_link.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
        await next_link.click()
        await page.wait_for_load_state(\"networkidle\", timeout=12000)
        await page_pause()
        return True
    except Exception as e:
        warn(f\"Next page failed: {e}\")
        return False

async def main():
    if not MESSAGE:
        raise SystemExit(\"MESSAGE env var required.\")
    info(\"Message Talent — CDP attach mode\")
    info(f\"CDP: {CDP_URL}\")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else None
        if not context:
            raise RuntimeError(\"No browser context found. Ensure Chrome is running with --remote-debugging-port.\")
        pages = context.pages
        if not pages:
            raise RuntimeError(\"No open tabs found. Open a tab (preferably the Voices search page), then rerun.\")
        page = pages[0]
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        if START_URL:
            await page.goto(START_URL, wait_until=\"domcontentloaded\")

        if INITIAL_DELAY_MS > 0:
            info(f\"Initial delay: {INITIAL_DELAY_MS} ms to let you adjust selections…\")
            await asyncio.sleep(INITIAL_DELAY_MS / 1000.0)

        totals = {\"seen\": 0, \"sent\": 0, \"skipped\": 0}
        page_num = 1
        while page_num <= MAX_PAGES:
            info(f\"\\n=== Page {page_num} ===\")
            stats = await process_current_page(page)
            for k in totals: totals[k] += stats[k]
            info(f\"Page {page_num} results: {stats}\")
            if not await go_to_next_page(page): break
            page_num += 1

        info(\"\\n=== COMPLETE ===\")
        info(f\"Seen: {totals['seen']}\")
        ok(f\"Sent: {totals['sent']}\")
        warn(f\"Skipped: {totals['skipped']}\")
        info(\"Done. (Attached browser remains open.)\")

if __name__ == \"__main__\":
    asyncio.run(main())
