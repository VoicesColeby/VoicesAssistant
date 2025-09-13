import os, asyncio, random, json, time, re, argparse
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

START_URL = os.environ.get(
    "VOICES_START_URL",
    "https://www.voices.com/talents/search?keywords=&language_ids=1",
)
STORAGE_STATE = "voices_auth_state.json"
CHECKPOINT = "voices_invite_checkpoint.json"
# Persisted store of invited talent IDs to skip across runs
INVITED_DB = os.environ.get("VOICES_INVITED_DB", "invited_ids.json")
# Only invite to this job ID (can override via VOICES_JOB_ID)
# Job selection is optional; default to no filtering and rely on the blue "Invite" confirm
# Set VOICES_JOB_ID to force targeting a specific job ID if desired
REQUIRED_JOB_ID = os.environ.get("VOICES_JOB_ID", "").strip()

# Chrome profile reuse (optional; helps use your already-signed-in Chrome)
# Override with env vars if needed:
#   CHROME_USER_DATA_DIR  e.g. C:\Users\<you>\AppData\Local\Google\Chrome\User Data
#   CHROME_PROFILE        e.g. "Default", "Profile 1"
#   USE_SYSTEM_CHROME     set to "0" to disable and use bundled Chromium
CHROME_USER_DATA_DIR = os.environ.get(
    "CHROME_USER_DATA_DIR",
    os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "Local", "Google", "Chrome", "User Data"),
)
CHROME_PROFILE = os.environ.get("CHROME_PROFILE", "Default")
# Prefer CDP attach to an already-running Chrome and avoid launching new browsers by default
USE_SYSTEM_CHROME = os.environ.get("USE_SYSTEM_CHROME", "0").lower() in {"1", "true", "yes", "on"}
CONNECT_RUNNING_CHROME = os.environ.get("CONNECT_RUNNING_CHROME", "1").lower() in {"1", "true", "yes", "on"}
CHROME_CDP_URL = os.environ.get("CHROME_CDP_URL", "http://127.0.0.1:9222")
# If true, do not fall back to launching a new browser when CDP attach fails
REQUIRE_CDP = os.environ.get("REQUIRE_CDP", "1").lower() in {"1", "true", "yes", "on"}

# Pause control
PAUSE_FILE = os.environ.get("VOICES_PAUSE_FILE", "PAUSE").strip()

# limits & pacing
TARGET_INVITES = 999999  # effectively "all"; lower if you want to cap
CLICK_PAUSE = (0.9, 1.8) # per-click jitter
PAGE_PAUSE  = (2.0, 4.0) # between pages
SCROLL_PASSES = 2        # help trigger lazy-loading on each page

# dry-run and logging
DRY_RUN = os.environ.get("VOICES_DRY_RUN", "0").lower() in {"1", "true", "yes", "on"}
LOG_FILE = os.environ.get("VOICES_LOG_FILE", "").strip()

# Favorites mode (optional alternative to inviting)
USE_FAVORITES = os.environ.get("VOICES_USE_FAVORITES", "0").lower() in {"1", "true", "yes", "on"}
FAVORITES_LIST_TITLE = os.environ.get("VOICES_FAVORITES_LIST", "").strip()
_FAVORITES_LIST_SELECTED = False  # set True after first successful list selection

# Strict job match disabled by default; we rely on selection step to set correct job

# selectors (you may tweak after a quick Inspect pass)
TALENT_CARD = "[data-testid='talent-card'], [data-qa='talent-card'], article:has(button:has-text('Invite'))"
INVITE_MENU_BTN = ":is(button, [role='button'], a):has-text('Invite to Job'), :is(button, [role='button'], a):has-text('Invite'), :is(button, [role='button'], a):has-text('Send Invite'), :is(button, [role='button'], a):has-text('Request a Quote')"  # on the card
# Broaden modal selector to include common Bootstrap/ARIA modals used on voices.com
INVITE_MODAL = "[role='dialog'], [aria-modal='true'], .modal.show, .modal.in, .modal[open], .modal-dialog, .modal-content, .ReactModal__Content"
EXISTING_TAB = f"{INVITE_MODAL} >> :is(button, a, [role='tab']):has-text('Invite to Existing Jobs'), {INVITE_MODAL} >> :is(button, a, [role='tab']):has-text('Invite to Existing Job'), {INVITE_MODAL} >> :is(button, a, [role='tab']):has-text('Existing Jobs'), {INVITE_MODAL} >> :is(button, a, [role='tab']):has-text('Use existing'), {INVITE_MODAL} >> :is(button, a, [role='tab']):has-text('Existing')"
# Dropdown menu item that opens the modal
EXISTING_MENU_ITEM = ":is(button, a, [role='menuitem']):has-text('Invite to Existing Job'), :is(button, a, [role='menuitem']):has-text('Invite to Existing Jobs'), :is(button, a, [role='menuitem']):has-text('Request a Quote'), button.request_a_quote_btn.menuitem"
# A final confirmation button sometimes appears after choosing the job row
FINAL_INVITE_BTN = f"#submit-request-quote, {INVITE_MODAL} >> button#submit-request-quote, {INVITE_MODAL} >> :is(button, [role='button'], a):has-text('Invite to Job'), {INVITE_MODAL} >> :is(button, [role='button'], a):has-text('Send Invite'), {INVITE_MODAL} >> :is(button, [role='button'], a):has-text('Invite'), {INVITE_MODAL} >> :is(button, [role='button'], a):has-text('Request a Quote'), {INVITE_MODAL} >> :is(button, [role='button'], a):has-text('Submit Request'), {INVITE_MODAL} >> :is(button, [role='button'], a):has-text('Send Request'), {INVITE_MODAL} >> button[type='submit']"
# Non-scoped variant as a fallback when the modal container cannot be detected
FINAL_INVITE_BTN_ANY = ":is(#submit-request-quote, button#submit-request-quote), :is(button, [role='button'], a):has-text('Invite to Job'), :is(button, [role='button'], a):has-text('Send Invite'), :is(button, [role='button'], a):has-text('Invite'), :is(button, [role='button'], a):has-text('Request a Quote'), :is(button, [role='button'], a):has-text('Submit Request'), :is(button, [role='button'], a):has-text('Send Request'), button.btn.btn-primary:has-text('Invite')"
JOB_ROW = f"{INVITE_MODAL} >> :is([data-testid='job-row'], .job-item, li, tr)"
JOB_TITLE_EL = ":is(h3, h4, .job-title, [data-testid='job-title'], a, span)"
JOB_INVITE_BTN = f"{JOB_ROW} >> :is(button, a):has-text('Invite'), {JOB_ROW} >> :is(button, a):has-text('Select'), {JOB_ROW} >> :is(button, a):has-text('Choose')"
SUCCESS_TOAST = ":is(.Toastify__toast, [role='status']):has-text('Invited'), :has-text('Invitation sent'), :has-text('invited')"

# Favorites selectors (tailored for Voices markup, resilient to variants)
FAVORITE_BTN = ", ".join([
    ".action-list-btn.fa-heart",
    "i.fa-heart",
    "[aria-label*='Save to Favorites' i]",
    "[title*='Save to Favorites' i]",
    "[title*='Favorite' i]",
    "[title*='Favourites' i]",
])
FAVORITE_ACTIVE = ":is([aria-pressed='true'], [title*='Favorited' i], [aria-label*='Favorited' i], .saved, .favorited, .favourited, .active, .selected)"
FAVORITES_UI_CONTAINERS = ":is([role='dialog'], [role='menu'], [role='listbox'], .modal.show, .dropdown-menu, .popover, .ReactModal__Content)"
FAVORITE_SUCCESS = ":is(.Toastify__toast, [role='status']):has-text('Saved'), :has-text('Added to Favorites'), :has-text('Favourites'), :has-text('Added to list'), :has-text('saved')"

# auth selectors
SIGNIN_LINK = ":is(a,button,[role='button']):has-text('Sign in'), :is(a,button,[role='button']):has-text('Log in')"
EMAIL_INPUT = "input[type='email'], input[name='email'], #email"
PASSWORD_INPUT = "input[type='password'], input[name='password'], #password"
SUBMIT_LOGIN = "button[type='submit'], button:has-text('Sign in'), button:has-text('Log in')"

# login helpers/selectors to avoid Google/OAuth and force email flow
CLIENT_OR_BUYER_TAB = ":is(button,a,[role='tab'],[role='button']):has-text('Client'), :is(button,a,[role='tab'],[role='button']):has-text('Buyer'), :is(button,a,[role='tab'],[role='button']):has-text(\"I'm hiring\")"
EMAIL_FLOW_BUTTONS = ":is(button,a,[role='button']):has-text('Continue with email'), :is(button,a,[role='button']):has-text('Sign in with email'), :is(button,a,[role='button']):has-text('Use email'), :is(button,a,[role='button']):has-text('Email and password')"
COOKIE_ACCEPT_BUTTONS = ":is(button,a,[role='button']):has-text('Accept'), :is(button,a,[role='button']):has-text('I agree'), :is(button,a,[role='button']):has-text('Got it')"

PAGINATION_NEXT = "nav[aria-label='Pagination'] >> text=Next"
CURRENT_PAGE = "nav[aria-label='Pagination'] [aria-current='page']"
PAGINATION_NUMBERS = "nav[aria-label='Pagination'] :is(a,button)"
# Broaden selectors to catch various Next controls (icon-only, rel=next, title, aria-label)
NEXT_LINK_SEL = ", ".join([
    "a[rel='next']",
    "a[aria-label='Next']",
    "a[title*='Next']",
    "a:has(span.sr-only:has-text('Next Page'))",
    "nav a:has(i.fa-angle-right)",
    ".pagination a:has(i.fa-angle-right)",
    "nav a:has(i.fa-chevron-right)",
    ".pagination a:has(i.fa-chevron-right)",
])

async def jitter(a,b):
    await asyncio.sleep(random.uniform(a,b))

def load_checkpoint():
    if Path(CHECKPOINT).exists():
        return json.loads(Path(CHECKPOINT).read_text())
    return {"page_num": 1, "invited": 0}

def save_checkpoint(state): Path(CHECKPOINT).write_text(json.dumps(state, indent=2))

def _resolve_chrome_profile():
    """Return (user_data_dir, profile_dir_name) for system Chrome if available.
    Detection priority:
      1) Respect CHROME_USER_DATA_DIR if it exists.
      2) If CHROME_PROFILE env provided and exists under UDD, use it.
      3) Read Chrome's "Local State" JSON for last_used profile.
      4) Fallback to "Default" if present.
      5) Fallback to first matching "Profile *" (e.g., "Profile 1").
    """
    try:
        udd = CHROME_USER_DATA_DIR
        if not udd or not Path(udd).exists():
            return None, None

        # If an explicit profile was provided, prefer it when present
        prof_env = CHROME_PROFILE
        if prof_env and Path(udd, prof_env).exists():
            return udd, prof_env

        # Try reading Chrome's Local State for last_used
        local_state_path = Path(udd) / "Local State"
        try:
            if local_state_path.exists():
                data = json.loads(local_state_path.read_text(encoding="utf-8"))
                last_used = (
                    data.get("profile", {}).get("last_used")
                    or (data.get("profile", {}).get("last_active_profiles") or [None])[0]
                )
                if last_used and Path(udd, last_used).exists():
                    return udd, last_used
        except Exception:
            pass

        # Common default
        if Path(udd, "Default").exists():
            return udd, "Default"

        # Any "Profile N" directory
        try:
            candidates = sorted(
                [p.name for p in Path(udd).iterdir() if p.is_dir() and p.name.lower().startswith("profile ")]
            )
            if candidates:
                return udd, candidates[0]
        except Exception:
            pass
    except Exception:
        pass
    return None, None

