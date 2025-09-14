import asyncio
import os
import re
import random
from typing import Dict, Optional
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout

# Config
START_URL = os.getenv("START_URL", "").strip()
JOB_QUERY = os.getenv("JOB_QUERY", "").strip()
CDP_URL   = os.getenv("DEBUG_URL", "http://127.0.0.1:9222").strip()

DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", "15000"))
# Removed initial wait; pause is handled via GUI now
INITIAL_DELAY_MS   = int(os.getenv("INITIAL_DELAY_MS", "0"))
BETWEEN_STEPS_MS   = int(os.getenv("BETWEEN_STEPS_MS", "700"))
BETWEEN_INVITES_MS = int(os.getenv("BETWEEN_INVITES_MS", "1800"))
BETWEEN_PAGES_MS   = int(os.getenv("BETWEEN_PAGES_MS", "2000"))
MAX_PAGES          = int(os.getenv("MAX_PAGES", "999"))

# Selectors
# Search/list card invite button (caret dropdown)
INVITE_BUTTON_WITH_DROPDOWN = "button.headbtn.btn.btn-primary:has(i.fa-caret-down)"
# Profile header invite button (top-right on talent profile)
PROFILE_INVITE_BUTTON = ", ".join([
    "button.profile-header-btn.headbtn.btn.btn-primary",
    "button.headbtn.btn.btn-primary.profile-header-btn",
    "button.btn.btn-primary.profile-header-btn",
    "button:has-text('Invite to Job')",
    "button:has-text('Invite to job')",
])
DROPDOWN_MENU = ".dropdown-content, .downmenu .dropdown-content"
INVITE_EXISTING_BTN = "button.request_a_quote_btn:has-text('Invite to Existing Job')"

MODAL_VISIBLE = ".modal.show, .modal.fade.show, .modal:visible"
MODAL_CONTENT = ".modal-content"

CHOICES_CONTAINER = ".choices[data-type='select-one']"
CHOICES_INNER     = ".choices__inner"
CHOICES_INPUT     = ".choices__input--cloned"
CHOICES_DROPDOWN  = ".choices__list--dropdown"
CHOICES_ITEMS     = ".choices__list--dropdown .choices__item--choice"
CHOICES_SINGLE    = ".choices__list--single .choices__item"
NATIVE_SELECT     = "#request-quote-open-jobs-list"
SPINNER_BLUE      = ".voices-spinner-blue"

MODAL_SUBMIT_BTN  = "#submit-request-quote"

SUCCESS_MSG       = ".toast-success, .alert-success, .success-message"
ERROR_MSG         = ".toast-error, .alert-danger, .error-message"
ALREADY_INVITED_MSG = "[text*='already received'], [text*='already invited']"

NEXT_PAGE_SELECTOR = """
    a[aria-label='Next']:not(.disabled):not([aria-disabled='true']),
    .pagination a:has(i.fa-angle-right):not(.disabled),
    .pagination button:has(i.fa-angle-right):not(:disabled)
"""

# Logging
def info(msg):  print(f"\x1b[36m[i]\x1b[0m {msg}")
def ok(msg):    print(f"\x1b[32m[ok]\x1b[0m {msg}")
def warn(msg):  print(f"\x1b[33m[!]\x1b[0m {msg}")
def err(msg):   print(f"\x1b[31m[x]\x1b[0m {msg}")

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

async def get_single_text(page: Page) -> str:
    try:
        single = page.locator(CHOICES_SINGLE).first
        if await single.count():
            return (await single.inner_text()).strip()
    except Exception:
        pass
    return ""

async def verify_selected(page: Page, job_id: Optional[str], title_sub: str = "") -> bool:
    native = await get_native_value(page)
    data_val = ""
    single = ""
    try:
        sel = page.locator(CHOICES_SINGLE).first
        if await sel.count():
            single = (await sel.inner_text()).strip()
            data_val = await sel.get_attribute("data-value") or ""
    except Exception:
        pass
    info(f"Verify: native='{native}', single='{single}', data='{data_val}'")

    cond_native = False
    cond_data = False
    cond_text = False
    if job_id:
        cond_native = native == job_id
        cond_data = data_val == job_id
        cond_text = job_id in single
    if title_sub:
        cond_text = cond_text or title_sub.lower() in single.lower()

    if job_id:
        return cond_native and cond_data and cond_text
    return cond_text

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

