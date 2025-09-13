
import asyncio
import os
import re
import random
from typing import Dict, Optional
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout

# ===== Config =====
START_URL = os.getenv(\"START_URL\", \"\").strip()
JOB_QUERY = os.getenv(\"JOB_QUERY\", \"\").strip()  # optional
CDP_URL   = os.getenv(\"DEBUG_URL\", \"http://127.0.0.1:9222\").strip()

DEFAULT_TIMEOUT_MS = int(os.getenv(\"DEFAULT_TIMEOUT_MS\", \"15000\"))
INITIAL_DELAY_MS   = int(os.getenv(\"INITIAL_DELAY_MS\", \"30000\"))  # let human pick job in UI

BETWEEN_STEPS_MS   = int(os.getenv(\"BETWEEN_STEPS_MS\", \"700\"))
BETWEEN_INVITES_MS = int(os.getenv(\"BETWEEN_INVITES_MS\", \"1800\"))
BETWEEN_PAGES_MS   = int(os.getenv(\"BETWEEN_PAGES_MS\", \"2000\"))
MAX_PAGES          = int(os.getenv(\"MAX_PAGES\", \"999\"))

# ===== Selectors =====
INVITE_BUTTON_WITH_DROPDOWN = \"button.headbtn.btn.btn-primary:has(i.fa-caret-down)\"
DROPDOWN_MENU = \".dropdown-content, .downmenu .dropdown-content\"
INVITE_EXISTING_BTN = \"button.request_a_quote_btn:has-text('Invite to Existing Job')\"

MODAL_VISIBLE = \".modal.show, .modal.fade.show, .modal:visible\"
MODAL_CONTENT = \".modal-content\"

CHOICES_CONTAINER = \".choices[data-type='select-one']\"
CHOICES_INNER     = \".choices__inner\"
CHOICES_INPUT     = \".choices__input--cloned\"
CHOICES_DROPDOWN  = \".choices__list--dropdown\"
CHOICES_ITEMS     = \".choices__list--dropdown .choices__item--choice\"
CHOICES_SINGLE    = \".choices__list--single .choices__item\"
NATIVE_SELECT     = \"#request-quote-open-jobs-list\"

MODAL_SUBMIT_BTN  = \"#submit-request-quote\"

SUCCESS_MSG       = \".toast-success, .alert-success, .success-message\"
ERROR_MSG         = \".toast-error, .alert-danger, .error-message\"
ALREADY_INVITED_MSG = \"[text*='already received'], [text*='already invited']\"

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
    return random.uniform(min_ms/1000, max_ms/1000)

async def step_pause():
    await asyncio.sleep(r(BETWEEN_STEPS_MS, BETWEEN_STEPS_MS + 400))

async def invite_pause():
    await asyncio.sleep(r(BETWEEN_INVITES_MS, BETWEEN_INVITES_MS + 900))

async def page_pause():
    await asyncio.sleep(r(BETWEEN_PAGES_MS, BETWEEN_PAGES_MS + 1000))

async def safe_click(loc: Locator, timeout: int = DEFAULT_TIMEOUT_MS) -> bool:
    try:
        await loc.wait_for(state=\"visible\", timeout=timeout)
        await loc.scroll_into_view_if_needed()
        await asyncio.sleep(0.25)
        await loc.click(force=True)
        return True
    except Exception as e:
        warn(f\"Click failed: {str(e)[:140]}\")
        return False

async def get_native_value(page: Page) -> str:
    return await page.evaluate(
        \"\"\"(sel) => {
            const el = document.querySelector(sel);
            return el ? String(el.value) : null;
        }\"\"\", NATIVE_SELECT
    )

async def get_single_text(page: Page) -> str:
    try:
        single = page.locator(CHOICES_SINGLE).first
        if await single.count():
            return (await single.inner_text()).strip()
    except Exception:
        pass
    return \"\"

async def verify_selected(page: Page, job_id: str) -> bool:
    native = await get_native_value(page)
    single = await get_single_text(page)
    info(f\"Verify: native='{native}', single='{single}'\")
    return (native == job_id) or (job_id in single)

async def js_click_option(page: Page, job_id: str) -> bool:
    return await page.evaluate(
        \"\"\"({jobId, itemsSel}) => {
            const el = document.querySelector(`${itemsSel}[data-value=\"${jobId}\"]`);
            if (!el) return false;
            el.scrollIntoView({block:'nearest'});
            const ev = (t) => new MouseEvent(t, {bubbles:true, cancelable:true, view:window});
            el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true}));
            el.dispatchEvent(ev('mousedown'));
            el.click();
            return true;
        }\"\"\", {\"jobId\": job_id, \"itemsSel\": CHOICES_ITEMS}
    )

async def select_job_in_modal(page: Page, job_query: Optional[str]) -> bool:
    if not job_query:
        info(\"No JOB_QUERY provided — assuming job is already selected in UI / default.\")
        return True

    info(f\"Selecting job: {job_query}\")
    m = re.search(r\"\\d+\", job_query)
    job_id = m.group(0) if m else None

    modal = page.locator(MODAL_CONTENT).first
    choices_container = modal.locator(CHOICES_CONTAINER).first
    inner = modal.locator(CHOICES_INNER).first

    try:
        await choices_container.wait_for(state=\"visible\", timeout=8000)
        await choices_container.scroll_into_view_if_needed()
        await inner.click()
        await asyncio.sleep(1.0)

        dropdown = modal.locator(CHOICES_DROPDOWN).first
        await dropdown.wait_for(state=\"visible\", timeout=6000)

        # Keyboard → normal click → JS click
        try:
            if job_id:
                input_loc = modal.locator(CHOICES_INPUT).first
                if await input_loc.count() > 0:
                    await input_loc.fill(\"\")
                    await asyncio.sleep(0.1)
                    await input_loc.type(job_id, delay=50)
                    await asyncio.sleep(0.6)
                    await input_loc.press(\"Enter\")
                    await asyncio.sleep(0.9)
                    if await verify_selected(page, job_id):
                        ok(f\"Selected job via keyboard: {job_id}\")
                        return True
        except Exception:
            pass

        try:
            if job_id:
                by_value = dropdown.locator(f'{CHOICES_ITEMS}[data-value=\"{job_id}\"]').first
                if await by_value.count() > 0:
                    await by_value.scroll_into_view_if_needed()
                    await asyncio.sleep(0.35)
                    await by_value.click()
                    await asyncio.sleep(0.9)
                    if await verify_selected(page, job_id):
                        ok(f\"Selected job by ID (click): {job_id}\")
                        return True
        except Exception:
            pass

        try:
            if job_id and await js_click_option(page, job_id):
                await asyncio.sleep(0.9)
                if await verify_selected(page, job_id):
                    ok(f\"Selected job by ID (JS click): {job_id}\")
                    return True
        except Exception:
            pass

    except Exception as e:
        warn(f\"Choices.js phase failed: {str(e)[:140]}\")

    if job_id:
        try:
            info(\"Trying native select fallback…\")
            changed = await page.evaluate(
                \"\"\"({sel, jobId}) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    const opt = Array.from(el.options).find(o => String(o.value) == String(jobId));
                    if (!opt) return false;
                    el.value = String(jobId);
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    const single = document.querySelector('.choices__list--single .choices__item');
                    if (single) single.textContent = opt.textContent;
                    return true;
                }\"\"\", {\"sel\": NATIVE_SELECT, \"jobId\": job_id}
            )
            await asyncio.sleep(0.6)
            if changed and await verify_selected(page, job_id):
                ok(\"Selected job using native select\")
                return True
        except Exception:
            pass

    warn(\"Could not verify job selection.\")
    return False

async def check_invitation_result(page: Page) -> str:
    await page.wait_for_timeout(2000)
    if await page.locator(SUCCESS_MSG).count() > 0:
        ok(\"Invitation sent successfully!\")
        return 'success'
    if await page.locator(ALREADY_INVITED_MSG).count() > 0:
        info(\"Talent was already invited\")
        return 'already'
    if await page.locator(ERROR_MSG).count() > 0:
        error_text = await page.locator(ERROR_MSG).first.inner_text()
        if 'already' in error_text.lower():
            info(\"Talent was already invited\")
            return 'already'
        warn(f\"Error: {error_text[:140]}\")
        return 'failed'
    warn(\"Could not determine invitation result\")
    return 'failed'

async def close_modal(page: Page):
    try:
        if await page.locator(MODAL_VISIBLE).count() > 0:
            await page.keyboard.press(\"Escape\")
            await asyncio.sleep(0.25)
    except Exception:
        pass

async def invite_single_talent(page: Page, invite_btn: Locator, job_query: Optional[str]) -> str:
    info(\"Clicking invite button dropdown…\")
    if not await safe_click(invite_btn, timeout=7000):
        return 'skipped'
    await asyncio.sleep(0.8)

    info(\"Waiting for and clicking 'Invite to Existing Job'…\")
    try:
        parent_downmenu = invite_btn.locator(\"..\")
        dropdown_menu = parent_downmenu.locator(DROPDOWN_MENU)
        await dropdown_menu.wait_for(state=\"visible\", timeout=5000)
        existing_btn = dropdown_menu.locator(INVITE_EXISTING_BTN)
        if not await safe_click(existing_btn, timeout=5000):
            warn(\"Could not click 'Invite to Existing Job'\")
            return 'skipped'
    except PWTimeout:
        warn(\"Dropdown menu didn't appear in time.\")
        return 'skipped'

    await asyncio.sleep(0.9)

    info(\"Waiting for modal to appear…\")
    try:
        await page.wait_for_selector(MODAL_VISIBLE, state=\"visible\", timeout=8000)
        info(\"Modal opened successfully\")
    except PWTimeout:
        warn(\"Modal didn't appear\")
        return 'skipped'

    await step_pause()

    success = await select_job_in_modal(page, job_query if job_query else None)
    if not success and job_query:
        warn(\"Failed to select job\")
        await close_modal(page)
        return 'skipped'

    await step_pause()

    info(\"Clicking final submit button…\")
    submit_btn = page.locator(MODAL_SUBMIT_BTN).first
    await asyncio.sleep(1.2)
    if not await safe_click(submit_btn, timeout=8000):
        warn(\"Could not click submit button\")
        await close_modal(page)
        return 'skipped'

    await asyncio.sleep(1.0)
    result = await check_invitation_result(page)
    await close_modal(page)
    return result

async def process_current_page(page: Page, job_query: Optional[str]) -> Dict[str, int]:
    stats = {\"seen\": 0, \"invited\": 0, \"already\": 0, \"skipped\": 0, \"failed\": 0}
    invite_buttons = page.locator(INVITE_BUTTON_WITH_DROPDOWN)
    count = await invite_buttons.count()
    if count == 0:
        warn(\"No invite buttons found on this page\")
        return stats
    stats[\"seen\"] = count
    info(f\"Found {count} talent cards to process\")

    for i in range(count):
        info(f\"\\nProcessing talent {i+1}/{count}\")
        current_button = page.locator(INVITE_BUTTON_WITH_DROPDOWN).nth(i)
        result = await invite_single_talent(page, current_button, job_query)
        if result == 'success':
            stats[\"invited\"] += 1
        elif result == 'already':
            stats[\"already\"] += 1
        elif result == 'skipped':
            stats[\"skipped\"] += 1
        else:
            stats[\"failed\"] += 1

        if i < count - 1:
            await invite_pause()

    return stats

async def go_to_next_page(page: Page) -> bool:
    try:
        next_link = page.locator(NEXT_PAGE_SELECTOR).first
        if await next_link.count() == 0:
            info(\"No next page link found\")
            return False
        is_disabled = await next_link.get_attribute(\"aria-disabled\")
        if is_disabled == \"true\":
            info(\"Next page link is disabled (last page)\")
            return False
        await next_link.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
        await next_link.click()
        await page.wait_for_load_state(\"networkidle\", timeout=12000)
        await page_pause()
        return True
    except Exception as e:
        warn(f\"Failed to go to next page: {str(e)[:140]}\")
        return False

async def main():
    info(\"Invite to Job — CDP attach mode\")
    info(f\"CDP: {CDP_URL}\")
    if not START_URL:
        warn(\"START_URL not provided — will act on the current tab's page.\")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else None
        if not context:
            raise RuntimeError(\"No browser context found. Make sure Chrome is running with --remote-debugging-port.\")
        pages = context.pages
        if not pages:
            raise RuntimeError(\"No open tabs found. Open a tab (preferably the Voices search page), then rerun.\")
        page = pages[0]
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        if START_URL:
            await page.goto(START_URL, wait_until=\"domcontentloaded\")

        if INITIAL_DELAY_MS > 0:
            info(f\"Initial delay: {INITIAL_DELAY_MS} ms to let you prepare the UI (choose job/list/etc.)…\")
            await asyncio.sleep(INITIAL_DELAY_MS / 1000.0)

        totals = {\"seen\": 0, \"invited\": 0, \"already\": 0, \"skipped\": 0, \"failed\": 0}
        page_num = 1

        while page_num <= MAX_PAGES:
            info(f\"\\n{'='*50}\")
            info(f\"Processing page {page_num}\")
            info(f\"{'='*50}\")

            stats = await process_current_page(page, JOB_QUERY or None)
            for key in totals:
                totals[key] += stats.get(key, 0)

            info(f\"\\nPage {page_num} results:\")
            info(f\"  Seen: {stats['seen']}\")
            ok(f\"  Invited: {stats['invited']}\")
            info(f\"  Already invited: {stats['already']}\")
            warn(f\"  Skipped: {stats['skipped']}\")
            if stats['failed'] > 0:
                err(f\"  Failed: {stats['failed']}\")

            if not await go_to_next_page(page):
                info(\"No more pages to process\")
                break

            page_num += 1

        info(f\"\\n{'='*50}\")
        ok(\"AUTOMATION COMPLETE\")
        info(f\"{'='*50}\")
        info(f\"Total talents seen: {totals['seen']}\")
        ok(f\"Successfully invited: {totals['invited']}\")
        info(f\"Already invited: {totals['already']}\")
        warn(f\"Skipped: {totals['skipped']}\")
        if totals['failed'] > 0:
            err(f\"Failed: {totals['failed']}\")

        info(\"\\nDone! Browser remains open.\")

if __name__ == \"__main__\":
    asyncio.run(main())
