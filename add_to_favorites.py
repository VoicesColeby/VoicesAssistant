import asyncio
import os
import random
from playwright.async_api import async_playwright, Page, Locator
from common_logging import info, ok, warn, err

# ================== Config ==================
START_URL = os.getenv("START_URL", "https://www.voices.com/talents/search")
CDP_URL = os.getenv("DEBUG_URL", "http://127.0.0.1:9222")
SPEED = float(os.getenv("SPEED", "1.0"))
SPEED_FILE = os.getenv("SPEED_FILE", "").strip()
FIRST_HEART_DELAY_MS = int(os.getenv("FIRST_HEART_DELAY_MS", "0"))  # unscaled, default off
MAX_PAGES = int(os.getenv("MAX_PAGES", "999"))
AUTO_DISMISS_DROPDOWN = os.getenv("AUTO_DISMISS_DROPDOWN", "0").strip().lower() in ("1", "true", "yes")
use_current = os.getenv("USE_CURRENT_PAGE", "1").strip().lower() in ("1", "true", "yes")

# pacing (base values; live speed scaling applied via r())
BASE_BETWEEN_STEPS_MS = 700
BASE_BETWEEN_FAVORITES_MS = 1200
BASE_BETWEEN_PAGES_MS = 1500

# selectors
# Legacy/general heart selector (kept for reference, but not used directly)
HEART_ICON = ", ".join([
    "i.action-list-btn.fa-heart",      # solid heart on card actions
    "i.action-list-btn.fa-heart-o",    # legacy outline heart
    "i.fas.fa-heart",                  # FA5 solid
    "i.far.fa-heart",                  # FA5 outline
    "button.add-to-favorites",         # legacy button
    "[aria-label*='Favorite']",        # accessibility label
])

# A robust set of possible heart selectors. We try them in order.
HEART_SELECTORS = [
    # Voices-specific: heart icon with data attributes
    "i.action-list-btn[data-item-id][data-item-type]",
    # aria/button names
    "button[aria-label*='Favorite' i]",
    "button[aria-label*='Favourite' i]",
    "button[title*='Favorite' i]",
    "button[title*='Favourite' i]",

    # common non-button labels/titles on <i> or other tags
    "[aria-label*='Favorite' i]",
    "[aria-label*='Favourite' i]",
    "[aria-label*='Save to Favorite' i]",
    "[title*='Save to Favorite' i]",
    "[data-bs-original-title*='Favorite' i]",

    # data attributes commonly used for favorites
    "button[data-action*='favorite' i]",
    "[data-action*='favorite' i]",

    # icon-based (font-awesome or svg hearts wrapped in a button)
    "button:has(i.fa-heart), button:has(i.fas.fa-heart), button:has(i.far.fa-heart)",
    "button:has(svg[aria-hidden='true'] use[href*='heart'])",
    "button:has(svg[aria-label*='Favorite' i])",

    # generic "action-list" button often used on cards
    ".action-list-btn:has(i.fa-heart)",
    "button.action-list-btn:has(i.fa-heart)",

    # direct <i> variants (as in Voices)
    "i.action-list-btn.fa-heart",
    "i.far.fa-heart",
    "i.fas.fa-heart",
]

CARD_CONTAINER_SELECTORS = [
    # list/grid containers that must exist before we start clicking
    "[data-testid='talent-results']",
    ".talent-results, .talent-cards, .search-results-grid",
    ".results-list, .results-grid",
]
NEXT_PAGE_SELECTOR = """
    a[aria-label='Next']:not(.disabled):not([aria-disabled='true']),
    .pagination a:has(i.fa-angle-right):not(.disabled),
    .pagination button:has(i.fa-angle-right):not(:disabled)
"""

# ============== Logging helpers ==============
# moved to common_logging module