async def select_job_in_modal(page: Page, job_query: Optional[str]) -> bool:
    if not job_query:
        info("No JOB_QUERY provided — assuming job is already selected in UI / default.")
        return True
    info(f"Selecting job: {job_query}")
    m = re.search(r"\d+", job_query)
    job_id = m.group(0) if m else None
    title_sub = re.sub(r"\d+", "", job_query).strip()
    modal = page.locator(MODAL_CONTENT).first
    choices_container = modal.locator(CHOICES_CONTAINER).first
    inner = modal.locator(CHOICES_INNER).first

    async def final_failure() -> bool:
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
            f"Failed to select job (id={job_id}, query='{job_query}') — native='{native}', single='{single}'"
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
    try:
        await choices_container.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await modal.locator(SPINNER_BLUE).first.wait_for(state="hidden", timeout=DEFAULT_TIMEOUT_MS)
        await inner.click()
        await asyncio.sleep(0.25)

        dropdown = modal.locator(CHOICES_DROPDOWN).first
        aria = await dropdown.get_attribute("aria-expanded")
        info(f"Dropdown aria-expanded after click: {aria}")
        try:
            await modal.locator(f"{CHOICES_DROPDOWN}[aria-expanded='true']").wait_for(state="visible", timeout=5000)
        except PWTimeout:
            warn("Dropdown did not open (aria-expanded!='true'). Capturing screenshot…")
            os.makedirs("logs", exist_ok=True)
            try:
                await page.screenshot(path="logs/dropdown_not_open.png")
            except Exception:
                pass
            raise
    except Exception:
        warn("Choices.js dropdown not found; trying native select fallback")
        if job_id:
            _ok = await page.evaluate(
                """(sel, val) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    el.value = String(val);
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                    return true;
                }""",
                NATIVE_SELECT,
                job_id,
            )
            if _ok:
                await asyncio.sleep(0.3)
                if await verify_selected(page, job_id, title_sub):
                    return True
        return await final_failure()
    if job_id:
        try:
            inp = modal.locator(CHOICES_INPUT).first
            await inp.fill("")
            await inp.type(job_id)
            await inp.press("Enter")
            await asyncio.sleep(0.3)
            if await verify_selected(page, job_id, title_sub):
                return True
        except Exception as e:
            warn(f"Typing job_id failed: {e}")
        try:
            item = modal.locator(f".choices__item[data-value='{job_id}']").first
            if await item.count():
                await item.click()
                await asyncio.sleep(0.3)
                if await verify_selected(page, job_id, title_sub):
                    return True
        except Exception as e:
            warn(f"Clicking by data-value failed: {e}")
    if title_sub:
        try:
            item = modal.locator(f".choices__item:has-text(\"{title_sub}\")").first
            if await item.count():
                await item.click()
                await asyncio.sleep(0.3)
                if await verify_selected(page, job_id, title_sub):
                    return True
        except Exception as e:
            warn(f"Clicking by title substring failed: {e}")
    if job_id and await js_click_option(page, job_id):
        await asyncio.sleep(0.3)
        if await verify_selected(page, job_id, title_sub):
            return True
    warn("JS click on option failed; trying native set + verify")
    if job_id:
        _ok = await page.evaluate(
            """(sel, val) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                el.value = String(val);
                el.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            }""",
            NATIVE_SELECT,
            job_id,
        )
        if _ok:
            await asyncio.sleep(0.3)
            if await verify_selected(page, job_id, title_sub):
                return True
    success = await verify_selected(page, job_id, title_sub)
    if success:
        return True

    return await final_failure()

async def close_modal(page: Page):
    try:
        esc = page.keyboard
        await esc.press('Escape')
        await asyncio.sleep(0.2)
    except Exception:
        pass

async def check_invitation_result(page: Page, timeout: int = DEFAULT_TIMEOUT_MS) -> str:
    """Wait for a success or error toast after submitting an invite.

    If no toast appears within ``timeout`` milliseconds, return ``"unknown"``.
    """
    success_task = asyncio.create_task(
        page.wait_for_selector(SUCCESS_MSG, timeout=timeout)
    )
    already_task = asyncio.create_task(
        page.wait_for_selector(ALREADY_INVITED_MSG, timeout=timeout)
    )
    error_task = asyncio.create_task(
        page.wait_for_selector(ERROR_MSG, timeout=timeout)
    )

    done, pending = await asyncio.wait(
        [success_task, already_task, error_task],
        return_when=asyncio.FIRST_COMPLETED,
        timeout=timeout / 1000,
    )

    for task in pending:
        task.cancel()

    if not done:
        warn("No invitation result detected within timeout")
        return "unknown"

    finished = done.pop()
    try:
        await finished
    except Exception:
        pass

    if finished is success_task:
        ok("Invitation success toast detected")
        return "success"
    if finished is already_task:
        info("Already invited message detected")
        return "already"
    if finished is error_task:
        err("Error toast detected")
        return "failed"
    return "unknown"

