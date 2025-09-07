import asyncio
import os
import re
import random
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PWTimeout, Page, Locator, ElementHandle

# =======================
# Config (env-overridable)
# =======================
START_URL = os.getenv("START_URL", "https://YOUR_TALENT_RESULTS_URL")
JOB_QUERY = os.getenv("JOB_QUERY", "#805775")     # '#12345' (job id) or a unique substring of the title
CDP_URL   = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")

# Timeouts and pacing
DEFAULT_TIMEOUT_MS       = int(os.getenv("DEFAULT_TIMEOUT_MS", "11000"))
POST_CLICK_PAUSE_MS      = int(os.getenv("POST_CLICK_PAUSE_MS", "340"))
PAGE_RENDER_WAIT_MS      = int(os.getenv("PAGE_RENDER_WAIT_MS", "1500"))
SCROLL_STEP_PX           = int(os.getenv("SCROLL_STEP_PX", "320"))
SCROLL_STEP_WAIT_MS      = int(os.getenv("SCROLL_STEP_WAIT_MS", "240"))
MAX_PAGES                = int(os.getenv("MAX_PAGES", "200"))

# Humanization
HUMAN_MIN_DELAY_MS       = int(os.getenv("HUMAN_MIN_DELAY_MS", "150"))
HUMAN_MAX_DELAY_MS       = int(os.getenv("HUMAN_MAX_DELAY_MS", "430"))
HUMAN_MOVE_STEPS         = int(os.getenv("HUMAN_MOVE_STEPS", "24"))
HUMAN_EXTRA_HOVER_MS     = int(os.getenv("HUMAN_EXTRA_HOVER_MS", "300"))
RETRY_ATTEMPTS           = int(os.getenv("RETRY_ATTEMPTS", "3"))

# =======================
# Selectors
# =======================

# Drive by the CTA buttons on the card
INVITE_BUTTONS = "button.btn.btn-primary.btn-invite, button:has-text('Invite to Job'), a:has-text('Invite to Job')"
RESULTS_READY_SELECTOR = INVITE_BUTTONS

# Exact dropdown item (from your snippet)
INVITE_EXISTING_TEXT = "Invite to Existing Job"
INVITE_EXISTING_ITEM = "button.request_a_quote_btn:has-text('Invite to Existing Job')"

# Modal (Bootstrap)
MODAL_ROOT        = ".modal.show"
MODAL_DIALOG      = ".modal.show .modal-dialog"
MODAL_BODY        = ".modal.show .modal-body"
MODAL_FOOTER      = ".modal.show .modal-footer"

# Choices.js (Existing Job field) – anchored to your native select
NATIVE_SELECT           = "#request-quote-open-jobs-list"
# IMPORTANT: use double-quotes inside the XPath to avoid the syntax error you saw
CHOICES_WRAPPER_XPATH   = 'xpath=ancestor::div[contains(@class,"choices")][1]'
CHOICES_FROM_SELECT     = f"{NATIVE_SELECT} >> {CHOICES_WRAPPER_XPATH}"
CHOICES_INNER           = f"{CHOICES_FROM_SELECT} .choices__inner"
CHOICES_DROPDOWN        = f"{CHOICES_FROM_SELECT} .choices__list.choices__list--dropdown"
CHOICES_OPTIONS         = f"{CHOICES_DROPDOWN} .choices__item[role='option']"

# Modal submit CTA
MODAL_SUBMIT_INVITE = (
    f"{MODAL_ROOT} button.btn.btn-primary[type='submit'], "
    f"{MODAL_ROOT} button:has-text('Invite to Job')"
)

# Alerts / toasts
ALERT_DANGER  = ".alert.alert-danger, .alert-danger, [role='alert'].alert-danger"
ALERT_SUCCESS = ".alert.alert-success, .toast-success, .alert-success, .toast"

