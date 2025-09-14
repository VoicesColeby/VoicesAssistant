# export_responses.py
import asyncio
import os
import re
import random
import csv
from typing import Dict, List
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout
from common_logging import info, ok, warn, err

# =======================
# Config (env-overridable)
# =======================
START_URL = os.getenv("START_URL", "https://www.voices.com/client/jobs/responses/805775")
CDP_URL = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "voices_responses.csv")

# Timeouts & pacing
DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", "60000"))
BETWEEN_STEPS_MS = int(os.getenv("BETWEEN_STEPS_MS", "600"))
BETWEEN_ACTIONS_MS = int(os.getenv("BETWEEN_ACTIONS_MS", "1200"))
EXTRACTION_PAUSE_MS = int(os.getenv("EXTRACTION_PAUSE_MS", "800"))

# =======================
# Selectors
# =======================

# Selector for each talent response card
RESPONSE_CARD = "div.response-item-list-group-item, div.response-item-list-group-item--expanded"

# Elements within each card
NAME_LINK = "div.response-item-talent-info > a"
RATE_TAG = "strong.response-item-price-tag"
OPEN_PROPOSAL_LINK = "a.toggle-proposal-btn:has-text('Open Proposal')"

# The proposal content that becomes visible after clicking the link
PROPOSAL_CONTENT = "div.response-item-proposal-content"

# =======================
# Logging (common)
# =======================
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

async def extract_talent_data(card: Locator) -> Dict:
    """Extracts name, rate, and proposal text from a single talent card"""
    data = {"Name": "N/A", "Rate": "N/A", "Proposal": "N/A"}

    info("Attempting to extract name...")
    try:
        name_locator = card.locator(NAME_LINK).first
        data["Name"] = await name_locator.inner_text()
        ok(f"Found name: {data['Name']}")
    except Exception:
        warn("Could not find name.")
        pass

    info("Attempting to extract rate...")
    try:
        rate_locator = card.locator(RATE_TAG).first
        data["Rate"] = await rate_locator.inner_text()
        ok(f"Found rate: {data['Rate']}")
    except Exception:
        warn("Could not find rate.")
        pass

    info("Attempting to find 'Open Proposal' link...")
    try:
        proposal_link = card.locator(OPEN_PROPOSAL_LINK).first
        if await proposal_link.count() > 0:
            info("Found 'Open Proposal' link. Attempting to click...")
            if await safe_click(proposal_link, timeout=5000):
                ok("Successfully clicked 'Open Proposal'.")
                
                info("Waiting for proposal content to become visible...")
                proposal_content_locator = card.locator(PROPOSAL_CONTENT).first
                await proposal_content_locator.wait_for(state="visible", timeout=5000)
                ok("Proposal content is visible. Extracting text...")
                await human_delay(EXTRACTION_PAUSE_MS)
                
                proposal_text = await proposal_content_locator.inner_text()
                data["Proposal"] = re.sub(r'\s+', ' ', proposal_text).strip()
                ok("Successfully extracted proposal text.")
                
                info("Closing proposal...")
                await safe_click(proposal_link, timeout=5000)
                ok("Successfully closed proposal.")
            else:
                warn("Failed to click 'Open Proposal' link.")
        else:
            warn("No 'Open Proposal' link found for this talent.")
    except Exception as e:
        err(f"An error occurred while extracting proposal for {data['Name']}: {str(e)[:100]}")
    
    return data

async def export_all_responses(page: Page) -> List[Dict]:
    """Extracts data from all talent response cards on the page"""
    all_data = []

    info("Waiting for the first response card to become visible...")
    try:
        await page.wait_for_selector(RESPONSE_CARD, state="visible", timeout=DEFAULT_TIMEOUT_MS)
        ok("First response card is visible. Proceeding with data extraction.")
    except PWTimeout:
        err("Timed out waiting for any response cards to appear. Exiting.")
        return all_data

    response_cards = page.locator(RESPONSE_CARD)
    count = await response_cards.count()
    info(f"Found {count} talent responses to process.")

    for i in range(count):
        card = response_cards.nth(i)
        info(f"\nProcessing response {i+1}/{count}...")
        talent_data = await extract_talent_data(card)
        all_data.append(talent_data)
        await action_pause()

    return all_data

# =========================
# Main
# =========================
async def main():
    info(f"Starting 'Export Responses' automation...")
    info(f"URL: {START_URL}")
    info(f"Output File: {OUTPUT_FILE}")
    info(f"CDP URL: {CDP_URL}")
    
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        
        info(f"Navigating to URL: {START_URL}")
        try:
            await page.goto(START_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
            
            # This is the new, more resilient wait.
            info("Waiting for a moment to allow dynamic content to render...")
            await asyncio.sleep(5)
            ok("Proceeding with element search.")

        except PWTimeout:
            warn("Page navigation took longer than expected but proceeding anyway.")
        
        await step_pause()

        try:
            talent_data = await export_all_responses(page)
            
            if talent_data:
                with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
                    fieldnames = ["Name", "Rate", "Proposal"]
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    
                    writer.writeheader()
                    writer.writerows(talent_data)
                
                ok(f"\nSuccessfully wrote data for {len(talent_data)} talents to '{OUTPUT_FILE}'.")
            else:
                warn("\nNo talent data was extracted.")
        except Exception as e:
            err(f"An error occurred during data extraction: {str(e)}")

        info("\nDone! Browser remains open.")

if __name__ == "__main__":
    asyncio.run(main())

