import asyncio
from typing import Optional, Set

from playwright.async_api import async_playwright, TimeoutError as PWTimeout


JOB_RESPONSES_URL = "https://www.voices.com/client/jobs/responses/818318"
MESSAGE_TEXT = "can you please complete this survey for your rate"


async def message_all_responses(
    job_url: str = JOB_RESPONSES_URL,
    storage_state: Optional[str] = "voices_auth_state.json",
    headless: bool = False,
    slow_mo: int = 60,
    per_pass_scroll: int = 1200,
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = await browser.new_context(storage_state=storage_state)
        page = await context.new_page()

        await page.goto(job_url)
        # Wait up to 2 minutes for the first batch of Message buttons (login, loading, etc.)
        try:
            await page.wait_for_selector("button:has-text('Message')", timeout=120000)
        except PWTimeout:
            print("Timeout waiting for Message buttons. Ensure you are logged in.")
            await context.close()
            await browser.close()
            return

        processed: Set[str] = set()
        while True:
            msg_buttons = page.locator("button:has-text('Message')")
            count = await msg_buttons.count()
            new_found = False

            for i in range(count):
                try:
                    btn = msg_buttons.nth(i)
                    if not await btn.is_visible():
                        continue

                    # Use a nearby text snapshot as a crude unique key to avoid double-processing
                    try:
                        key = await btn.evaluate(
                            "el => (el.closest('[data-testid]')?.innerText || el.closest('tr,li,div')?.innerText || '').substr(0,200)"
                        )
                    except Exception:
                        key = f"idx:{i}"
                    if key in processed:
                        continue

                    await btn.scroll_into_view_if_needed()
                    await btn.click()

                    # Modal handling
                    modal = page.locator("[role='dialog'], .modal.show, .modal.in").first
                    await modal.wait_for(state="visible", timeout=10000)

                    # Fill the textarea
                    textarea = modal.locator("textarea").first
                    await textarea.wait_for(state="attached", timeout=5000)
                    await textarea.fill(MESSAGE_TEXT)

                    # Cancel (do not send)
                    cancel = modal.locator("button:has-text('Cancel')").first
                    if await cancel.count():
                        await cancel.click()
                    else:
                        # Fallback: close icon or ESC
                        close_x = modal.locator("button:has-text('Close'), .close, [aria-label='Close']").first
                        if await close_x.count():
                            await close_x.click()
                        else:
                            await page.keyboard.press("Escape")

                    await modal.wait_for(state="hidden", timeout=10000)
                    processed.add(key)
                    new_found = True
                except Exception:
                    # Move on to next button if one fails
                    continue

            if not new_found:
                # Try to load more by scrolling; if count does not increase, we are done
                prev_count = count
                await page.mouse.wheel(0, per_pass_scroll)
                await page.wait_for_timeout(600)
                if await page.locator("button:has-text('Message')").count() <= prev_count:
                    break

        await context.close()
        await browser.close()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Open Message modal for each job response, fill text, and cancel.")
    ap.add_argument("--url", default=JOB_RESPONSES_URL, help="Voices job responses URL")
    ap.add_argument("--text", default=MESSAGE_TEXT, help="Message text to fill (will not be sent)")
    ap.add_argument("--headless", action="store_true", help="Run headless")
    ap.add_argument("--slow-mo", type=int, default=60, help="Slow-mo in ms")
    args = ap.parse_args()

    # Allow overriding globals via CLI without changing defaults
    JOB_RESPONSES_URL = args.url
    MESSAGE_TEXT = args.text
    asyncio.run(message_all_responses(job_url=JOB_RESPONSES_URL, headless=bool(args.headless), slow_mo=int(args.slow_mo)))