async def is_logged_in(page) -> bool:
    """Best-effort detection of authenticated state on Voices.
    Returns True if we infer the user is logged in.
    """
    # If URL is clearly a login page
    url = (page.url or "").lower()
    if any(k in url for k in ("/login", "signin", "sign-in")):
        return False

    # If a Sign in / Log in control is visible, assume logged out
    try:
        link = await page.query_selector(SIGNIN_LINK)
        if link and await link.is_visible():
            return False
    except Exception:
        pass

    # If an Invite button is present on talents page, you're likely logged in
    try:
        btn = await page.query_selector(INVITE_MENU_BTN)
        if btn:
            return True
    except Exception:
        pass

    # If a profile/account control is visible, assume logged in
    try:
        prof = await page.query_selector(":is([data-testid='user-avatar'], [data-qa='user-menu'], [aria-label*='Account'], [aria-label*='Profile'])")
        if prof and await prof.is_visible():
            return True
    except Exception:
        pass

    # Default to True if we cannot detect a login prompt
    return True

async def login_if_needed(context, page, manual_login: bool = False):
    """Ensure we are authenticated, then land on START_URL.
    Relies on VOICES_EMAIL and VOICES_PASSWORD env vars when login is required.
    """
    await page.goto(START_URL)
    await page.wait_for_load_state("domcontentloaded")

    # Try to accept cookie banners early so they don't block detection/clicks
    try:
        btn = await page.query_selector(COOKIE_ACCEPT_BUTTONS)
        if btn and await btn.is_visible():
            await btn.click()
            await asyncio.sleep(0.3)
    except Exception:
        pass

    # If already logged in, nothing to do
    if await is_logged_in(page):
        return

    # If the user prefers to log in manually (e.g., via Google SSO),
    # do minimal navigation and avoid auto-clicking/closing popups.
    if manual_login:
        try:
            link = await page.query_selector(SIGNIN_LINK)
            if link:
                await link.click()
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(0.5)
        except Exception:
            pass
    else:
        # Automated login assistance
        try:
            link = await page.query_selector(SIGNIN_LINK)
            if link:
                await link.click()
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Lightly handle cookie notices that may obscure buttons
        try:
            btn = await page.query_selector(COOKIE_ACCEPT_BUTTONS)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(0.3)
        except Exception:
            pass

        # Prefer "Client/Buyer" tab if a split login exists
        try:
            tab = await page.query_selector(CLIENT_OR_BUYER_TAB)
            if tab and await tab.is_visible():
                await tab.click()
                await asyncio.sleep(0.3)
        except Exception:
            pass

        # Try to switch to an explicit email flow to avoid Google OAuth
        try:
            email_btn = await page.query_selector(EMAIL_FLOW_BUTTONS)
            if email_btn and await email_btn.is_visible():
                await email_btn.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

    # If we're on a login form (by URL or by fields), proceed
    login_form = False
    try:
        url = (page.url or "").lower()
        if any(k in url for k in ("/login", "signin", "sign-in")):
            login_form = True
    except Exception:
        pass
    if not login_form:
        try:
            if await page.query_selector(EMAIL_INPUT) and await page.query_selector(PASSWORD_INPUT):
                login_form = True
        except Exception:
            pass

    if manual_login and login_form:
        # Give the user time to complete SSO manually. We poll for login.
        print("[login] Manual mode: complete login in the opened browser.")
        for i in range(900):  # up to ~15 minutes
            try:
                if await is_logged_in(page):
                    print("[login] Detected logged-in state. Continuing…")
                    break
            except Exception:
                pass
            if i % 30 == 0:
                print("[login] Waiting for manual login… (press Ctrl+C to abort)")
            await asyncio.sleep(1.0)
    elif login_form:
        email = os.environ.get("VOICES_EMAIL")
        pwd = os.environ.get("VOICES_PASSWORD")
        assert email and pwd, "Set VOICES_EMAIL and VOICES_PASSWORD env vars."

        # Ensure email/password fields are visible; try to reveal the email form if hidden
        try:
            await page.wait_for_selector(EMAIL_INPUT, state="visible", timeout=8000)
        except PWTimeout:
            # Try clicking email flow button(s) again if present
            try:
                email_btn = await page.query_selector(EMAIL_FLOW_BUTTONS)
                if email_btn:
                    await email_btn.click()
                    await asyncio.sleep(0.4)
            except Exception:
                pass
        # Final fallback: set value via script in case field remains hidden
        try:
            await page.fill(EMAIL_INPUT, email)
        except Exception:
            try:
                await page.eval_on_selector(
                    EMAIL_INPUT,
                    "(el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); }",
                    email,
                )
            except Exception:
                pass

        # Password field
        try:
            await page.wait_for_selector(PASSWORD_INPUT, state="visible", timeout=5000)
        except PWTimeout:
            pass
        try:
            await page.fill(PASSWORD_INPUT, pwd)
        except Exception:
            try:
                await page.eval_on_selector(
                    PASSWORD_INPUT,
                    "(el, v) => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); }",
                    pwd,
                )
            except Exception:
                pass

        # Submit the form
        try:
            await page.click(SUBMIT_LOGIN)
        except Exception:
            # Press Enter as a fallback
            try:
                await page.keyboard.press("Enter")
            except Exception:
                pass

        # If any Google OAuth popups appear, close them (automated mode only)
        if not manual_login:
            try:
                for p in list(context.pages):
                    u = (p.url or "").lower()
                    if p is not page and ("accounts.google." in u or "oauth2" in u or "signin/v2" in u):
                        try:
                            await p.close()
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            await page.wait_for_load_state("networkidle")
        except PWTimeout:
            pass
        await asyncio.sleep(1.0)

    # Ensure we land back on the intended search page
    await page.goto(START_URL)
    try:
        await page.wait_for_load_state("networkidle")
    except PWTimeout:
        await page.wait_for_load_state("domcontentloaded")
    # Save auth state when possible (not available when attaching over CDP without a context)
    try:
        if context:
            await context.storage_state(path=STORAGE_STATE)
    except Exception:
        pass

DEBUG = os.environ.get("VOICES_DEBUG", "0").lower() in {"1", "true", "yes", "on"}

def log_event(evt: dict):
    """Append a structured event to JSONL log (if configured) and echo when DEBUG is on."""
    try:
        evt = dict(evt)
        evt.setdefault("ts", time.time())
        if LOG_FILE:
            try:
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(evt, ensure_ascii=False) + "\n")
            except Exception:
                pass
        if DEBUG:
            try:
                print("[event] " + json.dumps(evt, ensure_ascii=False))
            except Exception:
                pass
    except Exception:
        pass

# invited IDs database (simple JSON key -> metadata)
_INVITED_DB_CACHE = None  # type: ignore[var-annotated]

def _invited_db_load() -> dict:
    global _INVITED_DB_CACHE
    if _INVITED_DB_CACHE is not None:
        return _INVITED_DB_CACHE
    try:
        p = Path(INVITED_DB)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            # support either list[str] or dict[str,meta]
            if isinstance(data, list):
                data = {str(x): {"ts": time.time()} for x in data}
            if isinstance(data, dict):
                _INVITED_DB_CACHE = data
                return _INVITED_DB_CACHE
    except Exception:
        pass
    _INVITED_DB_CACHE = {}
    return _INVITED_DB_CACHE

def invited_db_has(talent_id: str) -> bool:
    try:
        db = _invited_db_load()
        return str(talent_id) in db
    except Exception:
        return False

def invited_db_add(talent_id: str, url: str = ""):
    try:
        db = _invited_db_load()
        db[str(talent_id)] = {"ts": time.time(), "url": url}
        Path(INVITED_DB).write_text(json.dumps(db, indent=2), encoding="utf-8")
        log_event({"type": "invited_db_add", "talent_id": str(talent_id), "url": url})
    except Exception:
        pass

async def _card_is_favorited(card) -> bool:
    try:
        mark = await card.query_selector(FAVORITE_ACTIVE)
        if mark and await mark.is_visible():
            return True
    except Exception:
        pass
    return False

async def _is_heart_active(el) -> bool:
    try:
        title = None
        aria = None
        try:
            title = await el.get_attribute("title")
        except Exception:
            title = None
        try:
            aria = await el.get_attribute("aria-pressed")
        except Exception:
            aria = None
        if title and "favorited" in title.lower():
            return True
        if aria and aria.lower() in ("true", "1"):
            return True
    except Exception:
        pass
    return False

async def _click_heart_element(page, heart) -> bool:
    try:
        if await _is_heart_active(heart):
            return False
        try:
            await heart.scroll_into_view_if_needed()
        except Exception:
            pass
        if DRY_RUN:
            log_event({"type": "would_click", "target": "favorite_heart_element"})
            return True
        try:
            await heart.click()
            return True
        except asyncio.CancelledError:
            return False
        except Exception:
            try:
                # Click nearest clickable ancestor if icon itself isn't clickable
                await heart.evaluate("el => (el.closest('button, a, [role=button]') || el).click()")
                return True
            except Exception:
                return False
    except Exception:
        return False

async def _click_heart_on_card(page, card) -> bool:
    try:
        btn = await card.query_selector(FAVORITE_BTN)
        if not btn:
            try:
                await card.hover()
                btn = await card.query_selector(FAVORITE_BTN)
            except Exception:
                btn = None
        if not btn:
            return False
        try:
            await btn.scroll_into_view_if_needed()
        except Exception:
            pass
        if DRY_RUN:
            log_event({"type": "would_click", "target": "favorite_heart"})
            return True
        try:
            await btn.click()
            return True
        except asyncio.CancelledError:
            return False
        except Exception:
            # try force click on the located element
            try:
                await btn.evaluate("el => el.click()")
                return True
            except Exception:
                return False
    except Exception:
        return False

