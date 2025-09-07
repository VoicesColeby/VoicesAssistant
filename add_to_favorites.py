# add_to_favorites.py
import asyncio
import os
import re
import random
from typing import Dict
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout

# =======================
# Config (env-overridable)
# =======================
START_URL = os.getenv("START_URL", "https://YOUR_TALENT_RESULTS_URL")
FAVORITE_LIST_NAME = os.getenv("FAVORITE_LIST_NAME", "My Favorites")
CDP_URL = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")

# Timeouts & pacing
DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", "12000"))
BETWEEN_STEPS_MS = int(os.getenv("BETWEEN_STEPS_MS", "600"))
BETWEEN_ACTIONS_MS = int(os.getenv("BETWEEN_ACTIONS_MS", "1200"))
BETWEEN_PAGES_MS = int(os.getenv("BETWEEN_PAGES_MS", "1500"))
MAX_PAGES = int(os.getenv("MAX_PAGES", "999"))

# =======================
# Selectors
# =======================

# Heart icon
HEART_ICON = "i.action-list-btn.fa-heart.fa-lg"

# Favorites dropdown menu container
FAVORITES_DROPDOWN = "div.action-list-dropdown"

# Favorite list button inside the dropdown
FAVORITE_LIST_BTN_BASE = "button.action-list-checkbox-btn:has-text('{}')"

# Pagination
NEXT_PAGE_SELECTOR = """
    a[aria-label='Next']:not(.disabled):not([aria-disabled='true']),
    .pagination a:has(i.fa-angle-right):not(.disabled),
    .pagination button:has(i.fa-angle-right):not(:disabled)
"""

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

async def page_pause():
    await asyncio.sleep(r(BETWEEN_PAGES_MS, BETWEEN_PAGES_MS + 800))

# =========================
# Core Functions
# =========================

async def safe_click(loc: Locator, timeout: int = DEFAULT_TIMEOUT_MS) -> bool:
    """Safely click an element with error handling"""
    try:
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.scroll_into_view_if_needed()
        await human_delay(200)
        await loc.click()
        return True
    except Exception as e:
        warn(f"Click failed: {str(e)[:100]}")
        return False

async def add_to_favorites_single_talent(page: Page, heart_icon: Locator, favorite_list_name: str, favorites_list_selected: bool) -> (str, bool):
    """
    Adds a single talent to a specified favorites list.
    Returns: A tuple of (result, updated_favorites_list_selected_state).
    """

    # Check if the heart icon is already favorited (unselecting behavior)
    # The 'fas' class indicates a filled heart icon
    initial_icon_class = await heart_icon.get_attribute("class")
    initial_is_favorited = "fas" in initial_icon_class

    # Step 1: Click the heart icon to open the dropdown
    info("Clicking heart icon...")
    if not await safe_click(heart_icon, timeout=5000):
        return 'failed', favorites_list_selected

    await human_delay(300)

    # Step 2: Use the parent to find the correct dropdown menu
    try:
        parent_dropdown = heart_icon.locator("..")
        favorites_dropdown = parent_dropdown.locator(FAVORITES_DROPDOWN)
        await favorites_dropdown.wait_for(state="visible", timeout=3000)
    except PWTimeout:
        warn("Favorites dropdown menu didn't appear in time.")
        return 'failed', favorites_list_selected

    # Step 3: Find the specific favorite list button
    info(f"Looking for list: '{favorite_list_name}'")
    list_button_selector = FAVORITE_LIST_BTN_BASE.format(favorite_list_name)
    list_button = favorites_dropdown.locator(list_button_selector)

    # Check if the button for the list exists
    if await list_button.count() == 0:
        warn(f"Could not find favorite list named '{favorite_list_name}'.")
        # Try to close the menu
        await close_favorites_menu(favorites_dropdown)
        return 'failed', favorites_list_selected

    # Check if the talent is already in the target list (active checkbox)
    is_active = "active" in await list_button.get_attribute("class")

    if is_active:
        info(f"Talent is already in list '{favorite_list_name}'.")
        # Do not click again to avoid un-favoriting
        await close_favorites_menu(favorites_dropdown)
        return 'already_favorited', favorites_list_selected

    else:
        # Step 4: Click the list button to add to favorites
        info(f"Adding talent to list '{favorite_list_name}'...")
        if not await safe_click(list_button):
            warn("Could not click favorite list button.")
            await close_favorites_menu(favorites_dropdown)
            return 'failed', favorites_list_selected

        # Wait for the action to complete and menu to close
        await step_pause()
        
        # The action is complete, close the menu
        await close_favorites_menu(favorites_dropdown)
        
        # A simple success check is to see if the heart icon's class has changed
        updated_icon_class = await heart_icon.get_attribute("class")
        if "fas" in updated_icon_class:
            ok(f"Successfully added to list '{favorite_list_name}'.")
            return 'favorited', True
        
        warn("Could not verify that the talent was added.")
        return 'failed', favorites_list_selected


