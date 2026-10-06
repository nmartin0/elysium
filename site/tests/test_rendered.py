"""
What the page actually looks like in a browser.

EVERY OTHER TEST IN THIS DIRECTORY CHECKS THAT STRINGS EXIST IN A
FILE. None of them could see that the cookie preferences panel was
open over the hero on first paint, that the code block was clipped
mid-line, or that the primary button rendered grey on blue. I wrote
eight patches of CSS without once looking at the result, and the owner
had to tell me each time.

These run a real Chromium and measure the rendered page. They are
slower and worth it: every assertion here corresponds to something
that shipped broken and was invisible to the string tests.

SKIPPED, NOT FAILED, where no browser is available -- a contributor
without one should still be able to run the rest.
"""

import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parent.parent

pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser_page():
    from playwright.sync_api import sync_playwright

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except Exception as error:  # noqa: BLE001 - no browser installed
                pytest.skip(f"no chromium: {error}")
            def open_at(width, path="/"):
                opened = browser.new_page(viewport={"width": width, "height": 900})
                opened.goto(f"http://127.0.0.1:{port}{path}")
                opened.wait_for_timeout(300)
                return opened

            yield open_at
            browser.close()
    finally:
        server.shutdown()


@pytest.fixture(scope="module")
def page(browser_page):
    """The desktop view, which is what every test below assumed and
    which is exactly why two bugs survived: the page overflowed its
    viewport by 71px on a phone and the footer floated mid-screen on
    the short pages. A fixture that only ever opened one window at one
    width could not see either."""
    return browser_page(1440)


class TestNothingIsHiddenOrClipped:
    def test_the_consent_preferences_are_collapsed_on_arrival(self, page):
        """IT RENDERED OPEN, covering a third of the first screen.

        `[hidden]` is a user-agent rule and `.consent__inner` set
        `display: flex` at the same specificity, later in the cascade,
        so it won. The first thing every visitor saw was an expanded
        preferences form over the headline."""
        panel = page.locator("[data-consent-panel]")

        assert panel.is_hidden()

    def test_nothing_overflows_the_viewport_sideways(self, page):
        """A horizontal scrollbar on a marketing page is the clearest
        signal nobody looked at it."""
        width = page.evaluate("document.documentElement.scrollWidth")

        assert width <= 1440, f"page is {width}px wide in a 1440px window"

    def test_the_code_block_is_not_clipped(self, page):
        """It was cut mid-line at the container edge. `overflow-x:
        auto` HID the failure -- the text was there, behind a scrollbar
        nobody would find."""
        for i in range(page.locator("pre.snippet").count()):
            block = page.locator("pre.snippet").nth(i)
            overflow = block.evaluate("e => e.scrollWidth - e.clientWidth")

            assert overflow <= 2, f"snippet {i} overflows by {overflow}px"


class TestTheCallToActionIsReadable:
    def test_the_primary_button_is_not_grey_on_blue(self, page):
        """It was, for two patches. `.masthead nav a` is specificity
        0-1-2 and beat `.btn--primary` at 0-1-0 regardless of order, so
        the one element that had to be legible was not."""
        button = page.locator(".masthead .btn--primary").first
        colour = button.evaluate("e => getComputedStyle(e).color")
        background = button.evaluate("e => getComputedStyle(e).backgroundColor")

        def luminance(css):
            red, green, blue = (int(n) for n in css[css.index("(") + 1:css.index(")")]
                                .split(",")[:3])
            return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255

        contrast = abs(luminance(colour) - luminance(background))

        assert contrast > 0.4, f"{colour} on {background} is unreadable"


class TestTheLayoutUsesTheWidth:
    def test_the_hero_fills_the_frame(self, page):
        """"The right side looks barren like a desert." Measured: the
        hero's content must reach most of the way across its own
        container, not sit in the left third."""
        hero = page.locator(".hero").first.bounding_box()
        aside = page.locator(".hero__aside").first.bounding_box()

        reach = (aside["x"] + aside["width"]) - hero["x"]

        assert reach > hero["width"] * 0.9, "the hero leaves its right side empty"

    def test_no_section_leaves_a_column_empty_for_long(self, page):
        """A sticky heading beside a long body leaves hundreds of
        pixels of nothing. A band whose body runs long lays its head
        across the top instead."""
        for i in range(page.locator(".band").count()):
            band = page.locator(".band").nth(i)
            head = band.locator(".band__head").bounding_box()
            body = band.locator(".band__body").bounding_box()

            side_by_side = abs(head["y"] - body["y"]) < 40
            if side_by_side:
                assert body["height"] < head["height"] * 4, (
                    f"band {i}: a {head['height']:.0f}px head beside a "
                    f"{body['height']:.0f}px body leaves the left blank")