# Pagination (right-angle icon first)
NEXT_BUTTON_CANDIDATES = [
    "button:has(i.fas.fa-angle-right)",
    "a:has(i.fas.fa-angle-right)",
    ".pagination button:has(i.fas.fa-angle-right)",
    ".pagination a:has(i.fas.fa-angle-right)",
    "button[aria-label='Next']",
    "a[aria-label='Next']",
    "a.pagination-next",
    ".pagination .next a",
    "button:has-text('Next')",
    "a:has-text('Next')",
]

# Optional cookie consent
COOKIE_ACCEPT_BUTTONS = [
    "button:has-text('Accept')",
    "button:has-text('I agree')",
    "button[aria-label='Accept']",
]

# ==============
# Pretty logging
# ==============
def info(msg: str):  print(f"\x1b[36m[i]\x1b[0m {msg}")
def ok(msg: str):    print(f"\x1b[32m[✓]\x1b[0m {msg}")
def warn(msg: str):  print(f"\x1b[33m[!]\x1b[0m {msg}")
def err(msg: str):   print(f"\x1b[31m[×]\x1b[0m {msg}")
def dbg(msg: str):   print(f"\x1b[90m[debug]\x1b[0m {msg}")

# ============
# Human helpers
# ============
def jitter_ms(a: int = HUMAN_MIN_DELAY_MS, b: int = HUMAN_MAX_DELAY_MS) -> int:
    return random.randint(a, b)

async def human_sleep(min_ms: int = HUMAN_MIN_DELAY_MS, max_ms: int = HUMAN_MAX_DELAY_MS):
    await asyncio.sleep(random.uniform(min_ms/1000, max_ms/1000))

async def human_pause(ms: int):
    await asyncio.sleep(ms / 1000)

async def settle(page: Page, base_ms: int = POST_CLICK_PAUSE_MS):
    await human_pause(base_ms + jitter_ms(60, 180))

async def smooth_scroll_to(page: Page, y: int):
    cur = await page.evaluate("() => window.scrollY")
    step = SCROLL_STEP_PX if y > cur else -SCROLL_STEP_PX
    while (step > 0 and cur < y) or (step < 0 and cur > y):
        cur += step
        await page.evaluate("(yy) => window.scrollTo(0, yy)", cur)
        await human_pause(SCROLL_STEP_WAIT_MS + random.randint(0, 120))
    await page.evaluate("(yy) => window.scrollTo(0, yy)", y)
    await human_pause(220 + random.randint(0, 220))

async def human_hover_and_click(page: Page, target: Locator):
    box = await target.bounding_box()
    if not box:
        await target.click()
        return
    x = box["x"] + box["width"]  * random.uniform(0.41, 0.59)
    y = box["y"] + box["height"] * random.uniform(0.41, 0.59)
    await page.mouse.move(x, y, steps=HUMAN_MOVE_STEPS + random.randint(0, 8))
    await human_pause(HUMAN_EXTRA_HOVER_MS + random.randint(0, 180))
    await page.mouse.down()
    await human_sleep(60, 140)
    await page.mouse.up()

# ============
# Core helpers
# ============
async def click_if_visible(scope, selector: str, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> bool:
    try:
        el = scope.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout_ms)
        try:
            await el.scroll_into_view_if_needed(timeout=timeout_ms)
        except Exception:
            pass
        page = scope.page if hasattr(scope, "page") else scope
        await human_hover_and_click(page, el)
        await settle(page)
        return True
    except PWTimeout:
        return False
    except Exception:
        return False

async def wait_for_results(page: Page) -> bool:
    try:
        await page.wait_for_selector(RESULTS_READY_SELECTOR, timeout=DEFAULT_TIMEOUT_MS)
        await human_pause(PAGE_RENDER_WAIT_MS + random.randint(0, 400))
        return True
    except PWTimeout:
        return False

async def ensure_modal_open(page: Page) -> bool:
    try:
        await page.locator(MODAL_ROOT).wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await page.locator(MODAL_DIALOG).wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
        await human_sleep()
        return True
    except PWTimeout:
        return False

