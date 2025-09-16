import os
import sys
import csv
import re
import asyncio
from typing import List, Tuple
from playwright.async_api import async_playwright, Page, Locator, TimeoutError as PWTimeout
from common_logging import info, ok, warn, err


def read_env(name: str, default: str = "") -> str:
    return os.getenv(name, default) or default


def parse_usernames_from_csv(csv_path: str) -> List[str]:
    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise RuntimeError("CSV has no header row")
        fieldmap = { (c or '').strip().lower(): c for c in reader.fieldnames }
        ucol = fieldmap.get('username')
        if not ucol:
            raise RuntimeError("Could not find a 'username' column in the CSV")
        vals: List[str] = []
        for row in reader:
            v = (row.get(ucol) or '').strip()
            if v:
                vals.append(v)
        return vals


# =======================
# Config and selectors
# =======================
CDP_URL = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")
DEFAULT_TIMEOUT_MS = int(os.getenv("DEFAULT_TIMEOUT_MS", "15000"))

# Buttons on talent profile pages
PROFILE_INVITE_BTN = ", ".join([
    "button:has-text('Invite to Job')",
    "a.btn.btn-primary:has-text('Invite to Job')",
    "[role='button']:has-text('Invite to Job')",
])

# Dropdown and menu
DROPDOWN_MENU = ".dropdown-content, .downmenu .dropdown-content"
INVITE_EXISTING_BTN = ", ".join([
    "button.request_a_quote_btn:has-text('Invite to Existing Job')",
    "a.request_a_quote_btn:has-text('Invite to Existing Job')",
    "[role='menuitem']:has-text('Invite to Existing Job')",
])

# Modal and Choices.js
MODAL_FORM = "#request-a-quote-form"
MODAL_CONTENT = ".modal-content"
CHOICES_CONTAINER = ".choices[data-type='select-one']"
CHOICES_INNER = ".choices__inner"
CHOICES_INPUT = ".choices__input--cloned"
CHOICES_DROPDOWN = ".choices__list--dropdown"
CHOICES_ITEMS = ".choices__list--dropdown .choices__item--choice, .choices__list--dropdown .choices__item"
CHOICES_SINGLE = ".choices__list--single .choices__item"
NATIVE_SELECT = "#request-quote-open-jobs-list"
MODAL_SUBMIT_BTN = "#submit-request-quote"
SPINNER = ".voices-spinner-blue"

SUCCESS_MSG = ".toast-success, .alert-success, .success-message"
ERROR_MSG = ".toast-error, .alert-danger, .error-message"


# =======================
# Helpers
# =======================
async def safe_click(loc: Locator, timeout: int = DEFAULT_TIMEOUT_MS) -> bool:
    try:
        await loc.wait_for(state="visible", timeout=timeout)
        await loc.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
        await loc.click(force=True)
        return True
    except Exception as e:
        warn(f"Click failed: {str(e)[:140]}")
        return False


async def get_native_value(page: Page):
    try:
        return await page.eval_on_selector(NATIVE_SELECT, "el => String(el.value)")
    except Exception:
        return None


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


async def select_job_in_modal(page: Page, job_query: str) -> bool:
    # 0) Resolve job id
    job_id_match = re.search(r"\d+", job_query or "")
    job_id = job_id_match.group(0) if job_id_match else None
    if not job_id:
        err("JOB_QUERY missing digits")
        return False

    # 1) Wait for modal form and spinner to settle
    form = page.locator(MODAL_FORM).first
    try:
        await form.wait_for(state="visible", timeout=10000)
    except Exception:
        warn("Invite modal form not visible")
        return False

    try:
        # If a spinner overlays the modal, wait until it's gone
        sp = page.locator(SPINNER).first
        if await sp.count() > 0:
            await sp.wait_for(state="hidden", timeout=8000)
    except Exception:
        pass

    # 2) Ensure the Choices root is present in the form
    choices = form.locator(CHOICES_CONTAINER).first
    try:
        await choices.wait_for(state="visible", timeout=10000)
    except Exception:
        warn("Choices container not visible in modal form")
        return False

    # 3) Open the dropdown (inner first, then container)
    try:
        ci = choices.locator(CHOICES_INNER).first
        await ci.scroll_into_view_if_needed()
        await asyncio.sleep(0.15)
        await ci.click()
    except Exception as e:
        warn(f"Clicking .choices__inner failed: {str(e)[:140]}; trying container")
        try:
            await choices.scroll_into_view_if_needed()
            await asyncio.sleep(0.15)
            await choices.click()
        except Exception as e2:
            warn(f"Clicking container failed: {str(e2)[:140]}")
            return False

    # Wait for aria-expanded=true under this form
    try:
        dd = form.locator(f"{CHOICES_DROPDOWN}[aria-expanded='true']").first
        await dd.wait_for(state="visible", timeout=6000)
        info("[invite] dropdown:open")
    except Exception as e:
        warn(f"Dropdown did not open: {str(e)[:140]}")
        return False

    # 4) Choose the correct job (prefer exact data-value)
    dd = form.locator(f"{CHOICES_DROPDOWN}[aria-expanded='true']").first

    # Try exact data-value match first
    option = dd.locator(f".choices__item[data-value='{job_id}']").first
    if await option.count() == 0:
        # Fallback by text; labels look like "#818314 - ..."
        # Try with '#' prefix and raw digits as substring
        option = dd.locator(".choices__item").filter(has_text=f"#{job_id}").first
    if await option.count() == 0:
        option = dd.locator(".choices__item").filter(has_text=job_id).first

    if await option.count() == 0:
        # Secondary fallback: type-to-filter and press Enter
        try:
            input_loc = form.locator(CHOICES_INPUT).first
            if await input_loc.count() > 0:
                await input_loc.fill("")
                await input_loc.type(job_id, delay=40)
                await asyncio.sleep(0.4)
                await input_loc.press("Enter")
                await asyncio.sleep(0.4)
        except Exception as e:
            warn(f"Type-to-filter fallback failed: {str(e)[:140]}")

    # Re-evaluate selection verification regardless of path
    try:
        # If we identified an option earlier, click it explicitly
        if await option.count() > 0:
            await option.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            await option.click()
            info("[invite] option:clicked")
    except Exception as e:
        warn(f"Option click failed: {str(e)[:140]}")

    # 5) Verify selection took: visible single item and native select value
    try:
        await form.locator(f"{CHOICES_SINGLE}[data-value='{job_id}']").wait_for(state="visible", timeout=4000)
    except Exception:
        # Some builds may not keep data-value on the single display item
        pass

    hidden_val = await get_native_value(page)
    if hidden_val != job_id:
        warn(f"Hidden select value mismatch: {hidden_val} vs {job_id}")
        return False
    info("[invite] verify:ok")
    return True


