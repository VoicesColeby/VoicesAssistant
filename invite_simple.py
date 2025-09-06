import os
import json
import asyncio
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout


SEARCH_URL = "https://www.voices.com/talents/search?keywords=&language_ids=419&accent_id=114"
DEFAULT_JOB_ID = "818318"


async def open_existing_job_modal(page, index: int) -> Optional[object]:
    """Click the Nth card's 'Invite to Job' → 'Invite to Existing Job', then return the modal."""
    # Target by card to avoid matching modal buttons
    card_sel = "article:has(button:has-text('Invite to Job')), [data-testid='talent-card'], [data-qa='talent-card']"
    cards = page.locator(card_sel)
    total = await cards.count()
    if index >= total:
        return None
    card = cards.nth(index)
    btn = card.locator(":is(button,[role='button'],a):has-text('Invite to Job')").first
    try:
        await btn.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        await btn.click()
    except Exception:
        return None

    # Click the dropdown item next to the head button
    try:
        menu_item = page.locator(
            ".dropdown-menu :is(button,a,[role='menuitem']):has-text('Invite to Existing Job'), "
            ".dropdown-menu :is(button,a,[role='menuitem']):has-text('Invite to Existing Jobs'), "
            ".dropdown-menu :is(button,a,[role='menuitem']):has-text('Request a Quote')",
        ).first
        await menu_item.wait_for(state="visible", timeout=2500)
        await menu_item.click()
    except Exception:
        try:
            await page.get_by_text("Invite to Existing Job", exact=False).first.click()
        except Exception:
            return None

    modal = page.locator("[role='dialog'], .modal.show, .modal.in, .modal[open], .modal-content").first
    try:
        await modal.wait_for(state="visible", timeout=5000)
    except PWTimeout:
        try:
            await modal.wait_for(state="visible", timeout=3000)
        except Exception:
            return None
    return modal


async def select_job_in_modal(modal, job_id: str) -> bool:
    """Within the open modal, open the custom dropdown and pick the job by #ID text.
    Returns True if selection appears to have been made (chip or list reflects the choice).
    """
    job_id = str(job_id)

    # First try: set the hidden <select> directly
    try:
        await modal.select_option('#request-quote-open-jobs-list', job_id)
        await asyncio.sleep(0.15)
        # Verify chip reflects the choice
        chip_txt = await modal.locator('.choices__list--single .choices__item').first.inner_text()
        if f"#{job_id}" in (chip_txt or ""):
            try:
                log_event({"type": "job_select", "method": "hidden_select", "job_id": str(job_id)})
            except Exception:
                pass
            return True
    except Exception:
        pass

    # Fallback: Choices.js widget
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
                try:
                    log_event({"type": "job_select", "method": "choices_click", "job_id": str(job_id)})
                except Exception:
                    pass
                return True
        except Exception:
            pass

    # Last fallback: generic custom select/combobox
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
        try:
            log_event({"type": "confirm", "status": "modal_hidden"})
        except Exception:
            pass
        return True
    except Exception:
        try:
            log_event({"type": "confirm", "status": "timeout"})
        except Exception:
            pass
        return False


def log_event(evt: dict):
    try:
        evt = dict(evt)
        print("[invite_simple] " + json.dumps(evt))
        lf = os.environ.get("VOICES_LOG_FILE", "").strip()
        if lf:
            with open(lf, "a", encoding="utf-8") as f:
                f.write(json.dumps(evt) + "\n")
    except Exception:
        pass


async def accept_cookies(page) -> None:
    try:
        btn = page.locator(":is(button,a,[role='button']):has-text('Accept'), :is(button,a,[role='button']):has-text('I agree'), :is(button,a,[role='button']):has-text('Got it')").first
        if await btn.count():
            await btn.click()
            await asyncio.sleep(0.2)
            log_event({"type": "cookies", "action": "accepted"})
    except Exception:
        pass


async def run(job_id: str = DEFAULT_JOB_ID, start_url: str = SEARCH_URL, headless: bool = False, slow_mo: int = 60):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=slow_mo)
        context = await browser.new_context(storage_state="voices_auth_state.json")
        page = await context.new_page()

        log_event({"type": "start", "url": start_url, "job_id": str(job_id)})

        try:
            await page.goto(start_url)
            await page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        await accept_cookies(page)

        # Initial wait for Invite buttons to allow manual login and content load
        found = False
        for attempt in range(120):  # up to ~120 seconds
            try:
                cards = page.locator("article:has(button:has-text('Invite to Job')), [data-testid='talent-card'], [data-qa='talent-card']")
                count = await cards.count()
                log_event({"type": "wait_buttons", "attempt": attempt+1, "count": int(count)})
                if count > 0:
                    found = True
                    break
                # small scroll pulse to trigger lazy load
                await page.mouse.wheel(0, 800)
                await asyncio.sleep(1.0)
            except Exception:
                await asyncio.sleep(1.0)
        if not found:
            log_event({"type": "exit", "reason": "no_buttons"})
            await context.close()
            await browser.close()
            return

        # Process invites by re-computing buttons each loop (buttons may change after invites)
        idx = 0
        while True:
            try:
                cards = page.locator("article:has(button:has-text('Invite to Job')), [data-testid='talent-card'], [data-qa='talent-card']")
                count = await cards.count()
                if idx >= count:
                    break
                log_event({"type": "invite_open", "idx": int(idx), "count": int(count)})
                modal = await open_existing_job_modal(page, idx)
                if not modal:
                    log_event({"type": "invite_open_failed", "idx": int(idx)})
                    idx += 1
                    continue
                await asyncio.sleep(0.2)
                ok_sel = await select_job_in_modal(modal, job_id)
                log_event({"type": "invite_select", "idx": int(idx), "selected": bool(ok_sel), "job_id": str(job_id)})
                ok_conf = await confirm_invite(modal)
                log_event({"type": "invite_confirm", "idx": int(idx), "confirmed": bool(ok_conf)})
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