async def _ensure_favorites_list_selected(page) -> None:
    global _FAVORITES_LIST_SELECTED
    if _FAVORITES_LIST_SELECTED:
        return
    title = FAVORITES_LIST_TITLE
    if not title:
        # Nothing to pick; mark as selected to avoid repeated attempts
        _FAVORITES_LIST_SELECTED = True
        return
    try:
        # Log attempt for debugging
        try:
            log_event({"type": "favorites_pick_attempt", "title": title})
        except Exception:
            pass
        # Wait briefly for any favorites chooser container
        try:
            await page.wait_for_selector(FAVORITES_UI_CONTAINERS, timeout=2500)
        except Exception:
            pass
        container = page.locator(FAVORITES_UI_CONTAINERS).first
        # Prefer span.no-overflow (as in Voices list items), but allow several roles/elements
        item = container.locator(":is(span.no-overflow, [role='menuitem'], [role='option'], button, a, li, div)", has_text=title).first
        try:
            await item.wait_for(state="visible", timeout=2500)
            try:
                await item.click()
            except Exception:
                # Click nearest clickable ancestor if span isn't directly clickable
                parent = item.locator("xpath=ancestor-or-self::*[self::button or self::a or self::label or self::li or self::div][1]").first
                await parent.click()
            _FAVORITES_LIST_SELECTED = True
            # Brief settle and optionally wait for a success toast
            await asyncio.sleep(0.2)
            try:
                await page.wait_for_selector(FAVORITE_SUCCESS, timeout=1500)
            except Exception:
                pass
        except Exception:
            # If not clickable or not found, try a global lookup (unscoped)
            try:
                item2 = page.locator("span.no-overflow", has_text=title).first
                await item2.wait_for(state="visible", timeout=2000)
                try:
                    await item2.click()
                except Exception:
                    try:
                        parent2 = item2.locator("xpath=ancestor-or-self::*[self::button or self::a or self::label or self::li or self::div][1]").first
                        await parent2.click()
                    except Exception:
                        try:
                            control = item2.locator("xpath=ancestor::*[self::label or self::li or self::div][1]//input[@type='checkbox' or @type='radio']").first
                            await control.click()
                        except Exception:
                            pass
                _FAVORITES_LIST_SELECTED = True
                await asyncio.sleep(0.2)
            except Exception:
                pass
        # If we think we clicked, wait for UI to confirm (toast or chooser close)
        if _FAVORITES_LIST_SELECTED:
            try:
                await page.wait_for_selector(FAVORITE_SUCCESS, timeout=1200)
            except Exception:
                try:
                    await page.locator(FAVORITES_UI_CONTAINERS).first.wait_for(state="hidden", timeout=1200)
                except Exception:
                    pass
            try:
                log_event({"type": "favorites_picked", "title": title})
            except Exception:
                pass
    except Exception:
        pass

async def pause_if_requested():
    """If a pause file is present, block until it is removed.
    Configure via VOICES_PAUSE_FILE or --pause-file.
    """
    try:
        pf = PAUSE_FILE
        if not pf:
            return
        p = Path(pf)
        if p.exists():
            printed = False
            while p.exists():
                if not printed:
                    try:
                        print(f"[pause] Detected '{p}'. Delete the file to resume.")
                    except Exception:
                        pass
                    printed = True
                await asyncio.sleep(1.0)
    except Exception:
        pass

async def accept_cookies_if_present(page):
    try:
        btn = await page.query_selector(COOKIE_ACCEPT_BUTTONS)
        if btn and await btn.is_visible():
            try:
                await btn.click()
            except Exception:
                try:
                    await btn.click(force=True)
                except Exception:
                    try:
                        await page.eval_on_selector(COOKIE_ACCEPT_BUTTONS, "el => el.click()")
                    except Exception:
                        pass
            try:
                log_event({"type": "cookies_accepted"})
            except Exception:
                pass
    except Exception:
        pass

async def _click_existing_job_dropdown(page, head_btn) -> bool:
    """After clicking the head 'Invite to Job' button on a card, click the
    dropdown item 'Invite to Existing Job' as reliably as possible.

    Strategy:
      - Click the head button (toggle) and wait briefly.
      - Wait for any matching menuitem to become visible.
      - Prefer the visible menu item that is spatially closest to the head button.
    """
    try:
        # Ensure the card/head button is in view and hovered to keep the menu anchored right
        await head_btn.scroll_into_view_if_needed()
        try:
            await head_btn.hover()
        except Exception:
            pass

        # Click to open the dropdown; keep retries minimal to avoid toggling
        for attempt in range(3):
            try:
                await head_btn.click()
            except Exception:
                # Try force and JS, then coords
                try:
                    await head_btn.click(force=True)
                except Exception:
                    try:
                        await head_btn.evaluate("el => el.click()")
                    except Exception:
                        try:
                            bb = await head_btn.bounding_box()
                            if bb:
                                cx = bb["x"] + bb["width"]/2
                                cy = bb["y"] + bb["height"]/2
                                await page.mouse.move(cx, cy, steps=1)
                                await page.mouse.click(cx, cy, delay=30)
                        except Exception:
                            pass
            try:
                log_event({"type": "head_btn_click_attempt", "attempt": attempt+1})
            except Exception:
                pass
            await asyncio.sleep(0.25)

            # First, try container-scoped menu item inside this card
            try:
                container = await head_btn.evaluate_handle(
                    "el => el.closest('.ResultCard-action') || el.closest('.portfolio-list-item-invite-to-job') || el.parentElement"
                )
            except Exception:
                container = None
            if container:
                try:
                    existing = await container.query_selector("button.request_a_quote_btn.menuitem")
                    if not existing:
                        existing = await container.query_selector(
                            ":is(button,a):has-text('Invite to Existing Job'), :is(button,a):has-text('Invite to Existing Jobs')"
                        )
                    if existing and await existing.is_visible():
                        clicked = False
                        try:
                            await existing.click()
                            clicked = True
                        except asyncio.CancelledError:
                            clicked = True
                        except Exception:
                            clicked = False
                        if not clicked:
                            try:
                                bb = await existing.bounding_box()
                                if bb:
                                    cx = bb["x"] + bb["width"]/2
                                    cy = bb["y"] + bb["height"]/2
                                    await page.mouse.move(cx, cy, steps=1)
                                    await page.mouse.click(cx, cy, delay=30)
                                    clicked = True
                            except Exception:
                                clicked = False
                        if not clicked:
                            try:
                                await existing.evaluate("el => el.click()")
                                clicked = True
                            except Exception:
                                clicked = False
                        if clicked:
                            try:
                                await page.wait_for_selector(FINAL_INVITE_BTN_ANY, timeout=2000)
                                if DEBUG:
                                    try:
                                        print("[debug] Container-scoped click on 'Invite to Existing Job'.")
                                    except Exception:
                                        pass
                                return True
                            except Exception:
                                pass
                except Exception:
                    pass

            # Keyboard fallback: navigate dropdown with ArrowDown + Enter
            try:
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.05)
                await page.keyboard.press("Enter")
                try:
                    await page.wait_for_selector(FINAL_INVITE_BTN_ANY, timeout=1200)
                    if DEBUG:
                        try:
                            print("[debug] Keyboard fallback selected 'Invite to Existing Job'.")
                        except Exception:
                            pass
                    return True
                except Exception:
                    pass
            except Exception:
                pass

            # Wait a bit for the menu item to render
            try:
                await page.wait_for_selector(EXISTING_MENU_ITEM, state="visible", timeout=2000)
            except Exception:
                continue

            try:
                # Use proximity to pick the right menu item
                hb = await head_btn.bounding_box()
                if not hb:
                    # Fallback: click the first visible item
                    mi = page.locator(EXISTING_MENU_ITEM).first
                    if await mi.is_visible():
                        try:
                            await mi.click(force=True)
                        except Exception:
                            # Final fallback: JS click
                            try:
                                sel = EXISTING_MENU_ITEM
                                await page.eval_on_selector(sel, "el => el.click()")
                            except Exception:
                                pass
                        if DEBUG:
                            try:
                                print("[debug] Clicked first visible 'Invite to Existing Job' item (no bbox).")
                            except Exception:
                                pass
                        return True

                candidates = await page.query_selector_all(EXISTING_MENU_ITEM)
                if DEBUG:
                    try:
                        vis = 0
                        for el in candidates:
                            try:
                                if await el.is_visible():
                                    vis += 1
                            except Exception:
                                pass
                        print(f"[debug] Attempt {attempt+1}: found {len(candidates)} candidates, {vis} visible")
                    except Exception:
                        pass
                best = None
                best_d = 1e9
                for el in candidates:
                    try:
                        if not await el.is_visible():
                            continue
                        bb = await el.bounding_box()
                        if not bb:
                            continue
                        # Distance from head button center to menu item center
                        dx = (bb["x"] + bb["width"]/2) - (hb["x"] + hb["width"]/2)
                        dy = (bb["y"] + bb["height"]/2) - (hb["y"] + hb["height"]/2)
                        d2 = dx*dx + dy*dy
                        if d2 < best_d:
                            best_d = d2
                            best = el
                    except Exception:
                        continue
                if best:
                    try:
                        await best.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    clicked = False
                    try:
                        await best.click(force=True)
                        clicked = True
                    except Exception:
                        clicked = False
                    if not clicked:
                        try:
                            bb = await best.bounding_box()
                            if bb:
                                cx = bb["x"] + bb["width"]/2
                                cy = bb["y"] + bb["height"]/2
                                await page.mouse.move(cx, cy, steps=1)
                                await page.mouse.click(cx, cy, delay=30)
                                clicked = True
                        except Exception:
                            clicked = False
                    if not clicked:
                        try:
                            sel = EXISTING_MENU_ITEM
                            await page.eval_on_selector(sel, "el => el.click()")
                            clicked = True
                        except Exception:
                            clicked = False
                    if clicked:
                        try:
                            await page.wait_for_selector(FINAL_INVITE_BTN_ANY, timeout=2000)
                            if DEBUG:
                                try:
                                    print("[debug] Clicked nearest 'Invite to Existing Job' item.")
                                except Exception:
                                    pass
                            return True
                        except Exception:
                            # fall through to coordinate fallback below
                            pass
            except Exception:
                continue

            # Coordinate-based fallback: click slightly below the head button in case selectors failed
            try:
                hb = await head_btn.bounding_box()
            except Exception:
                hb = None
            if hb:
                cx = hb["x"] + hb["width"]/2
                base_y = hb["y"] + hb["height"]
                for dy in (36, 44, 56, 68, 80):
                    try:
                        await page.mouse.move(cx, base_y + dy, steps=1)
                        await page.mouse.click(cx, base_y + dy, delay=30)
                        # Did the modal appear?
                        try:
                            await page.wait_for_selector(FINAL_INVITE_BTN_ANY, timeout=1200)
                            if DEBUG:
                                try:
                                    print(f"[debug] Coordinate fallback clicked at dy={dy}.")
                                except Exception:
                                    pass
                            return True
                        except Exception:
                            pass
                    except Exception:
                        continue
    except Exception:
        pass

    # Container-scoped fallback: find the ResultCard action area for this head button and click
    # the 'Invite to Existing Job' inside it.
    try:
        container = await head_btn.evaluate_handle(
            "el => el.closest('.ResultCard-action') || el.closest('.portfolio-list-item-invite-to-job') || el.parentElement"
        )
    except Exception:
        container = None
    if container:
        try:
            # Try a few short polls for the menu item to render inside the container
            for _ in range(8):
                try:
                    existing = await container.query_selector("button.request_a_quote_btn.menuitem")
                    if not existing:
                        existing = await container.query_selector(
                            ":is(button,a):has-text('Invite to Existing Job'), :is(button,a):has-text('Invite to Existing Jobs')"
                        )
                    if existing:
                        clicked = False
                        try:
                            await existing.click()
                            clicked = True
                        except asyncio.CancelledError:
                            # Treat as likely click and continue to verify modal
                            clicked = True
                        except Exception:
                            clicked = False
                        if not clicked:
                            try:
                                bb = await existing.bounding_box()
                                if bb:
                                    cx = bb["x"] + bb["width"]/2
                                    cy = bb["y"] + bb["height"]/2
                                    await page.mouse.move(cx, cy, steps=1)
                                    await page.mouse.click(cx, cy, delay=30)
                                    clicked = True
                            except Exception:
                                clicked = False
                        if not clicked:
                            try:
                                # JS click on the element handle
                                await existing.evaluate("el => el.click()")
                                clicked = True
                            except Exception:
                                clicked = False
                        try:
                            await page.wait_for_selector(FINAL_INVITE_BTN_ANY, timeout=1500)
                            if DEBUG:
                                try:
                                    print("[debug] Container-scoped click on 'Invite to Existing Job'.")
                                except Exception:
                                    pass
                            return True
                        except Exception:
                            pass
                except Exception:
                    pass
                await asyncio.sleep(0.2)
        except Exception:
            pass

    return False