async def click_invite_existing(page: Page) -> bool:
    # Global: some menus render detached from the button's DOM context
    try:
        existing = page.locator(INVITE_EXISTING_BTN).first
        if await existing.count() > 0:
            return await safe_click(existing, timeout=6000)
    except Exception:
        pass
    return False


async def invite_flow_for_profile(page: Page, profile_url: str, job_query: str) -> str:
    await page.goto(profile_url, wait_until="domcontentloaded")
    await asyncio.sleep(0.5)

    # 1) Open "Invite to Job" dropdown on profile
    invite_btn = page.locator(PROFILE_INVITE_BTN).first
    if not await safe_click(invite_btn, timeout=10000):
        warn("Could not click 'Invite to Job' on profile")
        return 'failed'

    # 2) Click 'Invite to Existing Job'
    if not await click_invite_existing(page):
        warn("Could not click 'Invite to Existing Job'")
        return 'failed'

    # 3) Wait for modal form and dropdown to be ready
    try:
        await page.locator(MODAL_FORM).first.wait_for(state="visible", timeout=10000)
        await page.locator(f"{MODAL_FORM} {CHOICES_CONTAINER}").first.wait_for(state="visible", timeout=10000)
        # If spinner shows during load, wait for it to hide
        sp = page.locator(SPINNER).first
        if await sp.count() > 0:
            await sp.wait_for(state="hidden", timeout=8000)
        info("[invite] modal:ready")
    except PWTimeout:
        warn("Invite modal did not appear")
        return 'failed'

    # 4) Select job from dropdown
    if not await select_job_in_modal(page, job_query):
        warn("Job selection failed in modal")
        return 'failed'

    # 5) Submit
    submit_btn = page.locator(MODAL_SUBMIT_BTN).first
    info("[invite] submit:clicked")
    if not await safe_click(submit_btn, timeout=10000):
        warn("Could not click final submit")
        return 'failed'

    # 6) Confirm success (toast or modal close)
    try:
        await page.wait_for_selector(SUCCESS_MSG, timeout=8000)
        info("[invite] done:success")
        return 'success'
    except Exception:
        try:
            await page.locator(MODAL_FORM).first.wait_for(state="hidden", timeout=8000)
            info("[invite] done:success")
            return 'success'
        except Exception:
            if await page.locator(ERROR_MSG).count() > 0:
                warn("[invite] done:error")
                return 'failed'
            warn("[invite] done:unknown")
            return 'failed'


async def main_async() -> int:
    csv_path = read_env('CSV_PATH').strip()
    job_query = read_env('JOB_QUERY').strip()

    if not csv_path or not os.path.exists(csv_path):
        err("CSV_PATH missing or file not found. Provide CSV_PATH to a CSV with a 'username' column.")
        return 2
    if not job_query:
        err("JOB_QUERY missing. Provide the numeric Job # to invite to.")
        return 2
    job_digits = re.sub(r"\D", "", job_query)
    if not job_digits:
        err("JOB_QUERY must contain digits (e.g., 805775)")
        return 2

    try:
        usernames = parse_usernames_from_csv(csv_path)
    except Exception as e:
        err(f"CSV Error: {e}")
        return 2

    if not usernames:
        warn("No usernames found in the CSV.")
        return 0

    info(f"Importing {len(usernames)} usernames from CSV...")

    successes: List[str] = []
    failures: List[Tuple[str, int]] = []

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        for idx, username in enumerate(usernames, start=1):
            profile_url = f"https://www.voices.com/profile/{username}"
            info(f"Processing talent {idx} of {len(usernames)}: {username}")
            try:
                result = await invite_flow_for_profile(page, profile_url, job_digits)
            except Exception as e:
                warn(f"Unexpected error for {username}: {e}")
                result = 'failed'

            if result == 'success':
                successes.append(username)
                ok(f"Invited: {username}")
            else:
                failures.append((username, 1))
                err(f"Failed to invite: {username}")

            await asyncio.sleep(0.6)

    info(f"Import invites finished. {len(successes)} succeeded, {len(failures)} failed.")

    if failures:
        try:
            base, _ = os.path.splitext(csv_path)
            out_path = base + "_failures.csv"
            with open(out_path, 'w', encoding='utf-8', newline='') as f:
                w = csv.writer(f)
                w.writerow(["username", "code"]) 
                for (u, code) in failures:
                    w.writerow([u, code])
            info(f"Wrote failures CSV: {out_path}")
        except Exception as e:
            err(f"Failed to write failures CSV: {e}")

    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main_async()))
