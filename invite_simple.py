import asyncio
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout


SEARCH_URL = "https://www.voices.com/talents/search?keywords=&language_ids=419&accent_id=114"
DEFAULT_JOB_ID = "818318"


async def open_existing_job_modal(page) -> Optional[object]:
    """Clicks the first card-level 'Invite to Job' and then 'Invite to Existing Job'.
    Returns the modal locator when visible, else None.
    """
    # Prefer card-level buttons, not modal buttons
    buttons = page.locator(":is(button,[role='button'],a):has-text('Invite to Job')")
    count = await buttons.count()
    if count == 0:
        return None
    for i in range(count):
        btn = buttons.nth(i)
        # Skip buttons inside an already open modal
        try:
            in_modal = await btn.evaluate("el => !!el.closest('.modal, [role=dialog]')")
            if in_modal:
                continue
        except Exception:
            pass
        try:
            await btn.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            await btn.click()
        except Exception:
            continue
        # Click "Invite to Existing Job" from the small dropdown menu near the button
        try:
            item = page.locator(
                ".dropdown-menu :is(button,a,[role='menuitem']):has-text('Invite to Existing Job')"
            ).first
            await item.wait_for(state="visible", timeout=2500)
            await item.click()
        except Exception:
            # If dropdown-menu selector fails, try a global text fallback
            try:
                await page.get_by_text("Invite to Existing Job", exact=False).first.click()
            except Exception:
                continue

        # Wait for modal to appear
        modal = page.locator("[role='dialog'], .modal.show, .modal.in, .modal[open], .modal-content").first
        try:
            await modal.wait_for(state="visible", timeout=5000)
            return modal
        except PWTimeout:
            # Try once more if slow
            try:
                await modal.wait_for(state="visible", timeout=3000)
                return modal
            except Exception:
                pass
    return None


async def select_job_in_modal(modal, job_id: str) -> bool:
    """Within the open modal, open the custom dropdown and pick the job by #ID text.
    Returns True if selection appears to have been made (chip or list reflects the choice).
    """
    job_id = str(job_id)

    # Try Choices.js-like control first
    choices = modal.locator("div.choices[data-type='select-one']").first
    if await choices.count():
        # Check if already selected to the target
        try:
            chip = choices.locator(".choices__list--single .choices__item").first
            if await chip.count():
                txt = (await chip.inner_text()).strip()
                if f"#{job_id}" in txt:
                    return True
        except Exception:
            pass
        # Open dropdown
        try:
            await choices.locator(".choices__inner").first.click()
        except Exception:
            try:
                await choices.click()
            except Exception:
                pass
        # Wait for list, then click the option containing #<job_id>
        try:
            await choices.locator(".choices__list--dropdown").first.wait_for(state="visible", timeout=3000)
        except Exception:
            pass
        opt = choices.locator(
            ".choices__list--dropdown .choices__item[role='option']",
            has_text=f"#{job_id}",
        ).first
        try:
            if await opt.count():
                await opt.scroll_into_view_if_needed()
                await opt.click()
                return True
        except Exception:
            pass

    # Generic custom select fallback: click any combobox-like field then select the option
    try:
        field = modal.locator(":is([role='combobox'], .dropdown, .select, .select__control)").first
        if await field.count():
            try:
                await field.click()
            except Exception:
                pass
            opt2 = modal.get_by_text(f"#{job_id}", exact=False).first
            if await opt2.count():
                await opt2.scroll_into_view_if_needed()
                await opt2.click()
                return True
    except Exception:
        pass

    return False


async def confirm_invite(modal) -> bool:
    """Clicks the modal's primary Invite button and waits for the modal to close.
    Returns True if the modal closes, implying the action was sent/handled.
    """
    confirm = modal.locator(":is(button,[role='button'],a):has-text('Invite to Job')").first
    try:
        await confirm.wait_for(state="visible", timeout=3000)
    except Exception:
        # As a fallback, try a generic primary button inside the modal
        confirm = modal.locator("button.btn.btn-primary").first
    try:
        await confirm.click()
    except Exception:
        # Try force click
        try:
            await confirm.click(force=True)
        except Exception:
            try:
                await confirm.evaluate("el => el.click()")
            except Exception:
                return False

    # Wait for the modal to close (success or already invited toast may appear)
    try:
        await modal.wait_for(state="hidden", timeout=6000)
        return True
    except Exception:
        return False


async def run(job_id: str = DEFAULT_JOB_ID, start_url: str = SEARCH_URL, headless: bool = False, slow_mo: int = 60):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = await browser.new_context(storage_state="voices_auth_state.json")
        page = await context.new_page()

        await page.goto(start_url)
        # Give time for manual login if required; wait until card-level invite buttons are visible
        try:
            await page.wait_for_selector(":is(button,[role='button'],a):has-text('Invite to Job')", timeout=120000)
        except PWTimeout:
            print("Timeout waiting for invite buttons. Ensure you are logged in.")
            return

        # Collect buttons once to avoid stale re-querying while DOM reflows
        # We'll process by index to reduce detachment issues
        idx = 0
        total = await page.locator(":is(button,[role='button'],a):has-text('Invite to Job')").count()
        while idx < total:
            try:
                # Re-evaluate the locator each iteration to cope with DOM changes
                btns = page.locator(":is(button,[role='button'],a):has-text('Invite to Job')")
                if idx >= await btns.count():
                    break
                btn = btns.nth(idx)
                # Skip modal buttons
                try:
                    if await btn.evaluate("el => !!el.closest('.modal, [role=dialog]')"):
                        idx += 1
                        continue
                except Exception:
                    pass
                await btn.scroll_into_view_if_needed()

                modal = await open_existing_job_modal(page)
                if not modal:
                    idx += 1
                    continue

                ok = await select_job_in_modal(modal, job_id)
                if not ok:
                    # Even if selection fails, try to confirm if the correct job is preselected
                    pass
                sent = await confirm_invite(modal)
                await asyncio.sleep(0.5)
            except Exception:
                pass
            finally:
                idx += 1

        await context.close()
        await browser.close()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Invite talents on a Voices search page to a given job ID.")
    ap.add_argument("--job-id", default=DEFAULT_JOB_ID, help="Target job ID (e.g., 818318)")
    ap.add_argument("--start-url", default=SEARCH_URL, help="Search page URL to process")
    ap.add_argument("--headless", action="store_true", help="Run headless")
    ap.add_argument("--slow-mo", type=int, default=60, help="Slow-mo ms between actions")
    args = ap.parse_args()

    asyncio.run(run(job_id=str(args.job_id), start_url=args.start_url, headless=bool(args.headless), slow_mo=int(args.slow_mo)))