# ============== Randomized pacing (live) ==============
def _read_speed_file() -> float:
    try:
        if SPEED_FILE and os.path.exists(SPEED_FILE):
            with open(SPEED_FILE, 'r', encoding='utf-8') as f:
                v = float((f.read() or '5').strip())
                return max(1.0, min(5.0, v))
    except Exception:
        pass
    try:
        return max(1.0, min(5.0, float(os.getenv("SPEED", str(SPEED)))))
    except Exception:
        return 5.0

def r(min_ms, max_ms):
    s = _read_speed_file()
    lo = min_ms / s
    hi = max_ms / s
    return random.uniform(lo/1000, hi/1000)

async def step_pause(): await asyncio.sleep(r(BASE_BETWEEN_STEPS_MS, BASE_BETWEEN_STEPS_MS+400))
async def fav_pause():  await asyncio.sleep(r(BASE_BETWEEN_FAVORITES_MS, BASE_BETWEEN_FAVORITES_MS+800))
async def page_pause(): await asyncio.sleep(r(BASE_BETWEEN_PAGES_MS, BASE_BETWEEN_PAGES_MS+1000))

# ============== Core ==============
async def wait_for_results_to_render(page: Page):
    # wait for any container selector and at least 1 candidate heart to be present/visible
    for sel in CARD_CONTAINER_SELECTORS:
        try:
            await page.locator(sel).first.wait_for(state="visible", timeout=7000)
            break
        except Exception:
            pass

    # also wait briefly for at least one heart to exist (not necessarily visible)
    found = False
    for hs in HEART_SELECTORS:
        try:
            if await page.locator(hs).count() > 0:
                found = True
                break
        except Exception:
            pass
    if not found:
        # give the page a little more time to hydrate
        await page.wait_for_timeout(1200)
    # brief SPEED-scaled settle after initial render
    try:
        await step_pause()
    except Exception:
        pass


async def query_all_hearts(page: Page) -> Locator:
    # Prefer the stable, on-card heart icons (direct child of favorites-action-list)
    try:
        preferred = page.locator("div.favorites-action-list > i.action-list-btn")
        if await preferred.count() > 0:
            return preferred
    except Exception:
        pass
    # Otherwise, merge broader selectors via a single :is(...)
    combo = ", ".join(HEART_SELECTORS)
    try:
        visible = page.locator(f":is({combo}):visible")
        if await visible.count() > 0:
            return visible
    except Exception:
        pass
    return page.locator(f":is({combo})")


async def maybe_wait_for_fav_signal(page: Page, button: Locator):
    # Try a few lightweight signals, but don't fail the click if we don't see them.
    try:
        handle = await button.element_handle()
    except Exception:
        handle = None

    if handle is not None:
        try:
            await page.wait_for_function(
                "(el) => el && el.getAttribute('aria-pressed') === 'true'",
                handle,
                timeout=1200,
            )
            return
        except Exception:
            pass
        try:
            await page.wait_for_function(
                "(el) => { const t=(el && (el.getAttribute('title')||el.getAttribute('data-bs-original-title')||'')); const s=t.toLowerCase(); return s.includes('favorited') || s.includes('saved'); }",
                handle,
                timeout=1200,
            )
            return
        except Exception:
            pass

    try:
        # some apps flip classes on inner <i> or the button
        inner_i = button.locator("i, svg")
        await inner_i.first.wait_for(state="attached", timeout=400)
        await page.wait_for_timeout(250)  # tiny settle
    except Exception:
        pass
    # Also try class flip to FontAwesome solid heart
    try:
        h = await button.element_handle()
    except Exception:
        h = None
    if h is not None:
        try:
            await page.wait_for_function(
                "(el) => el && el.classList && el.classList.contains('fas') && el.classList.contains('fa-heart')",
                h,
                timeout=800,
            )
        except Exception:
            pass