async def _extract_talent_id_from_root(root) -> Optional[str]:
    """Attempt to extract a stable talent ID/slug from a talent card root element.
    Tries data-* attributes first, then common profile links.
    """
    try:
        # Try common data attributes
        for attr in ("data-talent-id", "data-profile-id", "data-id", "data-user-id"):
            try:
                v = await root.get_attribute(attr)
                if v and str(v).strip():
                    return str(v).strip()
            except Exception:
                pass
        # Try profile link anchors
        link = await root.query_selector("a[href*='/talents/'], a[href*='/talent/'], a[href*='/profile/'], a[href*='/users/']")
        if link:
            try:
                href = await link.get_attribute("href")
            except Exception:
                href = None
            if href:
                m = (
                    re.search(r"/talents/([A-Za-z0-9_-]+)", href)
                    or re.search(r"/talent/([A-Za-z0-9_-]+)", href)
                    or re.search(r"/profile/([A-Za-z0-9_-]+)", href)
                    or re.search(r"/users/([A-Za-z0-9_-]+)", href)
                )
                if m:
                    return m.group(1)
    except Exception:
        pass
    return None

async def _extract_talent_id_from_button(page, btn) -> Optional[str]:
    """Walk up from a button to the nearest talent card container and extract an ID."""
    try:
        container = None
        try:
            container = await btn.evaluate_handle(
                "el => el.closest('[data-testid=\\'talent-card\\']') || el.closest('[data-qa=\\'talent-card\\']') || el.closest('article')"
            )
        except Exception:
            container = None
        if container:
            try:
                return await _extract_talent_id_from_root(container)
            except Exception:
                pass
    except Exception:
        pass
    return None

async def _select_job_via_choices(page, modal, job_id: str, job_pref: str) -> bool:
    """Handle job selection when the modal uses a Choices.js dropdown.
    Returns True if it appears we selected a job in the dropdown.
    """
    try:
        scope = modal if modal else page
        # Prefer the Choices wrapper that owns the hidden select
        wrapper = scope.locator(".choices", has=scope.locator("#request-quote-open-jobs-list")).first
        dropdown = wrapper
        # Fallbacks if wrapper not found
        if await _is_locator_empty(wrapper):
            dropdown = scope.locator(":is(.choices, [role='combobox'], .choices__inner)").first
        try:
            await dropdown.wait_for(state="visible", timeout=2000)
        except Exception:
            return False

        # Log current chip and underlying select value
        try:
            chip = wrapper.locator('.choices__list--single .choices__item').first
            chip_text = await chip.inner_text() if await chip.is_visible() else ""
        except Exception:
            chip_text = ""
        try:
            sel_val = await scope.eval_on_selector("#request-quote-open-jobs-list", "el => el && el.value")
        except Exception:
            sel_val = None
        log_event({"type": "choices_state_before", "chip": chip_text, "select_val": sel_val, "target_job_id": job_id or None, "target_pref": job_pref or None})

        # Open by clicking the visible chip inside choices__inner
        opener = dropdown.locator(".choices__inner .choices__item").first
        try:
            if await opener.is_visible():
                await opener.click()
            else:
                await dropdown.click()
        except Exception:
            try:
                await dropdown.evaluate("el => el.click()")
            except Exception:
                pass
        await asyncio.sleep(0.2)

        # Wait until the list is open (aria-expanded=true) and scope to this wrapper
        try:
            expanded = await wrapper.get_attribute('aria-expanded')
        except Exception:
            expanded = None
        if expanded != 'true':
            # Try to detect the open list explicitly
            try:
                await wrapper.locator('.choices__list--dropdown[aria-expanded="true"]').wait_for(state='visible', timeout=2000)
            except Exception:
                pass

        # Collect visible options under this wrapper
        listbox = wrapper.locator('.choices__list--dropdown[aria-expanded="true"] .choices__item[role="option"]').or_(
            wrapper.locator('.choices__list--dropdown .choices__item[role="option"]')
        )
        try:
            await listbox.first.wait_for(state="visible", timeout=2000)
        except Exception:
            # Fallback: search globally but this is less reliable
            listbox = scope.locator('.choices__list--dropdown[aria-expanded="true"] .choices__item[role="option"]').or_(
                scope.locator('.choices__item[role="option"]')
            )

        # Snapshot options for debugging
        try:
            count = await listbox.count()
            snapshot = []
            for i in range(min(count, 20)):
                n = listbox.nth(i)
                try:
                    snapshot.append({
                        "id": await n.get_attribute('id'),
                        "value": await n.get_attribute('data-value'),
                        "aria": await n.get_attribute('aria-selected'),
                        "text": (await n.inner_text()).strip()[:140],
                    })
                except Exception:
                    continue
            log_event({"type": "choices_visible_options", "options": snapshot})
        except Exception:
            pass

        # Try keyboard-based navigation first: focus input, ArrowDown in batches until highlighted equals job_id
        if job_id:
            try:
                # Focus the search/input inside this Choices wrapper
                kb_input = wrapper.locator("input[type='search'], .choices__input--cloned, input[role='searchbox']").first
                if await kb_input.count():
                    try:
                        await kb_input.focus()
                    except Exception:
                        try:
                            await kb_input.click()
                        except Exception:
                            pass
                else:
                    # Fallback: focus the wrapper so key events go to Choices
                    try:
                        await wrapper.focus()
                    except Exception:
                        try:
                            await wrapper.click()
                        except Exception:
                            pass

                await asyncio.sleep(0.1)

                # Ensure dropdown is open (click the chip once)
                try:
                    chip_once = dropdown.locator(".choices__inner .choices__item").first
                    if await chip_once.is_visible():
                        await chip_once.click()
                    else:
                        await dropdown.click()
                except Exception:
                    try:
                        await dropdown.evaluate("el => el.click()")
                    except Exception:
                        pass

                await asyncio.sleep(0.15)

                # Walk with ArrowDown in small batches, logging the highlighted option as we go
                target_found = False
                max_steps = 800
                batch = 5
                steps = 0
                while steps < max_steps:
                    try:
                        for _ in range(batch):
                            await page.keyboard.press('ArrowDown')
                            await asyncio.sleep(0.04)
                    except Exception:
                        # If keyboard events fail, exit keyboard path
                        break

                    steps += batch
                    try:
                        hi = wrapper.locator('.choices__list--dropdown .choices__item.is-highlighted, .choices__item[aria-selected="true"].is-highlighted').first
                        hv = ht = None
                        if await hi.count():
                            try:
                                hv = await hi.get_attribute('data-value')
                            except Exception:
                                hv = None
                            try:
                                ht = (await hi.inner_text()).strip()
                            except Exception:
                                ht = None
                        log_event({"type": "choices_keyboard_step", "highlight_value": hv, "highlight_text": ht, "steps": steps})
                        if hv is not None and str(hv) == str(job_id):
                            target_found = True
                            # Commit selection
                            try:
                                await page.keyboard.press('Enter')
                            except Exception:
                                pass
                            await asyncio.sleep(0.2)
                            # Verify hidden select and chip
                            try:
                                chip_el = wrapper.locator('.choices__list--single .choices__item').first
                                chip_val = None
                                try:
                                    chip_val = await chip_el.get_attribute('data-value')
                                except Exception:
                                    chip_val = None
                                if chip_val is None:
                                    try:
                                        chip_val = await chip_el.get_attribute('value')
                                    except Exception:
                                        chip_val = None
                                if chip_val is None:
                                    try:
                                        chip_val = await chip_el.evaluate("el => (el && el.dataset && (el.dataset.value || el.getAttribute('data-value') || el.getAttribute('value'))) || null")
                                    except Exception:
                                        chip_val = None
                            except Exception:
                                chip_val = None
                            try:
                                new_val = await scope.eval_on_selector("#request-quote-open-jobs-list", "el => el && el.value")
                            except Exception:
                                new_val = None
                            log_event({"type": "job_choice_selected", "job_id": job_id or None, "pref": job_pref or None, "select_val": new_val})
                            # Only succeed if both chip and select reflect the target job id
                            if str(new_val) == str(job_id) and str(chip_val) == str(job_id):
                                return True
                            # If mismatch, break to fallbacks
                            break
                    except Exception:
                        # Continue trying until max_steps
                        pass
                # If keyboard path didn't confirm selection, continue to non-keyboard fallbacks below
            except Exception:
                # Ignore and fall back to click-based targeting
                pass

        # Find target by value first, then by text containing #ID or job title
        target = None
        by_value = None
        by_text_id = None
        by_text_title = None
        if job_id:
            by_value = wrapper.locator(f".choices__list--dropdown .choices__item[role='option'][data-value='{job_id}']").first
            target = by_value
            if await _is_locator_empty(target):
                by_text_id = wrapper.locator(".choices__list--dropdown .choices__item[role='option']", has_text=f"#{job_id}").first
                target = by_text_id
        if (not target) or (await _is_locator_empty(target)):
            if job_pref:
                by_text_title = wrapper.locator(".choices__list--dropdown .choices__item[role='option']", has_text=job_pref).first
                target = by_text_title

        # Log target resolution
        try:
            info = {"by_value_count": None, "by_text_id_count": None, "by_text_title_count": None, "final_count": None, "final_visible": None}
            if by_value is not None:
                info["by_value_count"] = await by_value.count()
            if by_text_id is not None:
                info["by_text_id_count"] = await by_text_id.count()
            if by_text_title is not None:
                info["by_text_title_count"] = await by_text_title.count()
            if target is not None:
                info["final_count"] = await target.count()
                try:
                    info["final_visible"] = await target.is_visible()
                except Exception:
                    info["final_visible"] = None
            log_event({"type": "choices_target_lookup", "job_id": job_id or None, "pref": job_pref or None, **info})
        except Exception:
            pass

        # Filter by typing if not found
        if (not target) or (await _is_locator_empty(target)):
            try:
                search = wrapper.locator("input[type='search'], .choices__input--cloned, input[role='searchbox']").first
                if not await _is_locator_empty(search):
                    await search.fill(job_id or job_pref)
                    await asyncio.sleep(0.3)
                    target = wrapper.locator(".choices__list--dropdown .choices__item[role='option']", has_text=(job_id or job_pref)).first
            except Exception:
                pass

        if target and not await _is_locator_empty(target):
            try:
                await target.scroll_into_view_if_needed()
            except Exception:
                pass
            try:
                await target.click()
            except Exception:
                try:
                    await target.evaluate("el => (el.closest('button, [role=option], [role=menuitem], li, a, div') || el).click()")
                except Exception:
                    return False
            # Verify the hidden select updated
            try:
                new_val = await scope.eval_on_selector("#request-quote-open-jobs-list", "el => el && el.value")
            except Exception:
                new_val = None
            log_event({"type": "job_choice_selected", "job_id": job_id or None, "pref": job_pref or None, "select_val": new_val})
            await asyncio.sleep(0.2)
            return True

        # Fallback: set the hidden <select> value directly and dispatch events
        if job_id:
            try:
                sel = scope.locator('#request-quote-open-jobs-list')
                if await sel.count():
                    try:
                        await sel.select_option(job_id)
                    except Exception:
                        # Force via JS if select_option fails due to hidden state
                        await scope.evaluate("(id, val) => { const s=document.getElementById(id); if (s) { s.value = val; s.dispatchEvent(new Event('input', {bubbles:true})); s.dispatchEvent(new Event('change', {bubbles:true})); } }", "request-quote-open-jobs-list", job_id)
                    try:
                        final_val = await scope.eval_on_selector('#request-quote-open-jobs-list', "el => el && el.value")
                    except Exception:
                        final_val = None
                    log_event({"type": "job_choice_selected_via_select", "job_id": job_id, "select_val": final_val})
                    return str(final_val) == str(job_id)
            except Exception:
                pass
    except Exception:
        pass
    return False

