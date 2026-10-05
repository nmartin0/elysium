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

SITE = Path(__file__).resolve().parent.parent
PAGES = sorted(p for p in SITE.rglob("*.html") if "tests" not in p.parts)


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
    SCRIPT = (SITE / "js/consent.js").read_text(encoding="utf-8")

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


class TestItIsTheSiteForElysiumNotElysium:
    def test_it_carries_nothing_of_elysiums_own_gates(self):
        """THE WEBSITE TAKES RESPONSIBILITY FOR ITSELF.

        These tests lived in Elysium's tests/unit/ and its HTMLParser
        override needed a line in Elysium's vulture whitelist -- so a
        typo in a headline could fail the product's suite, and the
        product carried configuration that existed only for a web page.

        They run from here now, through site/check.sh. This asserts the
        product has not been handed anything back."""
        repo = SITE.parent

        assert not (repo / "tests/unit/test_the_marketing_site_is_sound.py").exists()
        assert "handle_starttag" not in (repo / "vulture_whitelist.py").read_text()
        assert (SITE / "check.sh").exists()

    def test_the_site_owns_its_palette(self):
        """NOT A COPY OF THE PRODUCT'S, and this test used to assert
        the opposite. Enforcing byte-equality with
        ui/packages/shell-api/src/tokens.css meant a colour change in
        the application broke the marketing site -- a coupling between
        two things that are meant to be separable, whatever the
        directory layout says.

        The VALUES still match, because a prospect clicking into the
        demo should not watch the colours change. They match by being
        chosen to."""
        site_tokens = (SITE / "css/tokens.css").read_text(encoding="utf-8")

        assert "--blue-400" in site_tokens
        assert "@layer" not in site_tokens, "product cascade detail does not belong here"

    def test_nothing_under_site_reaches_into_the_product(self):
        """The isolation, asserted rather than assumed. A relative path
        out of this directory, or a reference to ui/ or core/, would
        mean the site cannot be moved or deployed on its own."""
        # LINKS AND IMPORTS, not prose. A first version grepped the
        # raw text and failed on its own explanatory comments, which
        # name `ui/packages/shell-api` precisely to say the site no
        # longer copies from it. What matters is whether anything
        # RESOLVES outside this directory.
        # THE SERVED FILES ONLY. `rglob("*")` picked up this test's
        # own __pycache__ and died on a binary -- the test moved INTO
        # the directory it inspects, which is the right place for it
        # and one more thing to skip.
        reaching = []
        for path in SITE.rglob("*"):
            if not path.is_file() or path.suffix not in {".html", ".css", ".js"}:
                continue
            source = path.read_text(encoding="utf-8")
            for match in re.findall(r'(?:href|src)="([^"]+)"', source):
                if match.startswith("../") or match.startswith("ui/"):
                    reaching.append(f"{path}: {match}")
            for match in re.findall(r"@import\s+[\"']([^\"']+)", source):
                if match.startswith(".."):
                    reaching.append(f"{path}: {match}")

        assert reaching == [], reaching

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


class TestItIsAboutElysiumSpecifically:
    """The first version of this page could have described any data
    tool: three cards saying "fast", "secure", "live". The owner's
    words were that it was "its own thing", not Elysium.

    What makes it Elysium is the ONTOLOGY -- a declared YAML file that
    is the whole interface -- and a write being a PROPOSAL a person
    approves. Both are now on the page as the thing itself rather than
    a claim about it, and these tests stop that drifting back."""

    LANDING = (SITE / "index.html").read_text(encoding="utf-8")

    def test_the_ontology_is_shown_not_described(self):
        """A prospect for this product wants to see the YAML, not a
        paragraph about how declarative it is."""
        assert "object_types:" in self.LANDING
        assert "id_field:" in self.LANDING
        assert "security:" in self.LANDING

    def test_the_security_field_is_what_is_highlighted(self):
        """Of everything in that fragment, the line that distinguishes
        Elysium from a schema file is the one naming who may see a
        row."""
        i = self.LANDING.index("object_types:")
        snippet = self.LANDING[i:i + 900]

        assert "<b>security:" in snippet

    def test_the_approval_flow_is_shown(self):
        """A write being a proposal somebody approves, with the
        APPROVER's grants re-checked, is the other thing only this
        product does."""
        assert "PROPOSED" in self.LANDING
        assert "APPROVED" in self.LANDING
        assert "re-checked" in self.LANDING

    def test_no_syntax_highlighting_library(self):
        """Forty kilobytes to colour nine lines, on the page that must
        load fastest. The two things worth an eye are marked in the
        markup."""
        for page in PAGES:
            source = _text(page)
            assert "prism" not in source.lower(), str(page)
            assert "highlight.js" not in source.lower(), str(page)

    def test_it_says_what_the_model_cannot_do(self):
        """The product's claim is negative -- the model never gets
        database access and is never trusted to judge what it may see.
        A page that only lists capabilities is selling a chatbot."""
        assert "never" in self.LANDING.lower()