async def js_click(button: Locator):
    try:
        handle = await button.element_handle()
        if handle is None:
            return False
        # Try native click first
        await handle.evaluate("el => el.click()")
        return True
    except Exception:
        # Fallbacks: dispatch event and/or click a clickable ancestor within favorites-action-list
        try:
            clicked = await button.evaluate(
                "(el) => {\n"
                "  if (!el) return false;\n"
                "  try { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window })); return true; } catch(e) {}\n"
                "  const root = el.closest('.favorites-action-list') || el.parentElement;\n"
                "  if (root) {\n"
                "    const alt = root.querySelector('.action-list-btn, button, [role=button]');\n"
                "    if (alt) { try { alt.click(); return true; } catch(e) {} }\n"
                "  }\n"
                "  return false;\n"
                "}"
            )
            return bool(clicked)
        except Exception:
            return False


async def hover_reveal(page: Page, button: Locator):
    try:
        handle = await button.element_handle()
        if handle is None:
            return
        # Find a reasonable card ancestor to hover
        card = await handle.evaluate_handle(
            'el => el.closest(\'[data-testid="talent-card"], .talent-card, .search-card, .result-card, .profile-card, article, li\') || el'
        )
        # Try bounding box hover if available
        try:
            box = await card.bounding_box()
        except Exception:
            box = None
        if box:
            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2
            try:
                await page.mouse.move(x, y, steps=12)
                await page.wait_for_timeout(150)
            except Exception:
                pass
        else:
            # Fallback: evaluate scroll + hover center
            try:
                await button.evaluate("el => el.scrollIntoView({block: 'center', inline: 'center'})")
                await page.wait_for_timeout(120)
            except Exception:
                pass
    except Exception:
        pass


async def maybe_wait_for_fav_signal_any(page: Page, target):
    # Lightweight, best-effort confirmation on either a Locator or ElementHandle
    try:
        handle = await target.element_handle() if hasattr(target, 'element_handle') else target
    except Exception:
        handle = None

    if handle is not None:
        try:
            await page.wait_for_function(
                "(el) => el && el.getAttribute('aria-pressed') === 'true'",
                handle,
                timeout=1200,
            )
            return
        except Exception:
            pass
        try:
            await page.wait_for_function(
                "(el) => { const t=(el && (el.getAttribute('title')||el.getAttribute('data-bs-original-title')||'')); const s=t.toLowerCase(); return s.includes('favorited') || s.includes('saved'); }",
                handle,
                timeout=1200,
            )
            return
        except Exception:
            pass
        try:
            await page.wait_for_function(
                "(el) => el && el.classList && el.classList.contains('fas') && el.classList.contains('fa-heart')",
                handle,
                timeout=800,
            )
        except Exception:
            pass


async def dismiss_action_list_dropdown(page: Page):
    try:
        dropdown = page.locator('.action-list-dropdown')
        if await dropdown.first.is_visible():
            try:
                # Prefer explicit toggles or Done button
                done_btn = dropdown.locator("button[data-toggle='action-list'], [data-toggle='action-list']:has-text('Done')").first
                if await done_btn.count() > 0:
                    await done_btn.click()
                else:
                    await page.keyboard.press('Escape')
            except Exception:
                try:
                    await page.keyboard.press('Escape')
                except Exception:
                    pass
            await page.wait_for_timeout(150)
    except Exception:
        pass