class TestTextPlacementIsSystematic:
    """"The text placement within the pages is still poor. It doesn't
    look natural."

    I measured every text block in the rendered page rather than
    guessing, and the numbers said exactly what was wrong: TEN distinct
    left edges where only one was the page margin, and FOUR body sizes
    including a 22px lede beside a 21px one -- a one-pixel difference
    between two things that are the same kind of text, which is the
    clearest tell of a page assembled block by block.

    These assert the system rather than any particular number, so the
    next block added has to join it."""

    def test_prose_uses_one_size_per_role(self, page):
        """Four steps and nothing between them: lede, prose, caption,
        label. Five sizes means two of them are doing one job."""
        sizes = page.evaluate("""() => [...document.querySelectorAll('p,dd')]
            .filter(e => e.getBoundingClientRect().width > 2)
            .map(e => getComputedStyle(e).fontSize)""")

        assert len(set(sizes)) <= 4, f"{len(set(sizes))} prose sizes: {sorted(set(sizes))}"

    def test_no_two_prose_sizes_are_within_two_pixels(self, page):
        """The 22px-beside-21px fault, stated as a rule. Two sizes that
        close read as a mistake rather than a decision."""
        sizes = sorted({float(s[:-2]) for s in page.evaluate(
            """() => [...document.querySelectorAll('p,dd')]
                .filter(e => e.getBoundingClientRect().width > 2)
                .map(e => getComputedStyle(e).fontSize)""")})
        # RATIOS, NOT PIXELS. A first version demanded a gap of more
        # than 2px and rejected 11-to-13 -- a label and a caption,
        # which are different roles and legitimately close at small
        # sizes. What actually reads as a mistake is two sizes within
        # about a tenth of each other, like the 22px lede that sat
        # beside a 21px one.
        ratios = [b / a for a, b in zip(sizes, sizes[1:], strict=False)]

        assert all(ratio > 1.12 for ratio in ratios), f"sizes too close: {sizes}"

    def test_every_paragraph_is_readable_width(self, page):
        """45 to 75 characters is the published range for running
        text. The floor here is 34, not 45, because text inside a card
        is legitimately narrower -- a three-up grid gives each tile
        about 37 characters and that is normal for the form.

        What this catches is the real failure: a paragraph four words
        wide, which is what the nested grids produced and what made
        the split unreadable."""
        bad = page.evaluate("""() => [...document.querySelectorAll('p')]
            .filter(e => e.getBoundingClientRect().width > 2)
            .map(e => {
              const r = e.getBoundingClientRect();
              const size = parseFloat(getComputedStyle(e).fontSize);
              return {chars: Math.round(r.width / (size * 0.5)),
                      text: e.textContent.trim().slice(0, 30)};
            })
            .filter(p => p.chars < 34 || p.chars > 85)""")

        assert bad == [], bad


class TestSmallScreens:
    """THE PAGE WAS 461px WIDE IN A 390px VIEWPORT and every rendered
    test passed, because they all opened a 1440px window.

    The cause is the classic one: a grid item's default `min-width` is
    `auto`, so a child that cannot shrink -- a <pre> of monospace code
    -- forces its column wider than the frame, and every block in that
    band inherits the width. `overflow-x: auto` did not save it, since
    that lets the box scroll only once the box may be narrower than its
    contents."""

    def test_nothing_overflows_a_phone(self, browser_page):
        phone = browser_page(390)
        width = phone.evaluate("document.documentElement.scrollWidth")

        assert width <= 390, f"page is {width}px wide in a 390px window"

    def test_the_mark_comes_before_the_navigation_on_a_phone(self, browser_page):
        """It wrapped with the links ABOVE the wordmark -- putting the
        mark second on exactly the device where top-left placement
        matters most."""
        phone = browser_page(390)
        mark = phone.locator(".wordmark").bounding_box()
        nav = phone.locator(".masthead nav").bounding_box()

        assert mark["y"] < nav["y"], "the navigation sits above the mark"


class TestShortPages:
    """The trust and legal pages are a heading and a paragraph, so the
    footer landed two thirds up the window with a third of the screen
    empty beneath it. A footer floating mid-viewport is the clearest
    signal a page is unfinished."""

    def test_the_footer_sits_on_the_bottom_of_a_short_page(self, browser_page):
        short = browser_page(1440, "/trust/")
        footer = short.locator(".footer").bounding_box()

        assert footer["y"] + footer["height"] >= 880, (
            f"footer ends at {footer['y'] + footer['height']:.0f} in a 900px window")

    def test_the_header_still_spans_the_full_width(self, browser_page):
        """Making the body a flex column grounded the footer and broke
        the header: `margin-inline: auto` on a flex item makes it
        shrink to its contents instead of stretching, so the bar lost
        its full width and the navigation bunched against the mark."""
        short = browser_page(1440, "/trust/")
        head = short.locator(".masthead").bounding_box()

        assert head["width"] >= 1430, f"masthead is only {head['width']:.0f}px wide"

    def test_the_navigation_matches_the_homepage(self, browser_page):
        """Inner pages kept a "Demo" text link beside the "Try the
        demo" button, removed from the homepage three patches earlier.
        Navigation that differs between pages reads as unfinished
        before anybody reads a word."""
        home = browser_page(1440, "/")
        inner = browser_page(1440, "/trust/")

        def links(target):
            return target.eval_on_selector_all(
                ".masthead nav a", "els => els.map(e => e.textContent.trim())")

        assert links(home) == links(inner)
