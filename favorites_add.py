import asyncio
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout


SEARCH_URL = "https://www.voices.com/talents/search?keywords=&language_ids=1"
FAVORITES_LIST_TITLE = "My List"

# Favorites selectors (mirrors invite_all.py defaults)
FAVORITE_BTN = ", ".join([
    ".action-list-btn.fa-heart",
    "i.fa-heart",
    "[aria-label*='Save to Favorites' i]",
    "[title*='Save to Favorites' i]",
    "[title*='Favorite' i]",
    "[title*='Favourites' i]",
])
FAVORITES_UI_CONTAINERS = ":is([role='dialog'], [role='menu'], [role='listbox'], .modal.show, .dropdown-menu, .popover, .ReactModal__Content)"
FAVORITE_SUCCESS = ":is(.Toastify__toast, [role='status']):has-text('Saved'), :has-text('Added to Favorites'), :has-text('Favourites'), :has-text('Added to list'), :has-text('saved')"


async def add_all_to_favorites(
    search_url: str = SEARCH_URL,
    list_title: str = FAVORITES_LIST_TITLE,
    storage_state: Optional[str] = "voices_auth_state.json",
    headless: bool = False,
    slow_mo: int = 60,
    max_pages: int = 1,
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = await browser.new_context(storage_state=storage_state)
        page = await context.new_page()

        await page.goto(search_url)
        try:
            await page.wait_for_load_state("networkidle")
        except PWTimeout:
            await page.wait_for_load_state("domcontentloaded")

        pages_done = 0
        total_clicked = 0
        while pages_done < max_pages:
            # Scroll to load
            for _ in range(2):
                await page.mouse.wheel(0, 20000)
                await asyncio.sleep(0.5)

            hearts = page.locator(FAVORITE_BTN)
            count = await hearts.count()
            if count == 0:
                # No heart icons found; try small scroll then break
                await page.mouse.wheel(0, 2000)
                await asyncio.sleep(0.3)
                count = await hearts.count()
                if count == 0:
                    break

            for i in range(count):
                try:
                    h = hearts.nth(i)
                    if not await h.is_visible():
                        continue
                    await h.scroll_into_view_if_needed()
                    await h.click()

                    # Choose the list if chooser appears; otherwise rely on default behavior
                    chooser = page.locator(FAVORITES_UI_CONTAINERS).first
                    try:
                        await chooser.wait_for(state="visible", timeout=2000)
                        # Select the item with given title
                        item = chooser.locator(":is(span.no-overflow, [role='option'], [role='menuitem'], button, a)", has_text=list_title).first
                        if await item.count():
                            try:
                                await item.click()
                            except Exception:
                                # Try clickable ancestor
                                await item.locator("xpath=ancestor-or-self::*[self::button or self::a or self::label or self::li or self::div][1]").first.click()
                    except Exception:
                        pass

                    # Wait for success toast or chooser to disappear
                    try:
                        await page.wait_for_selector(FAVORITE_SUCCESS, timeout=2500)
                    except Exception:
                        try:
                            await chooser.wait_for(state="hidden", timeout=1200)
                        except Exception:
                            pass

                    total_clicked += 1
                    await asyncio.sleep(0.2)
                except Exception:
                    continue

            # Go to next page if pagination is available
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.3)
                next_link = page.locator("nav[aria-label='Pagination'] >> text=Next").first
                if await next_link.count():
                    await next_link.click()
                    try:
                        await page.wait_for_load_state("networkidle")
                    except PWTimeout:
                        await page.wait_for_load_state("domcontentloaded")
                    pages_done += 1
                    continue
            except Exception:
                pass
            break

        print(f"Favorited on this run: {total_clicked}")
        await context.close()
        await browser.close()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Add visible talents on a search page to a Favorites list.")
    ap.add_argument("--url", default=SEARCH_URL, help="Search URL to process")
    ap.add_argument("--list", dest="list_title", default=FAVORITES_LIST_TITLE, help="Favorites list title")
    ap.add_argument("--headless", action="store_true", help="Run headless")
    ap.add_argument("--slow-mo", type=int, default=60, help="Slow-mo in ms")
    ap.add_argument("--pages", type=int, default=1, help="Max pages to process")
    args = ap.parse_args()

    asyncio.run(
        add_all_to_favorites(
            search_url=args.url,
            list_title=args.list_title,
            headless=bool(args.headless),
            slow_mo=int(args.slow_mo),
            max_pages=int(args.pages),
        )
    )