async def click_heart_buttons(page: Page):
    stats = {"seen": 0, "hearted": 0, "skipped": 0}

    # ensure results are present
    await wait_for_results_to_render(page)
    # small SPEED-scaled settle before collecting/iterating hearts
    await step_pause()

    # optional: delay before the very first heart to look human
    if FIRST_HEART_DELAY_MS > 0:
        await page.wait_for_timeout(FIRST_HEART_DELAY_MS)

    hearts = await query_all_hearts(page)
    count = await hearts.count()
    if count == 0:
        warn("No heart buttons found on this page")
        return stats

    stats["seen"] = count
    info(f"Found {count} candidate heart buttons")

    # Cache viewport height once to avoid repeated calls
    try:
        viewport_h = await page.evaluate("() => window.innerHeight")
    except Exception:
        viewport_h = None

    for i in range(count):
        btn = hearts.nth(i)
        try:
            # Skip elements that are rendered inside the action-list dropdown (menu content)
            try:
                h = await btn.element_handle()
            except Exception:
                h = None
            if h is not None:
                try:
                    inside_dropdown = await h.evaluate("el => !!el.closest('.action-list-dropdown')")
                except Exception:
                    inside_dropdown = False
                if inside_dropdown:
                    stats["skipped"] += 1
                    continue

            # Skip already favorited to avoid toggling off
            try:
                handle = await btn.element_handle()
                if handle is not None:
                    pressed = await handle.get_attribute('aria-pressed')
                    klass = await handle.get_attribute('class')
                    if (pressed and pressed.lower() == 'true') or (klass and 'fas' in klass and 'fa-heart' in klass):
                        stats["skipped"] += 1
                        continue
            except Exception:
                pass
            # Only attempt scroll if clearly outside viewport or not measurable
            need_scroll = False
            try:
                bbox = await btn.bounding_box()
            except Exception:
                bbox = None
            if bbox is None:
                need_scroll = True
            else:
                if viewport_h is not None:
                    if bbox.get("y", 0) < 0 or bbox.get("y", 0) > (viewport_h - max(8, int(bbox.get("height", 0)))):
                        need_scroll = True

            if need_scroll:
                # Use a light JS-based scroll without waiting for stability
                try:
                    await btn.evaluate("el => el.scrollIntoView({block: 'center', inline: 'center'})")
                    await page.wait_for_timeout(120)
                except Exception:
                    try:
                        handle = await btn.element_handle()
                    except Exception:
                        handle = None
                    if handle is not None:
                        try:
                            await page.evaluate(
                                """
                                (el) => {
                                  let n = el;
                                  while (n && n !== document.body) {
                                    const st = getComputedStyle(n);
                                    const canScroll = (st.overflowY === 'auto' || st.overflowY === 'scroll');
                                    if (canScroll && n.scrollHeight > n.clientHeight) {
                                      const r = el.getBoundingClientRect();
                                      n.scrollTop = Math.max(0, n.scrollTop + r.top - n.clientHeight * 0.3);
                                      return;
                                    }
                                    n = n.parentElement;
                                  }
                                  const r = el.getBoundingClientRect();
                                  const y = r.top + window.scrollY - (window.innerHeight * 0.3);
                                  window.scrollTo({ top: Math.max(0, y) });
                                }
                                """,
                                handle,
                            )
                            await page.wait_for_timeout(120)
                        except Exception:
                            pass
            # Try to ensure visibility; if not visible, attempt to reveal by hovering ancestor
            try:
                if not await btn.is_visible():
                    await hover_reveal(page, btn)
            except Exception:
                pass

            # Hover if possible (optional)
            try:
                await btn.hover(timeout=600)
            except Exception:
                pass

            # Single, simple click with one retry if dropdown interferes
            clicked = False
            last_err = None
            for attempt in range(2):
                try:
                    await btn.click(timeout=2000, force=True)
                    clicked = True
                    break
                except Exception as e:
                    last_err = e
                    # Try JS click first
                    try:
                        clicked = await js_click(btn)
                        if clicked:
                            break
                    except Exception:
                        clicked = False
                    # If dropdown is visible, close and retry once (interference-based)
                    try:
                        if await page.locator('.action-list-dropdown').first.is_visible():
                            await dismiss_action_list_dropdown(page)
                            continue
                    except Exception:
                        pass
                    break

            if not clicked:
                raise Exception(f"Click failed (both real and JS): {last_err}")

            # Optional tiny confirmation wait, non-blocking
            await maybe_wait_for_fav_signal_any(page, btn)

            # Only close dropdown proactively if it remains visible and may block the next item
            # This is guarded by AUTO_DISMISS_DROPDOWN and happens only when visible.
            if AUTO_DISMISS_DROPDOWN:
                try:
                    if await page.locator('.action-list-dropdown').first.is_visible():
                        await dismiss_action_list_dropdown(page)
                except Exception:
                    pass

            stats["hearted"] += 1
            ok(f"Heart clicked {i+1}/{count}")
        except Exception as e:
            warn(f"Skipped heart {i+1}: {e}")
            stats["skipped"] += 1

        # SPEED-scaled pacing between actions
        if i < count - 1:
            await fav_pause()

    return stats

