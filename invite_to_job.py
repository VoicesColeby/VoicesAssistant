# invite_to_job_fixed.py
import asyncio
import os
import re
import random
from typing import Optional, Dict
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout

# =======================
# Config (env-overridable)
# =======================
START_URL = os.getenv("START_URL", "https://YOUR_TALENT_RESULTS_URL")
JOB_QUERY = os.getenv("JOB_QUERY", "#805775")   # '#12345' or a unique title substring
CDP_URL   = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")

# Timeouts & pacing (slow & human)
DEFAULT_TIMEOUT_MS   = int(os.getenv("DEFAULT_TIMEOUT_MS", "12000"))
RETRY_ATTEMPTS       = int(os.getenv("RETRY_ATTEMPTS", "3"))
PER_CLICK_DELAY_MS   = int(os.getenv("PER_CLICK_DELAY_MS", "350"))
BETWEEN_STEPS_MS     = int(os.getenv("BETWEEN_STEPS_MS", "600"))
BETWEEN_INVITES_MS   = int(os.getenv("BETWEEN_INVITES_MS", "1200"))
BETWEEN_PAGES_MS     = int(os.getenv("BETWEEN_PAGES_MS", "1500"))
SCROLL_STEP_WAIT_MS  = int(os.getenv("SCROLL_STEP_WAIT_MS", "240"))
MAX_PAGES            = int(os.getenv("MAX_PAGES", "999"))

# =======================
# Updated Selectors
# =======================

# Main invite button (with dropdown caret)
INVITE_BUTTON_WITH_DROPDOWN = "button.headbtn.btn.btn-primary:has(i.fa-caret-down)"

# The dropdown menu container
DROPDOWN_MENU = ".dropdown-content, .downmenu .dropdown-content"

# "Invite to Existing Job" button inside dropdown
INVITE_EXISTING_BTN = "button.request_a_quote_btn:has-text('Invite to Existing Job')"

# Modal selectors
MODAL_VISIBLE = ".modal.show, .modal.fade.show, .modal:visible"
MODAL_CONTENT = ".modal-content"
MODAL_BODY = ".modal-body"

# Job dropdown in modal (Choices.js wrapper)
CHOICES_CONTAINER = ".choices[data-type='select-one']"
CHOICES_INNER = ".choices__inner"
CHOICES_SINGLE_ITEM = ".choices__list--single .choices__item"
CHOICES_DROPDOWN_LIST = ".choices__list--dropdown"
CHOICES_DROPDOWN_ITEMS = ".choices__list--dropdown .choices__item--choice"

# Native select (hidden but still there)
NATIVE_SELECT = "#request-quote-open-jobs-list"

# Final submit button
MODAL_SUBMIT_BTN = "#submit-request-quote"

# Success/Error messages
SUCCESS_MSG = ".toast-success, .alert-success, .success-message"
ERROR_MSG = ".toast-error, .alert-danger, .error-message"
ALREADY_INVITED_MSG = "[text*='already received'], [text*='already invited']"

# Pagination
NEXT_PAGE_SELECTOR = """
    a[aria-label='Next']:not(.disabled):not([aria-disabled='true']),
    .pagination a:has(i.fa-angle-right):not(.disabled),
    .pagination button:has(i.fa-angle-right):not(:disabled)
"""

# ==============
# Logging
# ==============
def info(msg: str):  print(f"\x1b[36m[i]\x1b[0m {msg}")
def ok(msg: str):    print(f"\x1b[32m[✔]\x1b[0m {msg}")
def warn(msg: str):  print(f"\x1b[33m[!]\x1b[0m {msg}")
def err(msg: str):   print(f"\x1b[31m[×]\x1b[0m {msg}")

# ==============
# Humanization
# ==============
def r(min_ms: int, max_ms: int) -> float:
    return random.uniform(min_ms/1000, max_ms/1000)

async def human_delay(base_ms: int = 300):
    await asyncio.sleep(r(base_ms, base_ms + 200))

async def step_pause():
    await asyncio.sleep(r(BETWEEN_STEPS_MS, BETWEEN_STEPS_MS + 300))

async def invite_pause():
    await asyncio.sleep(r(BETWEEN_INVITES_MS, BETWEEN_INVITES_MS + 600))

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

async def wait_for_element(page: Page, selector: str, timeout: int = DEFAULT_TIMEOUT_MS) -> bool:
    """Wait for element to be visible"""
    try:
        await page.wait_for_selector(selector, state="visible", timeout=timeout)
        return True
    except PWTimeout:
        return False