async def _is_locator_empty(loc) -> bool:
    try:
        # Only treat as empty when there are zero matches; some Choices items
        # may report not visible briefly while animating but are still clickable.
        return (await loc.count()) == 0
    except Exception:
        return True

async def pick_job_in_modal(page) -> bool:
    await pause_if_requested()
    """Return True if we clicked an Invite button for some job."""
    job_pref = os.environ.get("VOICES_JOB_TITLE", "").strip().lower()
    # Log the selection plan up front
    try:
        sel_val0 = await page.eval_on_selector("#request-quote-open-jobs-list", "el => el && el.value")
    except Exception:
        sel_val0 = None
    try:
        log_event({
            "type": "job_selection_plan",
            "required_job_id": REQUIRED_JOB_ID or None,
            "job_pref": job_pref or None,
            "select_val_before": sel_val0,
        })
    except Exception:
        pass

    # If a dropdown is present to open the modal, click it first
    try:
        dd = await page.query_selector(EXISTING_MENU_ITEM)
        if dd and await dd.is_visible():
            await dd.click()
            await asyncio.sleep(0.2)
    except Exception:
        pass

    # Ensure modal present or at least the final invite button is visible
    have_modal = False
    modal = page.locator(INVITE_MODAL).first
    try:
        await modal.wait_for(state="visible", timeout=4000)
        have_modal = True
    except Exception:
        have_modal = False

    # Log modal presence
    try:
        log_event({"type": "modal_detected", "have_modal": have_modal, "url": page.url})
    except Exception:
        pass

    if not have_modal:
        try:
            await page.wait_for_selector(FINAL_INVITE_BTN_ANY, timeout=6000)
        except PWTimeout:
            extra = {}
            if DEBUG:
                try:
                    locs = page.locator(FINAL_INVITE_BTN_ANY)
                    count = await locs.count()
                    matches = []
                    for i in range(count):
                        btn = locs.nth(i)
                        try:
                            visible = await btn.is_visible()
                        except Exception:
                            visible = None
                        try:
                            enabled = await btn.is_enabled()
                        except Exception:
                            enabled = None
                        matches.append({"visible": visible, "enabled": enabled})
                    extra["matches"] = matches
                except Exception:
                    pass
                ts = int(time.time() * 1000)
                try:
                    html_path = f"debug_modal_missing_{ts}.html"
                    with open(html_path, "w", encoding="utf-8") as fh:
                        fh.write(await page.content())
                    extra["html_path"] = html_path
                except Exception:
                    pass
                try:
                    png_path = f"debug_modal_missing_{ts}.png"
                    await page.screenshot(path=png_path)
                    extra["screenshot"] = png_path
                except Exception:
                    pass
            log_event({"type": "modal_missing", "reason": "no_confirm_button", "url": page.url, **extra})
            return False

    # Ensure focus stays inside the modal so scrolling doesn't move the background
    try:
        if have_modal:
            await modal.hover()
            try:
                await page.eval_on_selector(INVITE_MODAL, "(el) => { el.setAttribute('tabindex','-1'); el.focus(); }")
            except Exception:
                pass
        else:
            # Hover the confirm button directly
            btn0 = page.locator(FINAL_INVITE_BTN_ANY).first
            await btn0.hover()
    except Exception:
        pass

    # If no specific job is required, we can try confirming immediately
    if not (REQUIRED_JOB_ID or job_pref):
        try:
            confirm0 = page.locator("#submit-request-quote").first
            try:
                await confirm0.wait_for(state="visible", timeout=5000)
            except asyncio.CancelledError:
                return False
            await confirm0.scroll_into_view_if_needed()
            await pause_if_requested()
            if DRY_RUN:
                log_event({"type": "would_click", "target": "confirm_primary", "selector": "#submit-request-quote"})
                return True
            try:
                await confirm0.click()
            except asyncio.CancelledError:
                return False
            try:
                await page.wait_for_selector(SUCCESS_TOAST, timeout=6000)
            except PWTimeout:
                try:
                    if have_modal:
                        await page.wait_for_selector(INVITE_MODAL, state="hidden", timeout=3000)
                except Exception:
                    pass
            return True
        except Exception:
            pass

    # Always switch to "Invite to Existing Jobs" (never create new job)
    try:
        tab = await page.query_selector(EXISTING_TAB)
        if tab:
            await tab.click()
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(0.5)
    except Exception:
        pass  # sometimes the list is already on existing jobs

    # Attempt to select the job via Choices dropdown (new UI) before falling back to rows
    selected_via_choices = False
    try:
        if REQUIRED_JOB_ID or job_pref:
            # Prefer the simpler, stricter selector that scopes to the dropdown
            selected_via_choices = await _select_job_via_choices_simple(page, modal if have_modal else None, REQUIRED_JOB_ID, job_pref)
            if selected_via_choices:
                log_event({"type": "job_selected_via_choices", "job_id": REQUIRED_JOB_ID or None, "pref": job_pref or None})
    except Exception:
        selected_via_choices = False

    rows = await page.query_selector_all(JOB_ROW) if (have_modal and not selected_via_choices) else []
    if DEBUG:
        try:
            print(f"[debug] Found {len(rows)} job rows in modal.")
        except Exception:
            pass
    if have_modal and not rows:
        # Sometimes jobs list is virtualized—scroll inside the modal instead of the page
        try:
            for _ in range(4):
                try:
                    await modal.hover()
                except Exception:
                    pass
                # Scroll only the modal element; avoid background scrolling
                try:
                    await page.eval_on_selector(INVITE_MODAL, "(el) => el.scrollBy(0, 1200)")
                except Exception:
                    pass
                await asyncio.sleep(0.3)
            rows = await page.query_selector_all(JOB_ROW)
        except Exception:
            pass

    # Try to extract job IDs (if present) to support targeted selection
    async def _extract_job_id(row) -> Optional[str]:
        try:
            link = await row.query_selector("a[href*='/jobs/']")
            if link:
                href = await link.get_attribute("href")
                if href:
                    m = re.search(r"/jobs/(\d+)", href)
                    if m:
                        return m.group(1)
                    m = re.search(r"(\d{5,})", href)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        for attr in ("data-job-id", "data-id", "data-jobid", "data-job"):
            try:
                v = await row.get_attribute(attr)
                if v and re.fullmatch(r"\d{5,}", v.strip()):
                    return v.strip()
            except Exception:
                continue
        try:
            txt = await row.inner_text()
            m = re.search(r"\b(\d{5,})\b", txt)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    # If a specific job ID or title is required, try to target it; otherwise fall back to confirming
    target_btn = None
    if REQUIRED_JOB_ID:
        for r in rows:
            try:
                jid = await _extract_job_id(r)
                if jid and jid == REQUIRED_JOB_ID:
                    btn = await r.query_selector(JOB_INVITE_BTN)
                    if btn:
                        target_btn = btn
                        break
            except Exception:
                continue

        # try exact/contains match if title provided (only if not already matched by ID)
        if (not target_btn) and job_pref:
            for r in rows:
                try:
                    title_el = await r.query_selector(JOB_TITLE_EL)
                    title = (await title_el.inner_text()) if title_el else ""
                    if job_pref in title.lower():
                        btn = await r.query_selector(JOB_INVITE_BTN)
                        if btn:
                            target_btn = btn
                            break
                except Exception:
                    continue

    # If no required job filtering, or if we didn't find a specific row button, try the confirm path
    if not target_btn:
        # Fallback: click a row that contains the job id text, then confirm
        if have_modal and REQUIRED_JOB_ID:
            try:
                row_text = modal.locator(":is([data-testid='job-row'], .job-item, li, tr)", has_text=f"#{REQUIRED_JOB_ID}").first
                if await row_text.count():
                    try:
                        await row_text.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    try:
                        await row_text.click()
                    except Exception:
                        try:
                            await row_text.click(force=True)
                        except Exception:
                            try:
                                await row_text.evaluate("el => el.click()")
                            except Exception:
                                pass
                    await asyncio.sleep(0.2)
                    # After selecting a row, confirm
                    try:
                        confirm = await page.query_selector(FINAL_INVITE_BTN)
                        if confirm and (await confirm.is_enabled()):
                            if DRY_RUN:
                                log_event({"type": "would_click", "target": "confirm_after_row_click"})
                                return True
                            await confirm.click()
                            try:
                                await page.wait_for_selector(SUCCESS_TOAST, timeout=6000)
                            except PWTimeout:
                                try:
                                    await page.wait_for_selector(INVITE_MODAL, state="hidden", timeout=3000)
                                except Exception:
                                    pass
                            return True
                    except Exception:
                        pass
            except Exception:
                pass

    if not target_btn:
        # If we already selected a job via choices, proceed to confirm
        if selected_via_choices:
            try:
                # Nudge UI: ensure dropdown is closed and modal focused
                try:
                    if have_modal:
                        await modal.press("Escape")
                        await modal.hover()
                except Exception:
                    pass

                # Prefer a confirm button scoped to the modal
                if have_modal:
                    confirm_loc = modal.locator(
                        ":is(button,[role='button'],a):has-text('Invite to Job'), "
                        ":is(button,[role='button'],a):has-text('Send Invite'), "
                        ":is(button,[role='button'],a):has-text('Invite'), "
                        ":is(button,[role='button'],a):has-text('Request a Quote'), "
                        ":is(button,[role='button'],a):has-text('Submit Request'), "
                        ":is(button,[role='button'],a):has-text('Send Request'), "
                        "button#submit-request-quote, button[type='submit']"
                    )
                    confirm = confirm_loc.first
                else:
                    confirm = page.locator(FINAL_INVITE_BTN_ANY).first

                # Proceed to confirm; selection step already set the desired job
                
                await confirm.wait_for(state="attached", timeout=3000)
                # Log current hidden select value before confirming
                try:
                    sel_val1 = await page.eval_on_selector("#request-quote-open-jobs-list", "el => el && el.value")
                except Exception:
                    sel_val1 = None
                log_event({"type": "about_to_confirm", "path": "after_choices", "select_val": sel_val1})

                if DRY_RUN:
                    log_event({"type": "would_click", "target": "confirm_after_choices"})
                    return True

                # Try normal click, then force, then JS
                clicked = False
                try:
                    await confirm.click()
                    clicked = True
                except Exception:
                    try:
                        await confirm.click(force=True)
                        clicked = True
                    except Exception:
                        try:
                            await confirm.evaluate("el => el.click()")
                            clicked = True
                        except Exception:
                            clicked = False

                if not clicked:
                    # Last resort: press Enter to submit
                    try:
                        await modal.press("Enter")
                        clicked = True
                    except Exception:
                        pass

                if not clicked:
                    return False

                # Wait for success toast or modal to close
                try:
                    log_event({"type": "confirm_clicked", "path": "after_choices"})
                except Exception:
                    pass
                try:
                    await page.wait_for_selector(SUCCESS_TOAST, timeout=6000)
                    try:
                        log_event({"type": "confirm_result", "status": "toast_seen"})
                    except Exception:
                        pass
                except PWTimeout:
                    try:
                        if have_modal:
                            await page.wait_for_selector(INVITE_MODAL, state="hidden", timeout=3000)
                            try:
                                log_event({"type": "confirm_result", "status": "modal_hidden"})
                            except Exception:
                                pass
                    except Exception:
                        pass
                return True
            except Exception:
                pass

        # Otherwise, try the legacy confirm/row paths
        # 1) If a confirm button exists and is enabled, click it
        try:
            # Prefer modal-scoped confirm
            confirm = (modal.locator(
                ":is(button,[role='button'],a):has-text('Invite to Job'), "
                ":is(button,[role='button'],a):has-text('Send Invite'), "
                ":is(button,[role='button'],a):has-text('Invite'), "
                ":is(button,[role='button'],a):has-text('Request a Quote'), "
                ":is(button,[role='button'],a):has-text('Submit Request'), "
                ":is(button,[role='button'],a):has-text('Send Request'), "
                "button#submit-request-quote, button[type='submit']"
            ).first if have_modal else page.locator(FINAL_INVITE_BTN_ANY).first)

            await confirm.wait_for(state="attached", timeout=3000)
            try:
                if have_modal:
                    await modal.hover()
            except Exception:
                pass
            await confirm.scroll_into_view_if_needed()

            
            # Log current hidden select value before confirming
            try:
                sel_val2 = await page.eval_on_selector("#request-quote-open-jobs-list", "el => el && el.value")
            except Exception:
                sel_val2 = None
            log_event({"type": "about_to_confirm", "path": "fallback_confirm", "select_val": sel_val2})
            if DRY_RUN:
                log_event({"type": "would_click", "target": "confirm_fallback", "selector": "modal-scoped"})
                return True
            # Try click with fallbacks
            try:
                await confirm.click()
            except Exception:
                try:
                    await confirm.click(force=True)
                except Exception:
                    try:
                        await confirm.evaluate("el => el.click()")
                    except Exception:
                        return False
            try:
                log_event({"type": "confirm_clicked", "path": "fallback_confirm"})
            except Exception:
                pass
            try:
                await page.wait_for_selector(SUCCESS_TOAST, timeout=6000)
                try:
                    log_event({"type": "confirm_result", "status": "toast_seen"})
                except Exception:
                    pass
            except PWTimeout:
                try:
                    if have_modal:
                        await page.wait_for_selector(INVITE_MODAL, state="hidden", timeout=3000)
                        try:
                            log_event({"type": "confirm_result", "status": "modal_hidden"})
                        except Exception:
                            pass
                except Exception:
                    pass
            return True
        except Exception:
            pass

        # 2) Try clicking the first row-level Invite button
        try:
            first_row_btn = None
            for r in rows:
                btn = await r.query_selector(JOB_INVITE_BTN)
                if btn:
                    first_row_btn = btn
                    break
            if first_row_btn:
                await first_row_btn.scroll_into_view_if_needed()
                if DRY_RUN:
                    log_event({"type": "would_click", "target": "row_invite_button"})
                    return True
                try:
                    await first_row_btn.click()
                except asyncio.CancelledError:
                    return False
                try:
                    await page.wait_for_selector(SUCCESS_TOAST, timeout=6000)
                except PWTimeout:
                    try:
                        await page.wait_for_selector(INVITE_MODAL, state="hidden", timeout=3000)
                    except Exception:
                        pass
                return True
        except Exception:
            pass

        # 3) Select the first row (if any), then try confirm again
        try:
            if rows:
                await rows[0].click()
                await asyncio.sleep(0.2)
                confirm = await page.query_selector(FINAL_INVITE_BTN if have_modal else FINAL_INVITE_BTN_ANY)
                if confirm and (await confirm.is_enabled()):
                    if DRY_RUN:
                        log_event({"type": "would_click", "target": "confirm_after_row_select"})
                        return True
                    try:
                        await confirm.click()
                    except asyncio.CancelledError:
                        return False
                    try:
                        await page.wait_for_selector(SUCCESS_TOAST, timeout=6000)
                    except PWTimeout:
                        try:
                            if have_modal:
                                await page.wait_for_selector(INVITE_MODAL, state="hidden", timeout=3000)
                        except Exception:
                            pass
                    return True
        except Exception:
            pass

        if DEBUG and REQUIRED_JOB_ID:
            try:
                found_ids = []
                for r in rows:
                    try:
                        jid = await _extract_job_id(r)
                        if jid:
                            found_ids.append(jid)
                    except Exception:
                        pass
                print(f"[debug] No matching job. Found IDs: {', '.join(found_ids) if found_ids else 'none'}; required {REQUIRED_JOB_ID}.")
            except Exception:
                pass

        # nothing worked
        # Don't force-close modal; leave it as-is to avoid losing state
        log_event({"type": "modal_no_action", "rows": len(rows) if have_modal else 0, "url": page.url})
        return False

    await target_btn.scroll_into_view_if_needed()
    if DRY_RUN:
        log_event({"type": "would_click", "target": "target_row_button"})
        return True
    await target_btn.click()
    # wait for a success toast or the modal to close/disable
    try:
        await page.wait_for_selector(SUCCESS_TOAST, timeout=6000)
    except PWTimeout:
        # Try a final confirmation click if required
        try:
            confirm = await page.query_selector(FINAL_INVITE_BTN)
            if confirm and await confirm.is_enabled():
                await confirm.click()
                try:
                    await page.wait_for_selector(SUCCESS_TOAST, timeout=6000)
                except PWTimeout:
                    try:
                        await page.wait_for_selector(INVITE_MODAL, state="hidden", timeout=3000)
                    except Exception:
                        pass
        except Exception:
            pass
    # close modal (some UIs auto-close)
    try:
        close = await page.query_selector(f"{INVITE_MODAL} >> :is(button, [role='button']):has-text('Close')")
        if close:
            await close.click()
    except Exception:
        pass

    return True