async def invite_single_talent(page: Page, invite_button: Locator, job_query: Optional[str]) -> str:
    try:
        await invite_button.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await invite_button.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
        await invite_button.click()
    except Exception as e:
        warn(f"Failed to click invite button: {e}")
        return 'skipped'

    try:
        menu = page.locator(DROPDOWN_MENU).first
        await menu.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        btn = page.locator(INVITE_EXISTING_BTN).first
        await btn.click()
    except Exception as e:
        warn(f"Dropdown interaction failed: {e}")
        return 'skipped'

    try:
        await page.locator(MODAL_VISIBLE).first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await step_pause()
    except Exception:
        warn("Modal did not appear in time")
        return 'skipped'

    if not await select_job_in_modal(page, job_query):
        warn("Job selection failed")
        await close_modal(page)
        return 'skipped'

    await step_pause()
    info("Clicking final submit button…")
    submit_btn = page.locator(MODAL_SUBMIT_BTN).first
    await asyncio.sleep(1.0)
    if not await safe_click(submit_btn, timeout=8000):
        warn("Could not click submit button")
        await close_modal(page)
        return 'skipped'

    await asyncio.sleep(1.0)
    result = await check_invitation_result(page)
    if result == "unknown":
        warn("Invitation outcome unclear (no toast detected)")
    await close_modal(page)
    return result

async def invite_via_profile_header(page: Page, job_query: Optional[str]) -> str:
    """Handle inviting from a single talent profile page (top-right button)."""
    try:
        btn = page.locator(PROFILE_INVITE_BUTTON).first
        if await btn.count() == 0:
            warn("Profile header invite button not found")
            return 'skipped'
        await btn.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
        await btn.click()
    except Exception as e:
        warn(f"Failed to click profile invite button: {e}")
        return 'skipped'

    try:
        menu = page.locator(DROPDOWN_MENU).first
        await menu.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        btn2 = page.locator(INVITE_EXISTING_BTN).first
        await btn2.click()
    except Exception as e:
        warn(f"Profile dropdown interaction failed: {e}")
        return 'skipped'

    try:
        await page.locator(MODAL_VISIBLE).first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await step_pause()
    except Exception:
        warn("Modal did not appear in time")
        return 'skipped'

    if not await select_job_in_modal(page, job_query):
        warn("Job selection failed")
        await close_modal(page)
        return 'skipped'

    await step_pause()
    submit_btn = page.locator(MODAL_SUBMIT_BTN).first
    await asyncio.sleep(1.0)
    if not await safe_click(submit_btn, timeout=8000):
        warn("Could not click submit button")
        await close_modal(page)
        return 'skipped'
    await asyncio.sleep(1.0)
    result = await check_invitation_result(page)
    await close_modal(page)
    return result

async def process_current_page(page: Page, job_query: Optional[str]) -> Dict[str, int]:
    stats = {"seen": 0, "invited": 0, "already": 0, "skipped": 0, "failed": 0}
    invite_buttons = page.locator(INVITE_BUTTON_WITH_DROPDOWN)
    count = await invite_buttons.count()
    if count == 0:
        # Fallback: handle talent profile page with a single header button
        result = await invite_via_profile_header(page, job_query)
        stats["seen"] = 1
        if result == 'success':
            stats["invited"] += 1
        elif result == 'already':
            stats["already"] += 1
        elif result == 'skipped':
            stats["skipped"] += 1
        else:
            stats["failed"] += 1
        return stats
    stats["seen"] = count
    info(f"Found {count} talent cards to process")

    for i in range(count):
        info(f"\nProcessing talent {i+1}/{count}")
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

async def main():
    info("Invite to Job (CDP attach mode)")
    info(f"CDP: {CDP_URL}")
    if not START_URL:
        warn("START_URL not provided — will act on the current tab's page.")
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else None
        if not context:
            raise RuntimeError("No browser context found. Make sure Chrome is running with --remote-debugging-port.")
        pages = context.pages
        if not pages:
            raise RuntimeError("No open tabs found. Open a tab (preferably the Voices search page), then rerun.")
        page = pages[0]
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        if START_URL:
            await page.goto(START_URL, wait_until="domcontentloaded")

        # Removed initial delay; use GUI pause instead

        totals = {"seen": 0, "invited": 0, "already": 0, "skipped": 0, "failed": 0}
        page_num = 1
        while page_num <= MAX_PAGES:
            info(f"\n{'='*50}")
            info(f"Processing page {page_num}")
            info(f"{'='*50}")
            stats = await process_current_page(page, JOB_QUERY or None)
            for key in totals:
                totals[key] += stats.get(key, 0)
            info(f"\nPage {page_num} results:")
            info(f"  Seen: {totals['seen']}")
            ok(f"  Invited: {totals['invited']}")
            info(f"  Already invited: {totals['already']}")
            warn(f"  Skipped: {totals['skipped']}")
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
            err(f"Failed: {totals['failed']}")
        info("\nDone! Browser remains open.")

if __name__ == "__main__":
    asyncio.run(main())