async def invite_single_talent(page: Page, invite_btn: Locator, job_query: str) -> str:
    """
    Process a single talent invitation
    Returns: 'success', 'already', 'skipped', or 'failed'
    """
    
    # Step 1: Click the main "Invite to Job" button with dropdown
    info("Clicking invite button dropdown...")
    if not await safe_click(invite_btn, timeout=5000):
        return 'skipped'
    
    await human_delay(300)
    
    # Step 2: Use the parent of the clicked button to find the dropdown.
    info("Waiting for and clicking 'Invite to Existing Job'...")
    try:
        # Get the parent element of the clicked button.
        parent_downmenu = invite_btn.locator("..")
        # Find the dropdown menu within that specific parent.
        dropdown_menu = parent_downmenu.locator(DROPDOWN_MENU)
        
        await dropdown_menu.wait_for(state="visible", timeout=3000)
        
        # The 'Invite to Existing Job' button is inside this dropdown.
        existing_btn = dropdown_menu.locator(INVITE_EXISTING_BTN)
        if not await safe_click(existing_btn, timeout=3000):
            warn("Could not click 'Invite to Existing Job'")
            return 'skipped'
    except PWTimeout:
        warn("Dropdown menu didn't appear in time.")
        return 'skipped'
    
    await step_pause()
    
    # Step 3: Wait for modal to appear
    info("Waiting for modal to appear...")
    if not await wait_for_element(page, MODAL_VISIBLE, timeout=5000):
        warn("Modal didn't appear")
        return 'skipped'
    
    info("Modal opened successfully")
    await human_delay(500)
    
    # Step 4: Select the job from dropdown in the modal
    success = await select_job_in_modal(page, job_query)
    if not success:
        warn("Failed to select job")
        await close_modal(page)
        return 'skipped'
    
    await step_pause()
    
    # Step 5: Click the final "Invite to Job" button in the modal
    info("Clicking final submit button...")
    submit_btn = page.locator(MODAL_SUBMIT_BTN).first
    if not await safe_click(submit_btn):
        warn("Could not click submit button")
        await close_modal(page)
        return 'skipped'
    
    # Step 6: Wait for result
    await human_delay(1000)
    result = await check_invitation_result(page)
    
    # Close modal if still open
    await close_modal(page)
    
    return result

async def select_job_in_modal(page: Page, job_query: str) -> bool:
    """
    Select a job in the modal dropdown (Choices.js)
    """
    info(f"Selecting job: {job_query}")
    
    # Extract job ID if present
    job_id_match = re.search(r"#\s*(\d+)", job_query)
    job_id = job_id_match.group(1) if job_id_match else None
    
    # Method 1: Try clicking the Choices.js dropdown
    try:
        # Get the modal content locator first to scope the search.
        modal = page.locator(MODAL_CONTENT).first
        
        # Now find the choices container within the modal.
        choices_container = modal.locator(CHOICES_CONTAINER)
        
        await choices_container.wait_for(state="visible", timeout=3000)
        await choices_container.click()
        await human_delay(300)
        
        # The dropdown list becomes visible after the click.
        # Find the dropdown list within the modal.
        dropdown = modal.locator(CHOICES_DROPDOWN_LIST)
        
        await dropdown.wait_for(state="visible", timeout=2000)
        
        # Find and click the matching option
        if job_id:
            # Try to find by data-value attribute
            option = dropdown.locator(f'[data-value="{job_id}"]').first
            if await option.count() > 0:
                await option.click()
                info(f"Selected job by ID: {job_id}")
                return True
        
        # Fallback: Find by text content         options = dropdown.locator(CHOICES_DROPDOWN_ITEMS)
        count = await options.count()
        
        for i in range(count):
            opt = options.nth(i)
            text = await opt.inner_text()
            if job_query.lower() in text.lower():
                await opt.click()
                info(f"Selected job by text match")
                return True
                
    except Exception as e:
        warn(f"Choices.js method failed: {str(e)[:100]}")
    
    # Method 2: Fallback to setting native select value directly
    try:
        info("Trying native select fallback...")
        
        if job_id:
            # Set value directly on the hidden select.
            success = await page.evaluate("""
                (jobId) => {
                    const select = document.querySelector('#request-quote-open-jobs-list');
                    if (!select) return false;
                    
                    // Find option with matching value
                    const option = Array.from(select.options).find(o => o.value === jobId);
                    if (!option) return false;
                    
                    // Set the value
                    select.value = jobId;
                    
                    // Trigger change events
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    select.dispatchEvent(new Event('input', { bubbles: true }));
                    
                    // Update Choices.js display if it exists
                    const choicesItem = document.querySelector('.choices__list--single .choices__item');
                    if (choicesItem) {
                        choicesItem.textContent = option.textContent;
                    }
                    
                    return true;
                }
            """, job_id)
            
            if success:
                info("Selected job using native select")
                return True
                
    except Exception as e:
        warn(f"Native select method failed: {str(e)[:100]}")
    
    return False