async def close_modal_if_possible(page: Page):
    try:
        await page.keyboard.press("Escape")
        await settle(page, 150)
    except Exception:
        pass

def extract_job_id_from_query(query: str) -> Optional[str]:
    m = re.search(r"#\s*(\d+)", query)
    return m.group(1) if m else None

# ======= Split dropdown handler (uses your exact button) =======
async def choose_invite_existing_from_menu(page: Page, button: Locator) -> bool:
    await human_sleep(120, 260)

    # Primary: exact element you shared
    try:
        item = page.locator(INVITE_EXISTING_ITEM).filter(has_text=INVITE_EXISTING_TEXT).first
        await item.wait_for(state="visible", timeout=1500)
        await human_hover_and_click(page, item)
        await settle(page, 180)
        return True
    except Exception:
        pass

    # Fallbacks
    try:
        alt = page.locator(
            "a:has-text('Invite to Existing Job'), "
            "button:has-text('Invite to Existing Job'), "
            "li:has-text('Invite to Existing Job')"
        ).first
        await alt.wait_for(state="visible", timeout=1200)
        await human_hover_and_click(page, alt)
        await settle(page, 180)
        return True
    except Exception:
        pass

    try:
        container = button.locator("xpath=ancestor::*[contains(@class,'dropdown') or contains(@class,'btn-group')][1]")
        near_menu = container.locator(".dropdown-menu, [role='menu']").first
        await near_menu.wait_for(state="visible", timeout=1200)
        item2 = near_menu.locator(
            "a:has-text('Invite to Existing Job'), "
            "button:has-text('Invite to Existing Job'), "
            "li:has-text('Invite to Existing Job')"
        ).first
        await item2.wait_for(state="visible", timeout=1200)
        await human_hover_and_click(page, item2)
        await settle(page, 180)
        return True
    except Exception:
        pass

    try:
        await page.keyboard.press("ArrowDown")
        await human_sleep(80, 160)
        await page.keyboard.press("Enter")
        await settle(page, 180)
        return True
    except Exception:
        return False

# ======= Choices.js in modal (anchored to your select); scroll the DROPDOWN, not the page =======
async def select_job_in_modal(page: Page, query: str) -> bool:
    """
    Open the Choices.js dropdown inside the modal and select an option by ID (#12345)
    or by title substring. We scroll the dropdown list element itself so the page
    behind never moves.
    """
    # Ensure modal exists
    modal = page.locator(MODAL_ROOT)
    await modal.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

    # Anchor to the native select
    native = modal.locator(NATIVE_SELECT)
    await native.wait_for(state="attached", timeout=DEFAULT_TIMEOUT_MS)

    # Open the choices dropdown next to the select
    opened = False
    for _ in range(RETRY_ATTEMPTS):
        if await click_if_visible(page, CHOICES_INNER) or await click_if_visible(page, CHOICES_FROM_SELECT):
            try:
                await page.locator(CHOICES_DROPDOWN).wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
                opened = True
                break
            except PWTimeout:
                await human_sleep()
        else:
            await human_sleep()
    if not opened:
        warn("Could not open job dropdown (Choices.js).")
        return False

    dropdown = page.locator(CHOICES_DROPDOWN).first
    await dropdown.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)

    options = page.locator(CHOICES_OPTIONS)
    count = await options.count()
    if count == 0:
        warn("No options found inside job dropdown.")
        return False

    qlower = query.lower()
    job_id = extract_job_id_from_query(query)

    # Helper: scroll a specific option node into view INSIDE the dropdown
    async def scroll_option_into_view(opt_loc: Locator):
        handle: ElementHandle = await opt_loc.element_handle()
        if handle:
            try:
                await handle.evaluate("el => el.scrollIntoView({block:'center'})")
                await human_sleep(80, 160)
            finally:
                await handle.dispose()

    # Prefer data-value exact match
    if job_id:
        for i in range(count):
            opt = options.nth(i)
            dv = await opt.get_attribute("data-value")
            if dv and dv.strip() == job_id:
                # IMPORTANT: focus dropdown so wheel/scroll targets it, then scroll this option into view
                try:
                    await dropdown.hover(timeout=500)
                except Exception:
                    pass
                await scroll_option_into_view(opt)
                await human_hover_and_click(page, opt)
                await settle(page, 120)
                return True

    # Fallback: match by visible text substring
    for i in range(count):
        opt = options.nth(i)
        txt = (await opt.inner_text()).strip()
        if qlower in txt.lower():
            try:
                await dropdown.hover(timeout=500)
            except Exception:
                pass
            await scroll_option_into_view(opt)
            await human_hover_and_click(page, opt)
            await settle(page, 120)
            return True

    warn(f"No matching job for query: {query}")
    return False