async def go_to_next_page(page):
    try:
        next_link = page.locator(NEXT_PAGE_SELECTOR).first
        if await next_link.count() == 0:
            info("No next page link found")
            return False
        is_disabled = await next_link.get_attribute("aria-disabled")
        if is_disabled == "true":
            info("Next page link disabled (last page)")
            return False
        await next_link.scroll_into_view_if_needed()
        await asyncio.sleep(0.2)
        await next_link.click()
        await page.wait_for_load_state("networkidle", timeout=12000)
        await page_pause()
        return True
    except Exception as e:
        warn(f"Next page failed: {e}")
        return False

# ============== Main ==============
async def main():
    info("Starting 'Add to Favorites'")
    info(f"URL: {START_URL}")
    info(f"CDP: {CDP_URL}")
    info(f"SPEED: {SPEED}")
    info(f"FIRST_HEART_DELAY_MS: {FIRST_HEART_DELAY_MS} (unscaled, first page only)")

    async with async_playwright() as p:
        # Robust connection
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            info("Attached to existing Chrome via CDP")
            # If user prefers current page, try to keep the current tab and URL
            try:
                if use_current:
                    # Prefer an existing voices.com page if available
                    all_pages = []
                    for ctx in browser.contexts:
                        for pg in ctx.pages:
                            all_pages.append((ctx, pg))
                    if all_pages:
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
                        context, page = sorted(all_pages, key=page_rank)[-1]
                    cur = (page.url or '').strip()
                    if cur:
                        globals()['START_URL'] = cur
                        try:
                            globals()['FIRST_HEART_DELAY_MS'] = 0
                        except Exception:
                            pass
                        info("Using current page; will keep existing URL.")
            except Exception:
                pass
        except Exception as cdp_err:
            warn(f"Could not attach over CDP ({cdp_err}). Falling back...")
            user_data = os.getenv("CHROME_USER_DATA", "").strip()
            if user_data:
                info(f"Launching persistent context with CHROME_USER_DATA={user_data}")
                context = await p.chromium.launch_persistent_context(user_data, headless=False, args=[])
                page = context.pages[0] if context.pages else await context.new_page()
            else:
                info("Launching fresh browser (you may need to log in)")
                browser = await p.chromium.launch(headless=False)
                context = await browser.new_context()
                page = await context.new_page()

        # Navigate
        await page.goto(START_URL, wait_until="domcontentloaded")
        if FIRST_HEART_DELAY_MS > 0:
            # Initial delay disabled by default; use GUI pause when needed
            await asyncio.sleep(FIRST_HEART_DELAY_MS/1000)

        totals = {"seen": 0, "hearted": 0, "skipped": 0}
        page_num = 1
        while page_num <= MAX_PAGES:
            info(f"\n=== Page {page_num} ===")
            stats = await click_heart_buttons(page)
            for k in totals: totals[k] += stats[k]
            info(f"Page {page_num} results: {stats}")
            if not await go_to_next_page(page): break
            page_num += 1

        info("\n=== COMPLETE ===")
        info(f"Seen: {totals['seen']}")
        ok(f"Hearted: {totals['hearted']}")
        warn(f"Skipped: {totals['skipped']}")
        info("Done. Browser stays open.")

if __name__ == "__main__":
    asyncio.run(main())
