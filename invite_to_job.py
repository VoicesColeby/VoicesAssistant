# invite_to_job.py - robust Choices.js selection (keyboard search -> JS click -> native fallback)
# plus slower pacing and clear logging.

import asyncio
import os
import re
import random
import json
from typing import Dict
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout
from common_logging import info, ok, warn, err

# =======================
# Config (env-overridable)
# =======================
START_URL = os.getenv("START_URL", "https://YOUR_TALENT_RESULTS_URL")
# Deprecated: job query no longer used; job is selected interactively
JOB_QUERY = os.getenv("JOB_QUERY", "")
CDP_URL   = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")
SKIP_FIRST_TALENT = os.getenv("SKIP_FIRST_TALENT", "true").strip().lower() in ("1", "true", "yes")

# Timeouts & pacing (made slower/more human)
DEFAULT_TIMEOUT_MS   = int(os.getenv("DEFAULT_TIMEOUT_MS", "15000"))

# micro pacing
OPEN_DROPDOWN_MS     = int(os.getenv("OPEN_DROPDOWN_MS", "900"))
OPEN_MODAL_MS        = int(os.getenv("OPEN_MODAL_MS", "900"))
AFTER_CHOICES_OPEN   = int(os.getenv("AFTER_CHOICES_OPEN", "1200"))
AFTER_OPTION_CLICK   = int(os.getenv("AFTER_OPTION_CLICK", "1000"))
BEFORE_SUBMIT_MS     = int(os.getenv("BEFORE_SUBMIT_MS", "1400"))

# macro pacing
BETWEEN_STEPS_MS     = int(os.getenv("BETWEEN_STEPS_MS", "700"))
BETWEEN_INVITES_MS   = int(os.getenv("BETWEEN_INVITES_MS", "1800"))
BETWEEN_PAGES_MS     = int(os.getenv("BETWEEN_PAGES_MS", "2000"))

MAX_PAGES            = int(os.getenv("MAX_PAGES", "999"))

# =======================
# Selectors
# =======================

# Main invite button (with dropdown caret)
INVITE_BUTTON_WITH_DROPDOWN = "button.headbtn.btn.btn-primary:has(i.fa-caret-down)"

# The dropdown menu container near the clicked button
DROPDOWN_MENU = ".dropdown-content, .downmenu .dropdown-content"

# "Invite to Existing Job" button inside dropdown (robust union)
INVITE_EXISTING_BTN = ", ".join([
    "button.request_a_quote_btn:has-text('Invite to Existing Job')",
    "a.request_a_quote_btn:has-text('Invite to Existing Job')",
    "[role='menuitem']:has-text('Invite to Existing Job')",
])

# Modal selectors
MODAL_VISIBLE = ".modal.show, .modal.fade.show, .modal:visible"
MODAL_CONTENT = ".modal-content"

# Choices.js (select-one)
CHOICES_CONTAINER = ".choices[data-type='select-one']"
CHOICES_INNER     = ".choices__inner"
CHOICES_INPUT     = ".choices__input--cloned"  # the hidden text input for type-to-search
CHOICES_DROPDOWN  = ".choices__list--dropdown"
# Options within the open dropdown (support both standard and generic item classes)
CHOICES_ITEMS     = ".choices__list--dropdown .choices__item--choice, .choices__list--dropdown .choices__item"
CHOICES_SINGLE    = ".choices__list--single .choices__item"

# Native select
NATIVE_SELECT     = "#request-quote-open-jobs-list"

# Final submit button
MODAL_SUBMIT_BTN  = "#submit-request-quote"

# Success/Error messages
SUCCESS_MSG       = ".toast-success, .alert-success, .success-message"
ERROR_MSG         = ".toast-error, .alert-danger, .error-message"
ALREADY_INVITED_MSG = "[text*='already received'], [text*='already invited']"

# Pagination
NEXT_PAGE_SELECTOR = """
    a[aria-label='Next']:not(.disabled):not([aria-disabled='true']),
    .pagination a:has(i.fa-angle-right):not(.disabled),
    .pagination button:has(i.fa-angle-right):not(:disabled)
"""

"""Logging provided by common_logging"""