async def check_invitation_result(page: Page) -> str:
    """
    Check the result of the invitation attempt
    Returns: 'success', 'already', or 'failed'
    """
    # Wait a bit for any messages to appear
    await page.wait_for_timeout(2000)
    
    # Check for success message
    if await page.locator(SUCCESS_MSG).count() > 0:
        ok("Invitation sent successfully!")
        return 'success'
    
    # Check for "already invited" message
    if await page.locator(ALREADY_INVITED_MSG).count() > 0:
        info("Talent was already invited")
        return 'already'
    
    # Check for any error message
    if await page.locator(ERROR_MSG).count() > 0:
        error_text = await page.locator(ERROR_MSG).first.inner_text()
        if 'already' in error_text.lower():
            info("Talent was already invited")
            return 'already'
        else:
            warn(f"Error: {error_text[:100]}")
            return 'failed'
    
    # No clear result
    warn("Could not determine invitation result")
    return 'failed'

async def close_modal(page: Page):
    """Close modal if it's still open"""
    try:
        if await page.locator(MODAL_VISIBLE).count() > 0:
            await page.keyboard.press("Escape")
            await human_delay(300)
    except Exception:
        pass

async def process_current_page(page: Page, job_query: str) -> Dict[str, int]:
    """Process all talent cards on the current page"""
    stats = {"seen": 0, "invited": 0, "already": 0, "skipped": 0, "failed": 0}
    
    # Find all invite buttons with dropdowns
    invite_buttons = page.locator(INVITE_BUTTON_WITH_DROPDOWN)
    count = await invite_buttons.count()
    
    if count == 0:
        warn("No invite buttons found on this page")
        return stats
    
    stats["seen"] = count
    info(f"Found {count} talent cards to process")
    
    for i in range(count):
        info(f"\nProcessing talent {i+1}/{count}")
        
        # Re-query the button to avoid stale element issues
        current_button = page.locator(INVITE_BUTTON_WITH_DROPDOWN).nth(i)
        
        result = await invite_single_talent(page, current_button, job_query)
        
        if result == 'success':
            stats["invited"] += 1
        elif result == 'already':
            stats["already"] += 1
        elif result == 'skipped':
            stats["skipped"] += 1
        else:
            stats["failed"] += 1
        
        # Pause between invitations
        if i < count - 1:
            await invite_pause()
    
    return stats

async def go_to_next_page(page: Page) -> bool:
    """Navigate to the next page of results"""
    try:
        next_link = page.locator(NEXT_PAGE_SELECTOR).first
        
        if await next_link.count() == 0:
            info("No next page link found")
            return False
        
        # Check if it's disabled
        is_disabled = await next_link.get_attribute("aria-disabled")
        if is_disabled == "true":
            info("Next page link is disabled (last page)")
            return False
        
        # Click next page
        await next_link.scroll_into_view_if_needed()
        await next_link.click()
        
        # Wait for page to load
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
    info(f"Starting automation...")
    info(f"URL: {START_URL}")
    info(f"Job Query: {JOB_QUERY}")
    info(f"CDP URL: {CDP_URL}")
    
    async with async_playwright() as p:
        # Connect to existing browser
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        
        # Navigate to the start URL
        await page.goto(START_URL, wait_until="domcontentloaded")
        await page_pause()
        
        # Process pages
        totals = {"seen": 0, "invited": 0, "already": 0, "skipped": 0, "failed": 0}
        page_num = 1
        
        while page_num <= MAX_PAGES:
            info(f"\n{'='*50}")
            info(f"Processing page {page_num}")
            info(f"{'='*50}")
            
            stats = await process_current_page(page, JOB_QUERY)
            
            # Update totals
            for key in totals:
                totals[key] += stats.get(key, 0)
            
            # Print page stats
            info(f"\nPage {page_num} results:")
            info(f"  Seen: {stats['seen']}")
            ok(f"  Invited: {stats['invited']}")
            info(f"  Already invited: {stats['already']}")
            warn(f"  Skipped: {stats['skipped']}")
            if stats['failed'] > 0:
                err(f"  Failed: {stats['failed']}")
            
            # Try to go to next page
            if not await go_to_next_page(page):
                info("No more pages to process")
                break
            
            page_num += 1
        
        # Print final summary
        info(f"\n{'='*50}")
        ok("AUTOMATION COMPLETE")
        info(f"{'='*50}")
        info(f"Total talents seen: {totals['seen']}")
        ok(f"Successfully invited: {totals['invited']}")
        info(f"Already invited: {totals['already']}")
        warn(f"Skipped: {totals['skipped']}")
        if totals['failed'] > 0:
            err(f"  Failed: {totals['failed']}")
        
        # Don't close the browser since it's controlled externally
        info("\nDone! Browser remains open.")

if __name__ == "__main__":
    asyncio.run(main())