async def _select_job_via_choices_simple(page, modal, job_id: str, job_pref: str) -> bool:
    """Simplified, robust Choices.js selection by job ID or title.
    1) Try setting the hidden <select> value and fire events (fast path).
    2) Open the dropdown and click the option inside the dropdown by data-value.
    3) Fallback to filtering by typing, then click.
    Returns True when the hidden select (and visible chip) reflect the choice.
    """
    try:
        scope = modal if modal else page
        wrapper = scope.locator("div.choices[data-type='select-one']", has=scope.locator("#request-quote-open-jobs-list")).first
        if await _is_locator_empty(wrapper):
            wrapper = scope.locator(".choices:has(#request-quote-open-jobs-list)").first
        if await _is_locator_empty(wrapper):
            return False

        async def _read_state():
            try:
                chip_val = await wrapper.locator(".choices__list--single .choices__item").first.get_attribute("data-value")
            except Exception:
                chip_val = None
            try:
                sel_el = wrapper.locator('#request-quote-open-jobs-list').first
                if await sel_el.count():
                    sel_val = await sel_el.evaluate("el => el && el.value")
                else:
                    sel_val = None
            except Exception:
                sel_val = None
            return chip_val, sel_val

        chip0, sel0 = await _read_state()
        # Derive effective job id from either job_id or digits in job_pref (e.g., "818318")
        eff_job_id = None
        try:
            if job_id and str(job_id).strip():
                eff_job_id = str(job_id).strip()
            elif job_pref:
                import re as _re
                m = _re.search(r"\b(\d{5,})\b", str(job_pref))
                if m:
                    eff_job_id = m.group(1)
        except Exception:
            eff_job_id = job_id
        log_event({"type": "choices_state_before", "chip": chip0, "select_val": sel0, "target_job_id": eff_job_id or job_id or None, "target_pref": job_pref or None})

        # Fast path: set hidden select directly
        if eff_job_id:
            try:
                sel = wrapper.locator('#request-quote-open-jobs-list').first
                if await sel.count():
                    ok = False
                    try:
                        await sel.select_option(eff_job_id)
                        ok = True
                    except Exception:
                        await page.evaluate(
                            "(id, val) => { const s=document.getElementById(id); if (s) { s.value = val; s.dispatchEvent(new Event('input', {bubbles:true})); s.dispatchEvent(new Event('change', {bubbles:true})); } }",
                            "request-quote-open-jobs-list",
                            eff_job_id,
                        )
                        ok = True
                    if ok:
                        await asyncio.sleep(0.15)
                        chip1, sel1 = await _read_state()
                        log_event({"type": "job_choice_selected_via_select", "chip": chip1, "select_val": sel1})
                        if sel1 is not None and eff_job_id is not None and str(sel1) == str(eff_job_id) and str(chip1) == str(eff_job_id):
                            return True
            except Exception:
                pass

        # Open the dropdown reliably: click the wrapper and make sure aria-expanded becomes true
        try:
            opener = wrapper.locator(".choices__inner").first
            for _ in range(3):
                try:
                    if await opener.count():
                        await opener.click()
                    else:
                        await wrapper.click()
                except Exception:
                    try:
                        await wrapper.evaluate("el => el.click()")
                    except Exception:
                        pass
                await asyncio.sleep(0.12)
                try:
                    expanded = await wrapper.get_attribute("aria-expanded")
                except Exception:
                    expanded = None
                if expanded == "true":
                    break
                # Try keyboard open on the wrapper
                try:
                    await wrapper.press("Enter")
                except Exception:
                    try:
                        await wrapper.press("Space")
                    except Exception:
                        pass
                await asyncio.sleep(0.12)
        except Exception:
            pass

        # Do not rely solely on visible state; some themes animate/overlay the list.
        # Still try to wait briefly for the dropdown list to exist.
        try:
            await wrapper.locator(".choices__list--dropdown").first.wait_for(state="attached", timeout=2500)
        except Exception:
            pass
        # Log how many options are visible inside the dropdown for diagnostics
        try:
            opt_count = await wrapper.locator(".choices__list--dropdown .choices__item[role='option']").count()
            log_event({"type": "choices_dropdown_status", "options": int(opt_count)})
        except Exception:
            pass

        # Find target by value/text inside dropdown
        target = None
        if eff_job_id:
            t1 = wrapper.locator(f".choices__list--dropdown .choices__item[role='option'][data-value='{eff_job_id}']").first
            if await t1.count():
                target = t1
        if target is None or await _is_locator_empty(target):
            if eff_job_id:
                t2 = wrapper.locator(".choices__list--dropdown .choices__item[role='option']", has_text=f"#{eff_job_id}").first
                if await t2.count():
                    target = t2
        if (target is None or await _is_locator_empty(target)) and job_pref:
            t3 = wrapper.locator(".choices__list--dropdown .choices__item[role='option']", has_text=job_pref).first
            if await t3.count():
                target = t3

        # Filter by typing if still unresolved
        if target is None or await _is_locator_empty(target):
            try:
                search = wrapper.locator("input[type='search'], .choices__input--cloned, input[role='searchbox']").first
                if await search.count():
                    await search.fill(eff_job_id or job_pref)
                    await asyncio.sleep(0.25)
                    target = wrapper.locator(".choices__list--dropdown .choices__item[role='option']", has_text=(eff_job_id or job_pref)).first
            except Exception:
                pass

        if target is None or await _is_locator_empty(target):
            # Last resort: try hidden select again
            if eff_job_id:
                try:
                    await page.evaluate(
                        "(id, val) => { const s=document.getElementById(id); if (s) { s.value = val; s.dispatchEvent(new Event('input', {bubbles:true})); s.dispatchEvent(new Event('change', {bubbles:true})); } }",
                        "request-quote-open-jobs-list",
                        eff_job_id,
                    )
                    await asyncio.sleep(0.15)
                    chip3, sel3 = await _read_state()
                    log_event({"type": "job_choice_selected_via_select_fallback", "chip": chip3, "select_val": sel3})
                    return str(sel3) == str(eff_job_id)
                except Exception:
                    pass
            return False

        # Click target
        try:
            await target.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            await target.click()
        except Exception:
            try:
                await target.click(force=True)
            except Exception:
                try:
                    await target.evaluate("el => el.click()")
                except Exception:
                    return False

        await asyncio.sleep(0.15)
        chip2, sel2 = await _read_state()
        log_event({"type": "job_choice_selected", "chip": chip2, "select_val": sel2})
        return (str(sel2) == str(eff_job_id)) if eff_job_id else bool(chip2)
    except Exception:
        pass
    return False