async def close_favorites_menu(favorites_dropdown: Locator):
    """Close the favorites menu if it's still open"""
    try:
        # Click the close button or press Escape
        close_button = favorites_dropdown.locator("button.close")
        if await close_button.count() > 0:
            await safe_click(close_button, timeout=1000)
        else:
            await favorites_dropdown.page.keyboard.press("Escape")
    except Exception:
        pass

async def process_current_page(page: Page, favorite_list_name: str) -> Dict[str, int]:
    """Process all talent cards on the current page"""
    stats = {"seen": 0, "favorited": 0, "already_favorited": 0, "failed": 0}
    
    # State variable to track if we've selected the list on this page
    favorites_list_selected = False

    # Find all heart icons
    heart_icons = page.locator(HEART_ICON)
    count = await heart_icons.count()
    
    if count == 0:
        warn("No talent cards with heart icons found on this page")
        return stats
    
    stats["seen"] = count
    info(f"Found {count} talent cards to process")
    
    for i in range(count):
        info(f"\nProcessing talent {i+1}/{count}")
        
        # Re-query the icon to avoid stale element issues
        current_icon = page.locator(HEART_ICON).nth(i)

        # Check for filled heart icon before any action
        initial_icon_class = await current_icon.get_attribute("class")
        if "fas" in initial_icon_class:
            info("Talent is already favorited. Skipping.")
            stats["already_favorited"] += 1
            await action_pause()
            continue

        # If a list has not been selected on this page, perform the full two-step process
        if not favorites_list_selected:
            result, favorites_list_selected = await add_to_favorites_single_talent(page, current_icon, favorite_list_name, favorites_list_selected)
        else:
            # If a list has already been selected, perform the one-click action
            info("A list has been selected for this page. Clicking heart icon only.")
            if await safe_click(current_icon):
                ok("Successfully added to favorites list.")
                result = 'favorited'
            else:
                warn("Failed to perform one-click favorite action.")
                result = 'failed'

        if result == 'favorited':
            stats["favorited"] += 1
        elif result == 'already_favorited':
            stats["already_favorited"] += 1
        else:
            stats["failed"] += 1
        
        await action_pause()
    
    return stats

async def go_to_next_page(page: Page) -> bool:
    """Navigate to the next page of results"""
    try:
        next_link = page.locator(NEXT_PAGE_SELECTOR).first
        
        if await next_link.count() == 0:
            info("No next page link found")
            return False
        
        is_disabled = await next_link.get_attribute("aria-disabled")
        if is_disabled == "true":
            info("Next page link is disabled (last page)")
            return False
        
        await next_link.scroll_into_view_if_needed()
        await next_link.click()
        
        await page.wait_for_load_state("networkidle", timeout=10000)
        await page_pause()
        
        return True
        
    except Exception as e:
        warn(f"Failed to go to next page: {str(e)[:100]}")
        return False

# =========================
# Main
# =========================
async def main():
    info(f"Starting 'Add to Favorites' automation...")
    info(f"URL: {START_URL}")
    info(f"Favorite List Name: {FAVORITE_LIST_NAME}")
    info(f"CDP URL: {CDP_URL}")
    
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        
        await page.goto(START_URL, wait_until="domcontentloaded")
        await page_pause()
        
        totals = {"seen": 0, "favorited": 0, "already_favorited": 0, "failed": 0}
        page_num = 1
        
        while page_num <= MAX_PAGES:
            info(f"\n{'='*50}")
            info(f"Processing page {page_num}")
            info(f"{'='*50}")
            
            stats = await process_current_page(page, FAVORITE_LIST_NAME)
            
            for key in totals:
                totals[key] += stats.get(key, 0)
            
            info(f"\nPage {page_num} results:")
            info(f"  Seen: {stats['seen']}")
            ok(f"  Favorited: {stats['favorited']}")
            info(f"  Already Favorited: {stats['already_favorited']}")
            if stats['failed'] > 0:
                err(f"  Failed: {stats['failed']}")
            
            if not await go_to_next_page(page):
                info("No more pages to process")
                break
            
            page_num += 1
        
        info(f"\n{'='*50}")
        ok("AUTOMATION COMPLETE")
        info(f"{'='*50}")
        info(f"Total talents seen: {totals['seen']}")
        ok(f"Successfully favorited: {totals['favorited']}")
        info(f"Already favorited: {totals['already_favorited']}")
        if totals['failed'] > 0:
            err(f"Failed: {totals['failed']}")
        
        info("\nDone! Browser remains open.")

if __name__ == "__main__":
    asyncio.run(main())