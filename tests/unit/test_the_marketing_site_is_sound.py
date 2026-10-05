"""
The marketing site: structure, links, and the consent requirements.

NO BUILD STEP, by choice. The site is hand-written HTML and CSS served
as files -- a marketing site that needs a toolchain to change a
headline is a marketing site nobody changes. The cost of that choice
is that nothing type-checks it, so this file is the check.

THE CONSENT RULES ARE LEGAL REQUIREMENTS and they are tested here
rather than trusted:

    PRIOR      non-essential cookies stay blocked until consent
    EQUAL      "Reject All" at the FIRST layer, same prominence as
               "Accept All" -- an unequal pair is a dark pattern, and
               dark patterns are the current enforcement priority
    GRANULAR   per category
    WITHDRAWN  as easily as given, hence a footer link on every page
    LOGGED     the choice and when it was made

Fines reach 20 million euro or 4% of global turnover, so "it looked
right" is not a standard worth holding this to.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

SITE = Path("site")
PAGES = sorted(SITE.rglob("*.html"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        found = dict(attrs)
        if "id" in found:
            self.ids.add(found["id"])
        if tag == "a" and found.get("href"):
            self.hrefs.append(found["href"])


def _parsed(path: Path) -> _Links:
    parser = _Links()
    parser.feed(_text(path))
    return parser


class TestThePagesExist:
    def test_there_is_a_landing_page(self):
        assert (SITE / "index.html").exists()

    @pytest.mark.parametrize("page", [
        "legal/privacy/index.html",
        "legal/terms/index.html",
        "legal/cookies/index.html",
        "legal/accessibility/index.html",
        "trust/index.html",
        "demo/index.html",
    ])
    def test_every_page_the_footer_promises(self, page):
        """A footer link to a page that does not exist is a 404 on the
        most scrutinised part of the site."""
        assert (SITE / page).exists(), page


class TestEveryInternalLinkResolves:
    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_links_and_anchors_go_somewhere(self, page):
        parsed = _parsed(page)
        broken = []
        for href in parsed.hrefs:
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            if href.startswith("#"):
                if href != "#" and href[1:] not in parsed.ids:
                    broken.append(href)
                continue
            target = SITE / href.lstrip("/")
            if target.is_dir() or href.endswith("/"):
                target = target / "index.html"
            if not target.exists():
                broken.append(href)
        assert broken == [], f"{page}: {broken}"


class TestTheConsentBannerMeetsTheRules:
    def test_reject_is_at_the_first_layer(self):
        """NOT behind "Customise". Regulators require a reject at the
        first layer, and burying it is the specific pattern named in
        enforcement guidance."""
        landing = _text(SITE / "index.html")
        first_layer = landing[landing.index("data-consent "):landing.index("data-consent-panel")]

        assert 'data-consent-action="reject"' in first_layer

    def test_accept_and_reject_carry_the_same_classes(self):
        """Equal prominence, mechanically. `btn--consent` fixes a
        minimum width on both so one cannot shrink."""
        landing = _text(SITE / "index.html")

        for action in ("reject", "accept"):
            i = landing.index(f'data-consent-action="{action}"')
            button = landing[max(0, i - 220):i]
            assert "btn--consent" in button, action

    def test_consent_is_granular(self):
        landing = _text(SITE / "index.html")

        categories = set(re.findall(r'data-consent-category="(\w+)"', landing))

        assert categories == {"analytics", "marketing"}

    def test_necessary_cookies_are_not_offered_as_a_choice(self):
        """Presenting them as optional and then ignoring the answer is
        worse than not asking."""
        landing = _text(SITE / "index.html")
        i = landing.index('id="consent-necessary"')
        control = landing[i - 120:i + 120]

        assert "disabled" in control
        assert "checked" in control

    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_withdrawal_is_on_every_page(self, page):
        """Withdrawal must be as easy as giving. A link in the footer
        of one page is not "every page"."""
        assert "data-consent-reopen" in _text(page), str(page)


class TestTheConsentScript:
    SCRIPT = Path("site/js/consent.js").read_text(encoding="utf-8")

    def test_it_records_when_the_choice_was_made(self):
        """The log is the proof. A stored boolean with no timestamp
        cannot answer "when did they agree"."""
        assert "new Date().toISOString()" in self.SCRIPT

    def test_a_storage_failure_asks_again_rather_than_assuming(self):
        """Private browsing, a full quota, storage switched off. The
        safe direction is to ask; the unsafe one is to treat a failed
        write as consent."""
        # THE CATCH BLOCK SPECIFICALLY. A first version asserted
        # `"return null" in body`, which passed with the catch
        # returning full consent -- because an earlier line in the same
        # function returns null for a different reason. A control
        # caught it; the assertion had been proving nothing.
        i = self.SCRIPT.index("} catch (error) {", self.SCRIPT.index("function stored("))
        catch = self.SCRIPT[i:self.SCRIPT.index("}", i + 20)]

        assert "return null" in catch
        assert "true" not in catch

    def test_changing_the_categories_invalidates_old_consent(self):
        """Consent is specific to what was asked. Adding a category and
        treating last year's answer as covering it is consent for
        something nobody saw."""
        assert "parsed.version === VERSION" in self.SCRIPT

    def test_nothing_may_load_without_asking_first(self):
        """The gate other code is meant to call."""
        assert "window.elysiumConsent" in self.SCRIPT
        assert "allows:" in self.SCRIPT


class TestItLooksLikeTheProduct:
    def test_the_tokens_are_the_product_tokens(self):
        """A prospect clicking through to the demo should not watch the
        colours change. Copied rather than imported, because the site
        has no build step -- so this asserts the copy is current."""
        site_tokens = (SITE / "css/tokens.css").read_text(encoding="utf-8")
        product = Path("ui/packages/shell-api/src/tokens.css").read_text(encoding="utf-8")

        assert site_tokens == product

    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_every_page_uses_them(self, page):
        assert "/css/tokens.css" in _text(page), str(page)


class TestTheBasicsNobodyChecks:
    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_a_title_and_a_description(self, page):
        source = _text(page)

        assert "<title>" in source, str(page)
        assert 'name="description"' in source, str(page)

    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_a_language_and_a_viewport(self, page):
        source = _text(page)

        assert 'lang="en"' in source, str(page)
        assert 'name="viewport"' in source, str(page)

    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_a_skip_link_to_a_target_that_exists(self, page):
        """The first thing a keyboard user meets. A skip link pointing
        at nothing is worse than none, because it looks handled."""
        source = _text(page)

        assert 'class="skip"' in source, str(page)
        assert 'id="main"' in source, str(page)