async def invite_all_on_page(page) -> int:
    await pause_if_requested()
    await accept_cookies_if_present(page)
    # Ensure we're on a talents search page; if we were redirected (e.g., to jobs list), navigate back
    try:
        curr = (page.url or "").lower()
        if "/talents/search" not in curr:
            await page.goto(START_URL)
            try:
                await page.wait_for_load_state("networkidle")
            except PWTimeout:
                await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(0.5)
    except Exception:
        pass
    # For Favorites mode, ensure we treat this page as needing an initial list pick
    global _FAVORITES_LIST_SELECTED
    _FAVORITES_LIST_SELECTED = False
    favorites_selected_this_page = False
    # help trigger any lazy-loading
    for _ in range(SCROLL_PASSES):
        await page.mouse.wheel(0, 20000)
        await asyncio.sleep(0.6)

    # Pre-scan diagnostics: how many visible invite buttons exist now
    try:
        pre_invites = await page.locator(INVITE_MENU_BTN).count()
        if DEBUG:
            print(f"[debug] Visible invite buttons before scanning: {pre_invites}")
        log_event({"type": "page_scan_start", "url": page.url, "pre_invites": int(pre_invites)})
    except Exception:
        pre_invites = None

    # In favorites mode, also report heart count up-front
    if USE_FAVORITES:
        try:
            pre_hearts = await page.locator(FAVORITE_BTN).count()
            log_event({"type": "favorites_scan_start", "url": page.url, "pre_hearts": int(pre_hearts)})
        except Exception:
            pass

    cards = await page.query_selector_all(TALENT_CARD)
    if DEBUG:
        try:
            print(f"[debug] Found {len(cards)} talent cards on page.")
        except Exception:
            pass
    try:
        log_event({"type": "cards_detected", "url": page.url, "count": len(cards)})
    except Exception:
        pass
    invited = 0

    for c in cards:
        await pause_if_requested()
        try:
            # Check and skip previously invited IDs
            talent_id = None
            try:
                talent_id = await _extract_talent_id_from_root(c)
            except Exception:
                talent_id = None
            if talent_id and invited_db_has(talent_id):
                log_event({"type": "skip_already_invited", "talent_id": talent_id})
                continue
            # If card already shows invited state, skip (site-specific; update if needed)
            already = await c.query_selector(":is([aria-pressed='true'], .invited, :has-text('Invited'))")
            if already:
                continue

            # Favorites mode: per-page initial list selection, then simple heart clicks
            if USE_FAVORITES:
                try:
                    already_fav = await _card_is_favorited(c)
                    if not favorites_selected_this_page:
                        # Find the first non-favorited card on this page and use it to set (or confirm) the list
                        if already_fav:
                            # Skip; pick the next non-favorited as the initializer
                            continue
                        clicked = await _click_heart_on_card(page, c)
                        if clicked:
                            await _ensure_favorites_list_selected(page)
                            favorites_selected_this_page = True
                            if DRY_RUN:
                                log_event({"type": "favorite_planned", "url": page.url, "talent_id": talent_id, "phase": "initializer"})
                            else:
                                log_event({"type": "favorited", "url": page.url, "talent_id": talent_id, "phase": "initializer"})
                            invited += 1
                            await jitter(*CLICK_PAUSE)
                            continue
                    else:
                        # After initial selection on this page, just click hearts for non-favorited cards
                        if already_fav:
                            continue
                        clicked = await _click_heart_on_card(page, c)
                        if clicked:
                            if DRY_RUN:
                                log_event({"type": "favorite_planned", "url": page.url, "talent_id": talent_id})
                            else:
                                log_event({"type": "favorited", "url": page.url, "talent_id": talent_id})
                            invited += 1
                            await jitter(*CLICK_PAUSE)
                            continue
                except Exception:
                    pass

            btn = await c.query_selector(INVITE_MENU_BTN)
            if not btn:
                # Some cards hide the button until hover
                await c.hover()
                btn = await c.query_selector(INVITE_MENU_BTN)
            if not btn:
                if DEBUG:
                    try:
                        txt = await c.inner_text()
                        print(f"[debug] No Invite button on card snippet: {txt[:120].replace('\n',' ')}...")
                    except Exception:
                        pass
                continue

            await btn.scroll_into_view_if_needed()
            # Use robust dropdown click helper to open the 'Invite to Existing Job' flow
            opened = await _click_existing_job_dropdown(page, btn)
            if not opened:
                # Fallback: click head button once and try quick wait
                try:
                    await btn.click()
                    await asyncio.sleep(0.25)
                    mi = await page.wait_for_selector(EXISTING_MENU_ITEM, timeout=2000)
                    if mi:
                        try:
                            await mi.click(force=True)
                        except Exception:
                            try:
                                await page.eval_on_selector(EXISTING_MENU_ITEM, "el => el.click()")
                            except Exception:
                                pass
                        await asyncio.sleep(0.2)
                except Exception:
                    pass

            ok = await pick_job_in_modal(page)
            if ok:
                if DRY_RUN:
                    log_event({"type": "invite_planned", "url": page.url, "talent_id": talent_id})
                else:
                    log_event({"type": "invited", "url": page.url, "talent_id": talent_id})
                    if talent_id:
                        invited_db_add(talent_id, url=page.url)
                invited += 1
                await jitter(*CLICK_PAUSE)
        except Exception:
            # element may detach due to reflow; move on
            continue

    # Post-scan diagnostics and count for fallback
    post_invites = None
    try:
        post_invites = await page.locator(INVITE_MENU_BTN).count()
        if DEBUG:
            print(f"[debug] Visible invite buttons after scanning: {post_invites}")
    except Exception:
        post_invites = None

    # Favorites-mode fallback: if no cards matched (or none clicked), click hearts directly on the page
    if USE_FAVORITES and invited == 0:
        try:
            hearts = await page.query_selector_all(FAVORITE_BTN)
            clicked = 0
            favorites_selected_this_page = False
            for h in hearts:
                try:
                    active = await _is_heart_active(h)
                    if not favorites_selected_this_page:
                        # Use the first non-active heart to initialize the page's list selection
                        if active:
                            continue
                        ok = await _click_heart_element(page, h)
                        if ok:
                            await _ensure_favorites_list_selected(page)
                            favorites_selected_this_page = True
                            log_event({"type": "favorited", "url": page.url, "phase": "initializer"})
                            clicked += 1
                            await jitter(*CLICK_PAUSE)
                    else:
                        # After initialization, click hearts for non-active items only
                        if active:
                            continue
                        ok = await _click_heart_element(page, h)
                        if ok:
                            log_event({"type": "favorited", "url": page.url})
                            clicked += 1
                            await jitter(*CLICK_PAUSE)
                except Exception:
                    continue
            if clicked > 0:
                invited += clicked
        except Exception:
            pass

    # Fallback (invite mode only): if we didn't invite anyone via card-based flow, try clicking any visible Invite buttons directly
    if not USE_FAVORITES and invited == 0 and (post_invites or 0) > 0:
        try:
            btns = await page.query_selector_all(INVITE_MENU_BTN)
            try:
                log_event({"type": "fallback_invite_buttons", "count": len(btns)})
            except Exception:
                pass
            for btn in btns:
                try:
                    # Try mapping the button back to a talent ID and skip if already invited
                    try:
                        talent_id = await _extract_talent_id_from_button(page, btn)
                    except Exception:
                        talent_id = None
                    if talent_id and invited_db_has(talent_id):
                        log_event({"type": "skip_already_invited", "talent_id": talent_id, "where": "fallback_btns"})
                        continue
                    if not await btn.is_visible():
                        continue
                    # Ensure any prior dropdown is closed before proceeding
                    try:
                        await page.keyboard.press("Escape")
                    except Exception:
                        pass
                    await btn.scroll_into_view_if_needed()
                    # Robust dropdown opening and menu click
                    opened = await _click_existing_job_dropdown(page, btn)
                    if not opened:
                        try:
                            await btn.click()
                            await asyncio.sleep(0.25)
                            mi = await page.wait_for_selector(EXISTING_MENU_ITEM, timeout=2000)
                            if mi:
                                try:
                                    await mi.click(force=True)
                                except Exception:
                                    try:
                                        await page.eval_on_selector(EXISTING_MENU_ITEM, "el => el.click()")
                                    except Exception:
                                        pass
                                await asyncio.sleep(0.2)
                        except Exception:
                            pass
                    ok = await pick_job_in_modal(page)
                    if ok:
                        if DRY_RUN:
                            log_event({"type": "invite_planned", "url": page.url, "talent_id": talent_id})
                        else:
                            log_event({"type": "invited", "url": page.url, "talent_id": talent_id})
                            if talent_id:
                                invited_db_add(talent_id, url=page.url)
                        invited += 1
                        await jitter(*CLICK_PAUSE)
                except Exception:
                    continue
        except Exception:
            pass

    try:
        log_event({"type": "page_scan_end", "url": page.url, "count": int(invited), "dry_run": bool(DRY_RUN)})
    except Exception:
        pass
    return invited

async def goto_next_page(page) -> bool:
    # Ensure pagination is in view
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(0.2)
    except Exception:
        pass

    # 1) Prefer explicit next link variants (rel=next, title, sr-only "Next Page")
    try:
        next_link = await page.query_selector(NEXT_LINK_SEL)
        if next_link:
            href = None
            try:
                href = await next_link.get_attribute("href")
            except Exception:
                href = None
            try:
                await next_link.scroll_into_view_if_needed()
            except Exception:
                pass
            if href:
                if DEBUG:
                    try:
                        print(f"[debug] Navigating to next page via href: {href}")
                    except Exception:
                        pass
                await page.goto(href)
            else:
                await next_link.click()
            try:
                await page.wait_for_load_state("networkidle")
            except PWTimeout:
                await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(random.uniform(*PAGE_PAUSE))
            return True
    except Exception:
        pass

    # or numeric pagination
    try:
        curr = await page.query_selector(CURRENT_PAGE)
        if curr:
            txt = (await curr.inner_text()).strip()
            num = int(re.sub(r"\D+", "", txt) or "0")
            target = str(num + 1)
            nums = await page.query_selector_all(PAGINATION_NUMBERS)
            for n in nums:
                t = (await n.inner_text()).strip()
                if t == target:
                    await n.click()
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(random.uniform(*PAGE_PAUSE))
                    return True
    except Exception:
        pass

    # 3) Fallback: increment URL offset parameter (Voices uses offset=24*n)
    try:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
        u = urlparse(page.url)
        q = parse_qs(u.query)
        curr_offset = int(q.get("offset", [0])[0] or 0)
        next_offset = curr_offset + 24
        q["offset"] = [str(next_offset)]
        new_query = urlencode(q, doseq=True)
        new_url = urlunparse((u.scheme, u.netloc, u.path, u.params, new_query, u.fragment))
        if DEBUG:
            try:
                print(f"[debug] Fallback navigating to offset {next_offset}: {new_url}")
            except Exception:
                pass
        await page.goto(new_url)
        try:
            await page.wait_for_load_state("networkidle")
        except PWTimeout:
            await page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(random.uniform(*PAGE_PAUSE))
        return True
    except Exception:
        pass

    return False