async def submit_invite(page: Page) -> str:
    """
    Click the 'Invite to Job' button in the modal. If it's below the fold,
    scroll the modal body (not the page) to reveal it.
    """
    # Try several times: if not visible, scroll modal content down and retry
    for _ in range(5):
        if await click_if_visible(page, MODAL_SUBMIT_INVITE):
            break
        # Scroll inside the modal body if present; otherwise nudge the dialog itself
        body = page.locator(MODAL_BODY)
        try:
            await body.hover(timeout=400)
            # Use wheel while hovering modal body so background does not scroll
            await page.mouse.wheel(0, 450)
        except Exception:
            # Fallback: scroll the modal dialog slightly
            try:
                await page.locator(MODAL_DIALOG).hover(timeout=400)
                await page.mouse.wheel(0, 450)
            except Exception:
                pass
        await human_sleep(90, 180)
    else:
        return "no_submit"

    # Known error (already invited)
    try:
        err_box = page.locator(ALERT_DANGER)
        await err_box.wait_for(state="visible", timeout=3500)
        text = (await err_box.inner_text()).strip().lower()
        if "already received an invitation" in text or "already invited" in text:
            warn("Already invited error detected.")
            return "already_invited"
    except PWTimeout:
        pass

    # Success
    try:
        suc = page.locator(ALERT_SUCCESS)
        await suc.wait_for(state="visible", timeout=4000)
        ok("Success notification detected.")
        return "success"
    except PWTimeout:
        # If modal closes, assume success
        try:
            await page.locator(MODAL_ROOT).wait_for(state="detached", timeout=1600)
            ok("Modal closed after submit (assuming success).")
            return "success"
        except PWTimeout:
            pass

    warn("Submit result unknown.")
    return "unknown"

# ===========================
# Page-level processing logic
# ===========================
async def process_current_page(page: Page):
    if not await wait_for_results(page):
        return {"seen": 0, "invited": 0, "already": 0, "skipped": 0, "unknown": 0}

    # Trigger lazy content
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await human_pause(900 + random.randint(0, 400))

    buttons = page.locator(INVITE_BUTTONS)
    count = await buttons.count()
    info(f"Found {count} 'Invite to Job' buttons on this page.")
    invited = already = skipped = unknown = 0

    for i in range(count):
        try:
            btn = buttons.nth(i)

            try:
                await btn.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
            except PWTimeout:
                warn(f"Invite button {i} not visible; skipping.")
                skipped += 1
                continue

            # Soft scroll to put the button at a comfy position
            try:
                box = await btn.bounding_box()
                if box:
                    target_y = max(int(box["y"] - 160), 0)
                    await smooth_scroll_to(page, target_y)
            except Exception:
                pass

            # 1) Click the split button
            await human_hover_and_click(page, btn)
            await settle(page, 220)

            # 2) Pick "Invite to Existing Job" from the dropdown
            picked_item = await choose_invite_existing_from_menu(page, btn)
            if not picked_item:
                warn("Could not click 'Invite to Existing Job'; skipping.")
                skipped += 1
                continue

            # 3) Wait for modal (Bootstrap .modal.show)
            if not await ensure_modal_open(page):
                warn("Modal did not open; skipping.")
                skipped += 1
                continue

            # 4) Select job in Choices.js dropdown (anchored; scrolls the dropdown itself)
            picked_job = await select_job_in_modal(page, JOB_QUERY)
            if not picked_job:
                await close_modal_if_possible(page)
                skipped += 1
                continue

            # 5) Submit final "Invite to Job" (scrolls inside modal if needed)
            result = await submit_invite(page)
            if result == "success":
                invited += 1
            elif result == "already_invited":
                already += 1
            elif result.startswith("skipped"):
                skipped += 1
            else:
                unknown += 1

            await close_modal_if_possible(page)

        except Exception as e:
            err(f"Exception while processing button {i}: {e}")
            unknown += 1

        await human_sleep()

    return {"seen": count, "invited": invited, "already": already, "skipped": skipped, "unknown": unknown}

