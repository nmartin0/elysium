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

        assert "--navy-950" in site_tokens
        assert "--bone-50" in site_tokens
        assert "@layer" not in site_tokens, "product cascade detail does not belong here"

    def test_there_is_exactly_one_accent(self):
        """ONE ACCENT, SPENT CAREFULLY. The sites in this category that
        read as serious hold near-monochrome and let "the only colour
        contribution come from their products"."""
        css = (SITE / "css/site.css").read_text(encoding="utf-8")
        default = css[css.index(":root {"):css.index("}", css.index(":root {"))]

        assert default.count("--accent:") == 1, "one accent, spent carefully"

    def test_it_is_dark_with_no_escape_hatch(self):
        """IT SHIPPED LIGHT TWICE after I twice said it was fixed.

        The first time, three competing `:root` blocks and the last
        match won. The second time the blocks were right and a
        `prefers-color-scheme: light` query flipped the whole site on a
        light-mode machine -- which is what the owner kept seeing.

        "Dark by default" meant the site is dark, not "dark unless your
        laptop says otherwise". The product carries both schemes
        because people live in it all day; a landing page is read once
        and gets one treatment, chosen."""
        css = (SITE / "css/site.css").read_text(encoding="utf-8")
        rules = [line for line in css.splitlines()
                 if line.strip().startswith("@media") and "color-scheme" in line]

        assert rules == [], rules
        assert "color-scheme: dark" in css

    def test_the_page_has_proportion(self):
        """"All left aligned and doesn't look like it has any sort of
        padding" -- both true, and the same mistake: everything pinned
        to one left edge at full column width, which reads as a
        document rather than a designed page.

        The fix is the two moving in opposite directions: a WIDER
        column and a NARROWER measure, with a band between sections
        large enough to feel slightly too generous while writing
        it."""
        css = (SITE / "css/site.css").read_text(encoding="utf-8")

        assert "--band:" in css
        assert "--measure:" in css
        assert "--gutter: clamp(" in css

    def test_something_breaks_the_left_edge_deliberately(self):
        """A page entirely left-aligned has no rhythm; one that centres
        everything has no spine. Two bands break it completely -- the
        diagram, full width, and the closing call, centred."""
        css = (SITE / "css/site.css").read_text(encoding="utf-8")

        assert ".closer {" in css
        assert "text-align: center" in css
        assert "margin-inline: auto" in css


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

    def test_the_ontology_is_shown_in_the_diagram(self):
        """IT MOVED, and the move was the point. A YAML fragment listing
        field types is true and dull -- the owner's words were that the
        examples highlighted "insignificant parts".

        The ontology now appears in the diagram, where it can be shown
        sitting ON something: object types with their links, the grant
        each field needs, and the security rule set apart."""
        assert "Ontology" in self.LANDING
        assert "security" in self.LANDING
        assert "Customer" in self.LANDING and "Transaction" in self.LANDING

    def test_the_security_rule_is_named_in_the_ontology_band(self):
        """Of everything in an ontology, the line that distinguishes it
        from a schema file is the one naming who may see a row. It is
        named in the band, beside the field-level grant."""
        i = self.LANDING.index("security: region")
        band = self.LANDING[max(0, i - 700):i + 200]

        assert "read:Customer.email" in band
        assert "never the model" in band

    def test_the_snippet_shows_a_refusal_rather_than_a_schema(self):
        """The useful thing to show is not what you can declare -- it
        is two people asking one question and getting different
        answers, with the second told nothing rather than told
        'forbidden'."""
        assert "no customers match" in self.LANDING
        assert "that would tell bob they exist" in self.LANDING

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


class TestTheDiagram:
    """The hero image, and it had to be rebuilt from the code rather
    than from a mental model of a generic data lake.

    WHAT ELYSIUM ACTUALLY DOES, read out of core/mirror/ and
    data_silos.yaml:

      SILOS    the customer's own databases, named in
               data_silos.yaml. Each object type says which silo it
               lives in, so a deployment can span several.
      BRONZE   one Iceberg table per REAL SOURCE TABLE, 1:1,
               "ingest as-is, with no external preprocessing".
      SILVER   the SAME tables at the source's grain with the
               source's column names, typed and standardised.
      GOLD     THE SHAPE CHANGES. One table per OBJECT TYPE, keyed
               by the object's id, using the ONTOLOGY'S property
               names, JOINING the storages a type spans.
      ONTOLOGY what a question is asked against; reads gold.

    So the picture is a narrowing: three source tables across two
    silos become two object types. My previous version drew three
    equal stacked slabs, which said none of that."""

    LANDING = (SITE / "index.html").read_text(encoding="utf-8")

    def test_the_four_columns_are_named(self):
        for column in ("YOUR SILOS", "BRONZE", "SILVER", "GOLD"):
            assert column in self.LANDING, column

    def test_the_silos_are_named_as_the_customer_names_them(self):
        """Not "database" -- a silo is a named instance in
        data_silos.yaml, and a deployment spans more than one."""
        assert "primary_sql" in self.LANDING
        assert "risk_db" in self.LANDING
        assert "data_silos.yaml" in self.LANDING

    def test_bronze_and_silver_are_one_to_one_with_source_tables(self):
        """Three source tables in, three bronze, three silver. Drawing
        bronze as one box would say Elysium flattens them, which it
        does not."""
        assert self.LANDING.count(">customers<") >= 3
        assert self.LANDING.count(">risk_scores<") >= 3

    def test_gold_is_where_the_shape_changes(self):
        """One table per object TYPE rather than per source table, and
        a type joining two silos is the whole reason gold is a separate
        stage."""
        assert "one table per object type" in self.LANDING
        assert "joined from 2 silos" in self.LANDING

    def test_the_ontology_sits_above_gold_and_is_what_is_asked(self):
        assert "Ontology — object types, fields, links" in self.LANDING
        assert "a question is asked against this" in self.LANDING

    def test_the_sync_is_said_to_be_read_only(self):
        """The claim a prospect most needs from the picture."""
        assert "only ever READS your silos" in self.LANDING

    def test_it_is_described_for_a_screen_reader(self):
        i = self.LANDING.index('id="arch-desc"')
        description = self.LANDING[i:i + 1800]

        assert "bronze" in description
        assert "one table per object type" in description
        assert len(description) > 600

    def test_it_is_inlined_rather_than_an_img(self):
        assert "<svg" in self.LANDING
        assert "architecture.svg" not in self.LANDING

    def test_no_gradients_blurs_or_fake_depth(self):
        """What reads as generated: gradient fills everywhere, blur
        standing in for depth, translucency faking light."""
        i = self.LANDING.index("<svg")
        svg = self.LANDING[i:self.LANDING.index("</svg>")]

        for tell in ("linearGradient", "radialGradient", "feGaussianBlur",
                     "filter=", "fill-opacity"):
            assert tell not in svg, tell

    def test_every_wire_has_a_direction(self):
        """A flow diagram without arrowheads is a parts list."""
        i = self.LANDING.index("<svg")
        svg = self.LANDING[i:self.LANDING.index("</svg>")]

        wires = svg.count('class="wire')
        arrows = svg.count("marker-end")

        assert wires > 0
        assert arrows >= wires