async def main(
    cli_profile_dir: Optional[str] = None,
    disable_cdp: bool = False,
    headless: bool = False,
    slow_mo: int = 70,
    manual_login: bool = False,
    require_cdp: bool = False,
):
    state = load_checkpoint()
    invited_total = state["invited"]

    async with async_playwright() as p:
        using_persistent = False
        using_cdp = False
        using_cdp_browser = None
        context = None
        browser = None

        # First, try connecting to an already running Chrome via CDP (no profile lock)
        connect_cdp = CONNECT_RUNNING_CHROME and not disable_cdp
        if connect_cdp:
            cdp_urls = [CHROME_CDP_URL]
            # If using localhost, also try IPv4 explicitly to avoid ::1 resolution issues
            try:
                if "localhost" in CHROME_CDP_URL:
                    cdp_urls.append(CHROME_CDP_URL.replace("localhost", "127.0.0.1"))
            except Exception:
                pass

            last_err = None
            for cdp_url in cdp_urls:
                try:
                    browser = await p.chromium.connect_over_cdp(cdp_url)
                    # Reuse the first existing browser context (the current Chrome profile/window);
                    # if none are present, create a fresh incognito context to work in.
                    context = browser.contexts[0] if browser.contexts else await browser.new_context()
                    using_cdp = True
                    using_cdp_browser = browser
                    print(f"[mode] Connected to running Chrome over CDP at {cdp_url}.")
                    break
                except Exception as e:
                    last_err = e
                    browser = None
                    context = None
                    using_cdp = False
                    print(f"[hint] CDP connect failed at {cdp_url}: {e}")

            if not using_cdp:
                print("       To use CDP, start Chrome with: --remote-debugging-port=9222 and the desired profile.")
                if require_cdp:
                    print("[error] --require-cdp specified; aborting instead of falling back.")
                    return

        # Try to launch installed Chrome with your existing signed-in profile (system Chrome)
        if USE_SYSTEM_CHROME and not context:
            udd, profile = _resolve_chrome_profile()
            if udd:
                try:
                    print(f"[mode] Trying system Chrome profile at: {udd} (profile: {profile})\n       Ensure Chrome is closed for this profile to avoid lock errors.")
                    context = await p.chromium.launch_persistent_context(
                        user_data_dir=udd,
                        channel="chrome",
                        headless=headless,
                        slow_mo=slow_mo,
                        args=[f"--profile-directory={profile}"]
                    )
                    using_persistent = True
                except Exception as e:
                    print(f"[warn] System Chrome persistent launch failed: {e}\n       Tip: Close Chrome or use PLAYWRIGHT_USER_DATA_DIR for a dedicated profile.")
                    context = None
                    using_persistent = False

        # Prefer a dedicated persistent profile owned by Playwright (safest) as a fallback
        if not context and not (using_cdp and require_cdp):
            try:
                persistent_dir = (
                    cli_profile_dir
                    or os.environ.get("PLAYWRIGHT_USER_DATA_DIR")
                    or str(Path.cwd() / "playwright-profile")
                )
                print(f"[mode] Launching persistent Chromium with profile dir: {persistent_dir}")
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=persistent_dir,
                    headless=headless,
                    slow_mo=slow_mo,
                )
                using_persistent = True
            except Exception as e:
                print(f"[warn] Persistent Chromium launch failed: {e}")
                context = None
                using_persistent = False

        # Fallback to bundled Chromium + storage_state
        if not context and not (using_cdp and require_cdp):
            print("[mode] Falling back to non-persistent bundled Chromium + storage state.")
            browser = await p.chromium.launch(headless=headless, slow_mo=slow_mo)
            context = await browser.new_context(
                storage_state=STORAGE_STATE if Path(STORAGE_STATE).exists() else None
            )

        # If CDP was required but we have no context (and no browser), abort clearly
        if require_cdp and not using_cdp:
            print("[error] CDP was required but connection was not established. Exiting.")
            return

        # Open a new tab in the appropriate mode
        if using_cdp:
            # Open a tab in the existing Chrome window/profile
            try:
                page = await context.new_page()
            except Exception as e:
                print(f"[error] Failed to open a new page over CDP: {e}")
                return
        else:
            # Open a fresh page in our managed context
            page = await context.new_page()

        await login_if_needed(context, page, manual_login=manual_login)
        await page.goto(START_URL)
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(random.uniform(*PAGE_PAUSE))

        while invited_total < TARGET_INVITES:
            await pause_if_requested()
            added = await invite_all_on_page(page)
            invited_total += added
            if DRY_RUN:
                print(f"Planned invites on this page: {added} | Total planned: {invited_total}")
            else:
                print(f"Invited on this page: {added} | Total: {invited_total}")
            save_checkpoint({"page_num": state["page_num"] + 1, "invited": invited_total})

            await asyncio.sleep(random.uniform(*PAGE_PAUSE))
            if added == 0:
                # still try to move on—maybe all on this page were already invited
                pass

            await pause_if_requested()
            has_next = await goto_next_page(page)
            if not has_next:
                print("No next page found; done.")
                break

        # Persist and close cleanly depending on how we launched
        try:
            await context.storage_state(path=STORAGE_STATE)
        except Exception:
            pass
        if using_persistent:
            await context.close()
        elif using_cdp:
            # Don't close the user's Chrome; just close our tab
            try:
                await page.close()
            except Exception:
                pass
        else:
            await browser.close()

def _parse_cli_args():
    parser = argparse.ArgumentParser(description="Invite talents on voices.com to a specific job.")
    parser.add_argument(
        "--start-url",
        dest="start_url",
        help="Start from this search URL (overrides VOICES_START_URL and default START_URL).",
    )
    parser.add_argument(
        "--job-id",
        dest="job_id",
        help="Voices job ID to invite candidates to (overrides VOICES_JOB_ID).",
    )
    parser.add_argument(
        "--job-title",
        dest="job_title",
        help="Fallback substring of job title to match if job ID is not found.",
    )
    parser.add_argument(
        "--no-job-filter",
        action="store_true",
        help="Ignore job ID/title and just click the modal's Invite button.",
    )
    parser.add_argument(
        "--use-favorites",
        action="store_true",
        help="Use the Favorites heart instead of inviting to a job.",
    )
    parser.add_argument(
        "--favorites-list",
        dest="favorites_list",
        help="Title of the Favorites list to add to (selected the first time only).",
    )
    parser.add_argument(
        "--profile-dir",
        dest="profile_dir",
        help="Path to a persistent user data directory to use/create for the browser profile.",
    )
    parser.add_argument(
        "--no-cdp",
        action="store_true",
        help="Disable attempting to connect to a running Chrome via CDP.",
    )
    parser.add_argument(
        "--require-cdp",
        action="store_true",
        help="Require connecting to a running Chrome via CDP; do not fall back to launching a new browser.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the browser in headless mode.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=70,
        metavar="MS",
        help="Slow down Playwright actions by the given milliseconds (default: 70).",
    )
    parser.add_argument(
        "--scroll-passes",
        type=int,
        default=None,
        help="Number of vertical scroll passes per page to trigger lazy loading (default: 2).",
    )
    parser.add_argument(
        "--manual-login",
        action="store_true",
        help="Pause automation and let you log in manually (e.g., Google SSO).",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Faster timings: smaller click/page pauses and fewer scroll passes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not click anything; report what would be clicked via logs.",
    )
    parser.add_argument(
        "--log-file",
        dest="log_file",
        help="Path to JSONL log file for structured events.",
    )
    parser.add_argument(
        "--invited-db",
        dest="invited_db",
        help="Path to JSON file storing already-invited talent IDs to skip.",
    )
    parser.add_argument(
        "--pause-file",
        dest="pause_file",
        help="Create this file to pause; delete it to resume (default: PAUSE in CWD or VOICES_PAUSE_FILE).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    _args = _parse_cli_args()
    # Allow starting from a specific URL/page offset
    if _args.start_url:
        START_URL = _args.start_url  # type: ignore[name-defined]
        os.environ["VOICES_START_URL"] = _args.start_url
    # Allow CLI to override job selection without requiring env vars
    if _args.job_id:
        REQUIRED_JOB_ID = _args.job_id.strip()
    if _args.job_title:
        os.environ["VOICES_JOB_TITLE"] = _args.job_title
    if _args.no_job_filter:
        REQUIRED_JOB_ID = ""
        if "VOICES_JOB_TITLE" in os.environ:
            del os.environ["VOICES_JOB_TITLE"]
    if _args.scroll_passes is not None:
        SCROLL_PASSES = int(_args.scroll_passes)
    if _args.pause_file:
        PAUSE_FILE = _args.pause_file  # type: ignore[name-defined]
    # Logging config
    if getattr(_args, "log_file", None):
        LOG_FILE = _args.log_file  # type: ignore[name-defined]
        os.environ["VOICES_LOG_FILE"] = _args.log_file
    # Favorites mode
    if getattr(_args, "use_favorites", False):
        USE_FAVORITES = True  # type: ignore[name-defined]
        os.environ["VOICES_USE_FAVORITES"] = "1"
    if getattr(_args, "favorites_list", None):
        FAVORITES_LIST_TITLE = _args.favorites_list  # type: ignore[name-defined]
        os.environ["VOICES_FAVORITES_LIST"] = _args.favorites_list
    # Dry-run mode
    if getattr(_args, "dry_run", False):
        DRY_RUN = True  # type: ignore[name-defined]
        os.environ["VOICES_DRY_RUN"] = "1"
    # Invited DB path
    if getattr(_args, "invited_db", None):
        INVITED_DB = _args.invited_db  # type: ignore[name-defined]
        os.environ["VOICES_INVITED_DB"] = _args.invited_db
    # Apply fast mode if requested (or via env VOICES_FAST)
    if _args.fast or os.environ.get("VOICES_FAST", "0").lower() in {"1", "true", "yes", "on"}:
        CLICK_PAUSE = (0.3, 0.6)
        PAGE_PAUSE = (1.0, 2.0)
        if _args.scroll_passes is None:
            SCROLL_PASSES = 1
    asyncio.run(
        main(
            cli_profile_dir=_args.profile_dir,
            disable_cdp=_args.no_cdp,
            headless=_args.headless,
            slow_mo=_args.slow_mo,
            manual_login=_args.manual_login,
            require_cdp=_args.require_cdp or REQUIRE_CDP,
        )
    )