async def go_to_next_page(page: Page) -> bool:
    # Snapshot length to detect change
    try:
        before_len = len(await page.content())
    except Exception:
        before_len = None

    for sel in NEXT_BUTTON_CANDIDATES:
        cand = page.locator(sel).first
        try:
            if await cand.count() == 0:
                continue
            await cand.wait_for(state="visible", timeout=2000)

            aria_disabled = (await cand.get_attribute("aria-disabled")) or ""
            classes = (await cand.get_attribute("class")) or ""
            if aria_disabled.strip().lower() == "true" or "disabled" in (classes or "").split():
                continue

            await human_hover_and_click(page, cand)
            try:
                await page.wait_for_load_state("networkidle", timeout=7000)
            except Exception:
                await human_pause(700)

            try:
                after_len = len(await page.content())
            except Exception:
                after_len = None

            if before_len is None or after_len is None or after_len != before_len:
                await human_sleep(300, 700)
                return True
        except Exception:
            continue
    return False

async def dismiss_cookies_if_any(page: Page):
    for sel in COOKIE_ACCEPT_BUTTONS:
        if await click_if_visible(page, sel, timeout_ms=2500):
            ok(f"Dismissed cookie banner via: {sel}")
            break

# =========
# Main flow
# =========
async def main():
    info(f"Using START_URL: {START_URL}")
    info(f"Using JOB_QUERY : {JOB_QUERY}")
    info(f"Using CDP_URL  : {CDP_URL}")

    async with async_playwright() as p:
        # Attach to already-running Chrome
        browser = await p.chromium.connect_over_cdp(CDP_URL)

        # Reuse persistent context (Chrome has one)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()

        # Open a new tab
        page = await context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        # Go to results page
        await page.goto(START_URL, wait_until="domcontentloaded")
        await dismiss_cookies_if_any(page)
        await human_pause(800 + random.randint(0, 300))

        totals = {"seen": 0, "invited": 0, "already": 0, "skipped": 0, "unknown": 0}
        page_num = 1

        while page_num <= MAX_PAGES:
            info(f"--- Processing page {page_num} ---")
            stats = await process_current_page(page)
            for k in totals:
                totals[k] += stats.get(k, 0)

            print(f"[Page {page_num}] Seen={stats['seen']} | Invited={stats['invited']} | Already={stats['already']} | Skipped={stats['skipped']} | Unknown={stats['unknown']}")

            moved = await go_to_next_page(page)
            if not moved:
                info("No further pages detected.")
                break

            await human_sleep(500, 1000)
            page_num += 1

        ok(
            f"DONE. Total Seen={totals['seen']}, Invited={totals['invited']}, "
            f"Already={totals['already']}, Skipped={totals['skipped']}, Unknown={totals['unknown']}"
        )

        # Close only the tab we opened; keep live Chrome running
        try:
            await page.close()
        except Exception:
            pass
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