# =======================
# Additional selectors (profile page)
# =======================
# Fallback Invite button on talent profile pages (no explicit caret selector)
PROFILE_INVITE_BTN = ", ".join([
    "button:has-text('Invite to Job')",
    "a.btn.btn-primary:has-text('Invite to Job')",
    "[role='button']:has-text('Invite to Job')",
])

# ============== Humanization (live speed support) ==============
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

async def step_pause():
    await asyncio.sleep(r(BETWEEN_STEPS_MS, BETWEEN_STEPS_MS + 400))

async def invite_pause():
    await asyncio.sleep(r(BETWEEN_INVITES_MS, BETWEEN_INVITES_MS + 900))

async def page_pause():
    await asyncio.sleep(r(BETWEEN_PAGES_MS, BETWEEN_PAGES_MS + 1000))

# ========================= Core Helpers =========================

async def safe_click(loc: Locator, timeout: int = DEFAULT_TIMEOUT_MS) -> bool:
    try:
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.scroll_into_view_if_needed()
        await asyncio.sleep(0.25)
        await loc.click(force=True)
        return True
    except Exception as e:
        warn(f"Click failed: {str(e)[:140]}")
        return False

async def get_native_value(page: Page) -> str:
    return await page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            return el ? String(el.value) : null;
        }""",
        NATIVE_SELECT
    )

async def force_native_value(page: Page, job_id: str) -> bool:
    return await page.evaluate(
        """({sel, jobId}) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            const opt = Array.from(el.options).find(o => String(o.value) === String(jobId));
            if (!opt) return false;
            el.value = String(jobId);
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('input', { bubbles: true }));
            const single = document.querySelector('.choices__list--single .choices__item');
            if (single) single.textContent = opt.textContent;
            return true;
        }""",
        {"sel": NATIVE_SELECT, "jobId": job_id}
    )

async def get_single_text(page: Page) -> str:
    try:
        single = page.locator(CHOICES_SINGLE).first
        if await single.count():
            return (await single.inner_text()).strip()
    except Exception:
        pass
    return ""

async def verify_selected(page: Page, job_id: str) -> bool:
    native = await get_native_value(page)
    single = await get_single_text(page)
    info(f"Verify: native='{native}', single='{single}'")
    return (native == job_id) or (job_id in single)

async def js_click_option(page: Page, job_id: str) -> bool:
    """Dispatch pointer/mouse/click via JS on the exact option by data-value.

    Logs lookup failures (with available choices), confirms the selected option
    text on success, and surfaces any exception stack traces from the JS side.
    """
    try:
        result = await page.evaluate(
            """({jobId, itemsSel}) => {
                const items = Array.from(document.querySelectorAll(itemsSel));
                const values = items.map(el => el.getAttribute('data-value'));
                const el = items.find(el => el.getAttribute('data-value') === jobId);
                if (!el) {
                    return {success:false, values};
                }
                try {
                    el.scrollIntoView({block:'nearest'});
                    const ev = (t) => new MouseEvent(t, {bubbles:true, cancelable:true, view:window});
                    el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true}));
                    el.dispatchEvent(ev('mousedown'));
                    el.click();
                    return {success:true, text: el.textContent, values};
                } catch (err) {
                    return {success:false, values, error: err.stack || String(err)};
                }
            }""",
            {"jobId": job_id, "itemsSel": CHOICES_ITEMS}
        )
    except Exception as e:
        err(f"js_click_option evaluate failed for job_id '{job_id}': {e}")
        return False

    if not result.get("success"):
        available = ", ".join(result.get("values") or [])
        warn(f"js_click_option: no element for job_id '{job_id}'. Available: [{available}]")
        if result.get("error"):
            err(f"js_click_option click error: {result['error']}")
        return False

    selected_text = (result.get("text") or "").strip()
    info(f"js_click_option: selected option '{selected_text}'")
    return True

# ========================= Main Actions =========================

async def invite_single_talent(page: Page, invite_btn: Locator) -> str:
    info("Clicking invite button dropdown...")
    if not await safe_click(invite_btn, timeout=7000):
        return 'skipped'
    await asyncio.sleep(OPEN_DROPDOWN_MS/1000)

    info("Waiting for and clicking 'Invite to Existing Job'...")
    clicked_existing = False
    try:
        parent_downmenu = invite_btn.locator("..")
        dropdown_menu = parent_downmenu.locator(DROPDOWN_MENU)
        await dropdown_menu.wait_for(state="visible", timeout=5000)
        existing_btn = dropdown_menu.locator(INVITE_EXISTING_BTN)
        if await existing_btn.count() > 0:
            clicked_existing = await safe_click(existing_btn.first, timeout=5000)
    except PWTimeout:
        warn("Dropdown menu didn't appear in time (scoped). Trying global fallback...")
        clicked_existing = False

    if not clicked_existing:
        try:
            # Global fallback: menu may be rendered elsewhere in DOM
            existing_global = page.locator(INVITE_EXISTING_BTN).first
            await existing_global.wait_for(state="visible", timeout=5000)
            clicked_existing = await safe_click(existing_global, timeout=5000)
        except Exception as e:
            warn(f"Global fallback failed for 'Invite to Existing Job': {str(e)[:140]}")

    if not clicked_existing:
        warn("Could not click 'Invite to Existing Job'")
        return 'skipped'

    await asyncio.sleep(OPEN_MODAL_MS/1000)

    info("Waiting for modal to appear...")
    try:
        await page.wait_for_selector(MODAL_VISIBLE, state="visible", timeout=8000)
        info("Modal opened successfully")
        info("[invite] modal:ready")
    except PWTimeout:
        warn("Modal didn't appear")
        return 'skipped'

    await step_pause()

    # In regular flow, rely on the existing/default job selection in modal
    success = await ensure_job_selected(page)
    if not success:
        warn("Failed to select job")
        await close_modal(page)
        return 'skipped'
    await step_pause()

    info("Clicking final submit button (slow)...")
    submit_btn = page.locator(MODAL_SUBMIT_BTN).first
    await asyncio.sleep(BEFORE_SUBMIT_MS/1000)
    info("[invite] submit:clicked")
    if not await safe_click(submit_btn, timeout=8000):
        warn("Could not click submit button")
        await close_modal(page)
        return 'skipped'

    await asyncio.sleep(1.2)
    result = await check_invitation_result(page)
    if result == 'success':
        info("[invite] done:success")
    elif result == 'already':
        info("[invite] done:already")
    else:
        info("[invite] done:failed")
    await close_modal(page)
    return result

async def select_job_in_modal(page: Page, job_query: str) -> bool:
    """Robust: keyboard -> normal click -> JS click -> native fallback. Verifies after each."""
    info(f"Selecting job: {job_query}")
    m = re.search(r"\d+", job_query)
    job_id = m.group(0) if m else None

    modal = page.locator(MODAL_CONTENT).first
    choices_container = modal.locator(CHOICES_CONTAINER).first
    inner = modal.locator(CHOICES_INNER).first

    try:
        # 0) Open dropdown
        await choices_container.wait_for(state="visible", timeout=8000)
        await choices_container.scroll_into_view_if_needed()
        await inner.click()
        await asyncio.sleep(AFTER_CHOICES_OPEN/1000)

        dropdown = modal.locator(CHOICES_DROPDOWN).first
        aria = await dropdown.get_attribute("aria-expanded")
        info(f"Dropdown aria-expanded after click: {aria}")

        try:
            await modal.locator(f"{CHOICES_DROPDOWN}[aria-expanded='true']").wait_for(state="visible", timeout=6000)
        except PWTimeout:
            warn("Dropdown did not open (aria-expanded!='true'). Capturing screenshot...")
            os.makedirs("logs", exist_ok=True)
            try:
                await page.screenshot(path="logs/dropdown_not_open.png")
            except Exception:
                pass
            raise

        dropdown = modal.locator(f"{CHOICES_DROPDOWN}[aria-expanded='true']").first

        options = dropdown.locator(CHOICES_ITEMS)
        count = await options.count()
        info(f"Choices.js dropdown shows {count} options")
        for i in range(min(count, 10)):
            opt = options.nth(i)
            txt = (await opt.inner_text()).strip()
            val = await opt.get_attribute("data-value")
            info(f"  Option {i+1}: value={val} | text={txt}")

        # 1) KEYBOARD SEARCH & ENTER
        try:
            if job_id:
                input_loc = modal.locator(CHOICES_INPUT).first
                if await input_loc.count() > 0:
                    await input_loc.fill("")  # clear
                    await asyncio.sleep(0.1)
                    # Type the id (not including '#') - Choices filters live
                    await input_loc.type(job_id, delay=50)
                    await asyncio.sleep(0.6)
                    # Press Enter to select highlighted option
                    await input_loc.press("Enter")
                    await asyncio.sleep(AFTER_OPTION_CLICK/1000)
                    if await verify_selected(page, job_id):
                        ok(f"Selected job via keyboard: {job_id}")
                        return True
                    else:
                        warn("Keyboard selection didn't verify; trying click paths...")
        except Exception as e:
            warn(f"Keyboard path error: {str(e)[:140]}")

        # 2) NORMAL CLICK BY data-value
        try:
            if job_id:
                by_value = dropdown.locator(f'{CHOICES_ITEMS}[data-value="{job_id}"]').first
                if await by_value.count() > 0:
                    await by_value.scroll_into_view_if_needed()
                    await asyncio.sleep(0.35)
                    await by_value.click()
                    await asyncio.sleep(AFTER_OPTION_CLICK/1000)
                    if await verify_selected(page, job_id):
                        ok(f"Selected job by ID (click): {job_id}")
                        return True
                    warn("Normal click didn't verify; trying JS click...")
        except Exception as e:
            warn(f"Normal click error: {str(e)[:140]}")

        # 3) JS CLICK (pointerdown/mousedown/click)
        try:
            if job_id and await js_click_option(page, job_id):
                await asyncio.sleep(AFTER_OPTION_CLICK/1000)
                if await verify_selected(page, job_id):
                    ok(f"Selected job by ID (JS click): {job_id}")
                    return True
                warn("JS click didn't verify; trying native...")
        except Exception as e:
            warn(f"JS click error: {str(e)[:140]}")

    except Exception as e:
        warn(f"Choices.js phase failed: {str(e)[:140]}")

    # 4) NATIVE SELECT FALLBACK
    try:
        if job_id:
            info("Trying native select fallback...")
            if await force_native_value(page, job_id):
                await asyncio.sleep(0.6)
                if await verify_selected(page, job_id):
                    ok("Selected job using native select")
                    return True
                warn("Native set did not verify.")
    except Exception as e:
        warn(f"Native select method failed: {str(e)[:140]}")

    # Final failure: capture state for debugging
    os.makedirs("logs", exist_ok=True)
    try:
        await page.screenshot(path=f"logs/select_job_failure_{job_id or 'unknown'}.png")
    except Exception:
        pass
    try:
        single = await get_single_text(page)
    except Exception:
        single = ""
    try:
        native = await get_native_value(page)
    except Exception:
        native = None
    warn(
        f"Failed to select job (id={job_id}, query='{job_query}') - native='{native}', single='{single}'"
    )
    if os.getenv("DEBUG_CHOICES"):
        try:
            html = await modal.locator(CHOICES_DROPDOWN).first.inner_html()
            fname = f"logs/choices_dropdown_{job_id or 'unknown'}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass

    return False

async def check_invitation_result(page: Page) -> str:
    await page.wait_for_timeout(2000)
    if await page.locator(SUCCESS_MSG).count() > 0:
        ok("Invitation sent successfully!")
        return 'success'
    if await page.locator(ALREADY_INVITED_MSG).count() > 0:
        info("Talent was already invited")
        return 'already'
    if await page.locator(ERROR_MSG).count() > 0:
        error_text = await page.locator(ERROR_MSG).first.inner_text()
        if 'already' in error_text.lower():
            info("Talent was already invited")
            return 'already'
        warn(f"Error: {error_text[:140]}")
        return 'failed'
    warn("Could not determine invitation result")
    return 'failed'

async def close_modal(page: Page):
    try:
        if await page.locator(MODAL_VISIBLE).count() > 0:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.25)
    except Exception:
        pass

async def ensure_job_selected(page: Page) -> bool:
    """Ensure a job is selected in the modal; if not, wait for the user to select one once.
    Subsequent invites will use the site's remembered selection.
    """
    modal = page.locator(MODAL_CONTENT).first

    async def has_selection() -> bool:
        try:
            native = await get_native_value(page)
        except Exception:
            native = None
        if native and native not in ("", "0", "null", "undefined"):
            return True
        try:
            single = await get_single_text(page)
        except Exception:
            single = ""
        if single and not single.lower().startswith("select"):
            return True
        return False

    try:
        await modal.wait_for(state="visible", timeout=8000)
    except Exception:
        return False

    if await has_selection():
        return True

    info("Please select a job in the modal (first-time setup). Waiting...")
    for _ in range(600):  # up to ~5 minutes
        if await has_selection():
            ok("Detected job selected in modal.")
            return True
        await asyncio.sleep(0.5)

    warn("Timed out waiting for job selection in modal.")
    return False

async def process_current_page(page: Page, skip_first: bool = False) -> Dict[str, int]:
    stats = {"seen": 0, "invited": 0, "already": 0, "skipped": 0, "failed": 0}
    invite_buttons = page.locator(INVITE_BUTTON_WITH_DROPDOWN)
    count = await invite_buttons.count()
    if count == 0:
        # Fallback: talent profile page button without explicit caret selector
        profile_btns = page.locator(PROFILE_INVITE_BTN)
        pcount = await profile_btns.count()
        if pcount > 0:
            info("Profile page detected (fallback). Attempting invite...")
            stats["seen"] = 1
            result = await invite_single_talent(page, profile_btns.first)
            if result == 'success':
                stats["invited"] = 1
            elif result == 'already':
                stats["already"] = 1
            elif result == 'skipped':
                stats["skipped"] = 1
            else:
                stats["failed"] = 1
            return stats
        warn("No invite buttons found on this page")
        return stats
    stats["seen"] = count
    info(f"Found {count} talent cards to process")

    start_index = 1 if (skip_first and count > 0) else 0
    if skip_first and count > 0:
        info("Skipping first talent on this page (manual invite assumed).")
    for i in range(start_index, count):
        info(f"\nProcessing talent {i+1}/{count}")
        current_button = page.locator(INVITE_BUTTON_WITH_DROPDOWN).nth(i)
        result = await invite_single_talent(page, current_button)
        if result == 'success':
            stats["invited"] += 1
        elif result == 'already':
            stats["already"] += 1
        elif result == 'skipped':
            stats["skipped"] += 1
        else:
            stats["failed"] += 1

        if i < count - 1:
            await invite_pause()

    return stats

async def go_to_next_page(page: Page) -> bool:
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
        await asyncio.sleep(0.2)
        await next_link.click()
        await page.wait_for_load_state("networkidle", timeout=12000)
        await page_pause()
        return True
    except Exception as e:
        warn(f"Failed to go to next page: {str(e)[:140]}")
        return False

# ========================= Main =========================
async def main():
    info(f"Starting automation...")
    info(f"URL: {START_URL}")
    info(f"CDP URL: {CDP_URL}")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)

        # Prefer to use an existing page from any context (latest),
        # so we don't blow away manual setup.
        all_pages = []
        for ctx in browser.contexts:
            for pg in ctx.pages:
                all_pages.append((ctx, pg))

        # Determine preference flags
        use_current = os.getenv("USE_CURRENT_PAGE", "").strip().lower() in ("1", "true", "yes")

        if use_current and all_pages:
            # Pick the most recent non-chrome page, prefer voices.com
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
            ctx, page = sorted(all_pages, key=page_rank)[-1]
        else:
            # Fallback: original behavior, first context/page (or new)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()

        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        # Only navigate if not using current page
        if not use_current:
            await page.goto(START_URL, wait_until="domcontentloaded")
            await page_pause()
        else:
            info("Using current page; no navigation performed.")

        totals = {"seen": 0, "invited": 0, "already": 0, "skipped": 0, "failed": 0}
        page_num = 1

        while page_num <= MAX_PAGES:
            info(f"\n{'='*50}")
            info(f"Processing page {page_num}")
            info(f"{'='*50}")

            stats = await process_current_page(page, skip_first=(SKIP_FIRST_TALENT and page_num == 1))

            for key in totals:
                totals[key] += stats.get(key, 0)

            info(f"\nPage {page_num} results:")
            info(f"  Seen: {stats['seen']}")
            ok(f"  Invited: {stats['invited']}")
            info(f"  Already invited: {stats['already']}")
            warn(f"  Skipped: {stats['skipped']}")
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
        ok(f"Successfully invited: {totals['invited']}")
        info(f"Already invited: {totals['already']}")
        warn(f"Skipped: {totals['skipped']}")
        if totals['failed'] > 0:
            err(f"  Failed: {totals['failed']}")

        info("\nDone! Browser remains open.")

if __name__ == "__main__":
    asyncio.run(main())
