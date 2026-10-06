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
            # A CROSS-PAGE ANCHOR like "/#how" points at the homepage,
            # not at this one. The inner pages link back to the
            # homepage's sections so their navigation matches it, and
            # checking those ids against the CURRENT page's would fail
            # every one.
            if "#" in href:
                target_path, _, fragment = href.partition("#")
                target = SITE / (target_path.lstrip("/") or "")
                if target.is_dir() or target_path.endswith("/") or not target_path:
                    target = target / "index.html"
                if not target.exists():
                    broken.append(href)
                elif fragment and f'id="{fragment}"' not in target.read_text(encoding="utf-8"):
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
        band = self.LANDING[max(0, i - 900):i + 300]

        assert "read:Customer.email" in band

    def test_the_snippet_shows_a_refusal_rather_than_a_schema(self):
        """The useful thing to show is not what you can declare -- it
        is two people asking one question and getting different
        answers, with the second told nothing rather than told
        'forbidden'."""
        assert "no customers match" in self.LANDING
        assert "that would tell him" in self.LANDING

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
        for column in ("SOURCES", "BRONZE", "SILVER", "GOLD", "ONTOLOGY"):
            assert column in self.LANDING, column

    def test_the_silos_are_named_as_the_customer_names_them(self):
        """Not "database" -- a silo is a named instance in
        data_silos.yaml, and a deployment spans more than one."""
        assert "primary_sql" in self.LANDING
        assert "risk_db" in self.LANDING
        assert "primary_sql" in self.LANDING and "risk_db" in self.LANDING

    def test_bronze_and_silver_are_one_to_one_with_source_tables(self):
        """Three source tables in, three bronze, three silver. Drawing
        bronze as one box would say Elysium flattens them, which it
        does not."""
        # Each source table appears in bronze and in silver, plus once
        # as a silo caption -- so at least two boxes each.
        assert self.LANDING.count(">customers<") >= 2
        assert self.LANDING.count(">risk_scores<") >= 2

    def test_gold_is_where_the_shape_changes(self):
        """One table per object TYPE rather than per source table, and
        a type joining two silos is the whole reason gold is a separate
        stage."""
        # Gold holds one box per object TYPE, not per source table:
        # three source lanes arrive, two object types leave.
        i = self.LANDING.index(">Transaction<")
        j = self.LANDING.index(">Customer<")
        assert abs(i - j) < 2000, "the two gold types are not adjacent"
        assert self.LANDING.count(">risk_scores<") >= 2

    def test_the_ontology_is_what_a_question_is_asked_against(self):
        assert "Ontology" in self.LANDING
        assert "a question is asked" in self.LANDING

    def test_the_sync_is_said_to_be_read_only(self):
        """The claim a prospect most needs from the picture."""
        assert "only ever reads your databases" in self.LANDING

    def test_it_is_described_for_a_screen_reader(self):
        # THE WHOLE ELEMENT, not a fixed window. A 1800-character slice
        # from the attribute cut the description short once the redraw
        # made it longer, so the test failed on text that was present.
        i = self.LANDING.index('id="arch-desc"')
        description = self.LANDING[i:self.LANDING.index("</desc>", i)]

        assert "bronze" in description
        assert "one table per object type" in description
        assert "never writes to them" in description
        assert len(description) > 500

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

        # NO ARROWHEADS AT ALL NOW, deliberately. The redraw put every
        # source table in its own horizontal lane reading left to
        # right, with one elbow where two lanes join. Direction is
        # carried by the column order and the single turn; a head on
        # every segment was clutter the owner correctly called
        # contrived.
        wires = svg.count('class="wire')

        assert wires >= 6, "the lanes are not drawn"
        assert svg.count("marker-end") == 0, "arrowheads are back"


class TestTheSilosLookLikeDatabases:
    """"Show the data silos as actual recognizable database objects."

    A rectangle labelled primary_sql is a box with a word in it. The
    cylinder is the one shape every reader already knows means
    database, and the platter lines are what make it read at a glance
    rather than after a moment."""

    LANDING = (SITE / "index.html").read_text(encoding="utf-8")

    def test_the_silos_are_drawn_as_cylinders(self):
        assert 'class="cyl"' in self.LANDING
        assert 'class="cyl-top"' in self.LANDING

    def test_they_carry_the_platter_lines(self):
        """Two curved lines inside the body -- the convention that says
        "database" without a label."""
        assert self.LANDING.count('class="cyl-line"') >= 2

    def test_both_silos_are_drawn(self):
        assert self.LANDING.count('class="cyl"') == 2


class TestTheOntologyIsAtTheEnd:
    """"The ontology should be beyond the gold layer, all in line. You
    putting the ontology underneath kinda loses the logic that the
    ontology is the ultimate distillation of the data."

    Right. A band underneath says "and also, separately, there is an
    ontology". At the end of the line it says what is true: everything
    narrows into it."""

    LANDING = (SITE / "index.html").read_text(encoding="utf-8")

    def test_it_is_the_rightmost_thing(self):
        import re

        plain = [float(m) for m in re.findall(r'<rect class="box" x="([\d.]+)"', self.LANDING)]
        onto = float(re.search(r'<rect class="box box--accent" x="([\d.]+)"',
                               self.LANDING).group(1))

        assert onto > max(plain), f"ontology at {onto}, a gold box at {max(plain)}"

    def test_gold_feeds_it(self):
        """The flow has to arrive, or it is just a box on the right."""
        assert self.LANDING.count("wire--in") >= 2


class TestTheFormattingIsSystematic:
    """"The formatting of everything is not adequate."

    The fault was systematic: every size and spacing had been chosen
    individually as each section was written. Ad hoc values are what
    "separates professional layouts from chaotic ones", and adjusting
    them one at a time does not fix it."""

    CSS = (SITE / "css/site.css").read_text(encoding="utf-8")

    def test_there_is_one_type_scale(self):
        """A modular scale of 1.25 from a 17px base. Nothing may use a
        size outside it."""
        # THE DECLARATION, not any mention. A control deleted the
        # `--t-base:` line and this passed, because `var(--t-base)`
        # still appears wherever it is used -- the test was checking
        # that something referred to the step, not that the step
        # existed.
        for step in ("--t-xs:", "--t-sm:", "--t-base:", "--t-md:", "--t-lg:",
                     "--t-xl:", "--t-3xl:"):
            assert step in self.CSS, step

    def test_there_is_one_spacing_unit(self):
        """8px, everything a multiple -- which is what makes blocks line
        up without anybody aligning them."""
        for step in ("--s-1:", "--s-2:", "--s-4:", "--s-8:", "--s-16:"):
            assert step in self.CSS, step

    def test_the_measure_is_in_the_readable_range(self):
        """45 to 75 characters, "65 being the widely cited sweet spot".
        At 17px, 34rem is about 65."""
        import re

        measure = re.findall(r"--measure: ([\d.]+)rem", self.CSS)[-1]

        assert 28 <= float(measure) <= 40, f"{measure}rem is outside 45-75 characters"

    def test_headings_are_set_tighter_than_body(self):
        """1.1 to 1.3 for headings, 1.5 to 1.6 for body. A heading set
        at body leading looks like a paragraph in bold."""
        # THE TYPE-SCALE BLOCK, not the last `h1 {` in the file --
        # `rindex` found `.hero h1 { max-width }`, which sets no
        # leading at all, so the assertion was testing the wrong rule.
        i = self.CSS.index("h1 {", self.CSS.index("--t-3xl:"))
        h1 = self.CSS[i:self.CSS.index("}", i)]

        assert "line-height: 1.0" in h1 or "line-height: 1.1" in h1, h1


class TestTheProofIsReal:
    """Every guide says to put customer logos above the fold. Elysium
    has no customers, and a row of invented logos on a page selling
    access control would be the single most expensive lie available.

    THE FIRST ANSWER WAS ALSO WRONG. I put repository facts there --
    unit tests, tracked audit findings, CI controls -- which the owner
    correctly said clients could not care less about. They are an
    engineer's pride, not a buyer's question.

    AND THIS CLASS WENT MISSING. An earlier rewrite of the file dropped
    it entirely, so the page ran with no guard on its claims at all
    until a green suite looked wrong and I checked. A test file that
    loses a class silently is the same failure as a guard wired to
    nothing."""

    LANDING = (SITE / "index.html").read_text(encoding="utf-8")

    def test_no_customer_logos_and_no_invented_counts(self):
        lowered = self.LANDING.lower()

        for claim in ("trusted by", "customers worldwide", "fortune 500",
                      "join thousands", "capterra"):
            assert claim not in lowered, claim

    def test_the_proof_is_architectural_not_repository_trivia(self):
        i = self.LANDING.index('class="proof"')
        row = self.LANDING[i:self.LANDING.index("</dl>", i)].lower()

        for engineerly in ("tests", "commits", "coverage", "controls",
                           "audit findings"):
            assert engineerly not in row, engineerly

    def test_it_says_the_four_things_a_buyer_asks(self):
        i = self.LANDING.index('class="proof"')
        row = self.LANDING[i:self.LANDING.index("</dl>", i)]

        for claim in ("leave your silos", "Per field", "Read-only", "One tenant"):
            assert claim in row, claim

    def test_each_claim_is_true_of_the_code(self):
        """Why these are safe to print: each maps to something the
        repository enforces, so a change falsifying one would break a
        test in Elysium's own suite long before anybody read this
        page."""
        repo = SITE.parent

        assert "ExternalReadAdapter" in (repo / "core/ontology/interface.py").read_text()
        assert "read:Transaction.amount" in (repo / "deployment/etc/policy.yaml").read_text()


class TestTheCallToActionIsLegible:
    """IT RENDERED GREY ON BLUE -- the one element on the page that had
    to be readable.

    `.masthead nav a` is specificity 0-1-2 and `.btn--primary` is
    0-1-0, so the nav's muted grey won over the button's own colour
    REGARDLESS of source order. Not a mistake anyone sees by reading
    the file top to bottom.

    Fixed by scoping the nav rule to links that are NOT buttons rather
    than raising the button's specificity -- an arms race between two
    selectors is how this happens a second time."""

    CSS = (SITE / "css/site.css").read_text(encoding="utf-8")

    def test_the_nav_rule_excludes_buttons(self):
        assert ".masthead nav a:not(.btn)" in self.CSS

    def test_no_bare_nav_colour_rule_remains(self):
        """The one that caused it. A bare `.masthead nav a { color }`
        would win again."""
        import re

        bare = re.search(r"\.masthead nav a \{[^}]*color:", self.CSS)

        assert bare is None, bare.group(0) if bare else ""

    def test_the_primary_button_states_its_own_colour(self):
        i = self.CSS.rindex(".btn--primary,")
        rule = self.CSS[i:self.CSS.index("}", i)]

        assert "color: #05080e" in rule
        assert "background: var(--accent)" in rule


class TestTheNavigationIsNotRedundant:
    LANDING = (SITE / "index.html").read_text(encoding="utf-8")

    def test_the_bare_demo_link_is_gone(self):
        """A "Demo" text link beside a "Try the demo" button is two
        controls for one action, and the research is explicit that a
        second CTA competing in the hero costs conversions."""
        i = self.LANDING.index("<nav")
        nav = self.LANDING[i:self.LANDING.index("</nav>")]

        assert nav.count('href="/demo/"') == 1


class TestAlignmentVariesBySection:
    """"It's all left-aligned, and doesn't look appealing."

    The fix is NOT centring the body text -- "left aligned text is
    easier to read than centered text for paragraphs", because
    centring moves the start of every line and leaves "no consistent
    place where users can move their eyes to".

    The real fault was that every section was identical: same edge,
    same width, same shape, top to bottom. "Breaking alignment
    intentionally draws attention -- if every element sits along the
    same left edge except one, that outlier becomes the focal
    point.
    """

    LANDING = (SITE / "index.html").read_text(encoding="utf-8")
    CSS = (SITE / "css/site.css").read_text(encoding="utf-8")

    def test_the_right_half_of_the_page_is_not_empty(self):
        """THE ACTUAL COMPLAINT, which I twice misread as a text-align
        question: "the whole text of the site is hugging the left side,
        where the right side looks barren".

        Measured at the time: a 78rem container holding a 34rem
        measure, with nothing in the other 44rem. The text was
        correctly left-aligned throughout -- there was simply no second
        column, so every block sat alone in a frame twice its width.

        Sections are two columns now: what this section is on the left,
        the thing itself on the right."""
        assert "band" in self.LANDING
        assert 'class="band__head"' in self.LANDING
        assert 'class="band__body"' in self.LANDING

    def test_the_hero_fills_the_frame(self):
        """The first screen was the worst of it -- a headline and one
        paragraph in the left third."""
        assert 'class="hero__aside"' in self.LANDING

    def test_the_container_is_not_far_wider_than_the_measure(self):
        """78rem around a 34rem measure leaves 44rem of nothing. The
        container came in to 64rem and the diagram breaks out on its
        own instead."""
        import re

        column = float(re.findall(r"--column: ([\d.]+)rem", self.CSS)[-1])
        measure = float(re.findall(r"--measure: ([\d.]+)rem", self.CSS)[-1])

        assert column - measure <= 32, (
            f"{column - measure:.0f}rem of the frame has nothing in it")

    def test_a_centred_head_centres_its_lede_too(self):
        """"A centered headline should not go with a left aligned
        paragraph" -- the paragraph's ragged lines make the heading
        look off-centre."""
        i = self.CSS.index(".section-head--centre p,")
        rule = self.CSS[i:self.CSS.index("}", i)]

        assert "margin-inline: auto" in rule

    def test_the_page_alternates_rather_than_repeats(self):
        """Hero puts copy left and the visual right; the split below
        reverses it with the code on the left. Two identical layouts in
        a row is what made the page read as one long column."""
        assert 'class="split"' in self.LANDING
        assert ".split {" in self.CSS

    def test_body_text_is_never_centred(self):
        """The rule that does not bend. Centring is for short headings
        and calls to action only."""
        import re

        for block in re.findall(r"\.(?:tile|snippet|split__aside)[^{]*\{[^}]*\}", self.CSS):
            assert "text-align: center" not in block, block[:80]


class TestTheMark:
    """A bee skep: coiled straw bands, a small crown, an entrance arch.

    The first attempt tapered linearly and read as a pagoda -- a stack
    of pancakes rather than a dome. A skep is close to a paraboloid:
    near-vertical for the bottom third, then turning over. The profile
    is generated from that curve rather than drawn by hand, which is
    why the coils narrow smoothly instead of in steps somebody chose.

    FIVE FILES, TWO JOBS. The clean mark is the professional one and
    the favicon; the glitched one carries the character. A 16px browser
    tab cannot hold a three-coil slip, so a single form doing both jobs
    would do one of them badly."""

    MARKS = ("logo.svg", "logo-light.svg", "logo-dark.svg",
             "logo-glitch-light.svg", "logo-glitch-dark.svg")

    def test_every_variant_exists(self):
        for name in self.MARKS:
            assert (SITE / "img" / name).exists(), name

    def test_there_is_a_light_and_a_dark_of_each(self):
        """Off-white on navy, or navy on off-white. Both, for both
        forms, so neither ground needs an inverted copy made by hand."""
        for form in ("logo", "logo-glitch"):
            light = (SITE / f"img/{form}-light.svg").read_text(encoding="utf-8")
            dark = (SITE / f"img/{form}-dark.svg").read_text(encoding="utf-8")

            assert "#080c14" in light and "#f7f6f3" in light, f"{form}-light"
            assert "#f7f6f3" in dark and "#080c14" in dark, f"{form}-dark"

    def test_the_glitch_changes_colour_and_not_shape(self):
        """THE BRIEF, AND A CORRECTION. The first version slipped three
        coils sideways, which changes the silhouette -- the owner asked
        instead for "glitches that still preserve the shape of the
        skep, just changing the coloring".

        So the coils are byte-identical between the two files and the
        glitch is three thin slices painted across a clip path cut from
        the silhouette. The outline cannot move, because it is the same
        geometry."""
        import re

        clean = (SITE / "img/logo-dark.svg").read_text(encoding="utf-8")
        glitch = (SITE / "img/logo-glitch-dark.svg").read_text(encoding="utf-8")

        def coils(svg):
            return re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="[\d.]+" height="[\d.]+"', svg)

        assert coils(clean), "no coils found"
        assert coils(glitch)[:len(coils(clean))] == coils(clean), "the shape moved"
        assert "clipPath" in glitch
        assert "clipPath" not in clean

    def test_the_glitch_is_light(self):
        """Three slices, each about half a coil's height. An earlier
        version used nine-pixel slices in the background colour, which
        cut holes and read as damage rather than as style."""
        import re

        glitch = (SITE / "img/logo-glitch-dark.svg").read_text(encoding="utf-8")
        slices = re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="[\d.]+" '
                            r'height="([\d.]+)" fill="(#[0-9a-f]{6})"', glitch)

        assert len(slices) == 3, f"{len(slices)} slices"
        assert all(float(h) <= 6 for h, _ in slices), slices
        assert {c for _, c in slices} == {"#4d8dff"}, "a slice is not the accent"

    def test_it_reads_as_a_dome_not_a_cone(self):
        """The fault in the first attempt, pinned. A skep is still
        nearly full width a third of the way up and narrows sharply
        near the crown; a cone narrows evenly."""
        import re

        clean = (SITE / "img/logo-dark.svg").read_text(encoding="utf-8")
        widths = [float(w) for w in
        # THE CLASS IS GONE from the markup: the coils are plain rects
        # inside one filled group now, which is smaller and lets the
        # clip path reuse them. This read a `class="band"` that no
        # longer exists and matched nothing, so the test raised
        # IndexError instead of failing with a reason.
                  re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="([\d.]+)"', clean)]

        # THE THRESHOLDS WERE FROM THE WRONG SHAPE. This demanded a top
        # coil under 35% of the base, which is a tepee. The sources are
        # consistent that a skep is "the shape of a thimble or an
        # upside-down flowerpot, with a rounded top", "wider at the
        # bottom than the top" -- so the top coil is around two thirds
        # of the base and a separate rounded cap closes it.
        third = widths[len(widths) // 3] / widths[0]
        # widths[-1], not [-2]. The cap is a <path>, not a rect, so it
        # is not in this list at all -- the last rect IS the top coil.
        top_coil = widths[-1] / widths[0]

        assert third > 0.9, f"too conical: {third:.2f} of base width a third up"
        assert 0.5 < top_coil < 0.8, f"not a thimble: top coil is {top_coil:.2f} of the base"
        assert "a 36 " in clean or "a 36." in clean, "the rounded cap is missing"

    def test_the_mark_is_in_the_masthead_of_every_page(self):
        for page in PAGES:
            source = _text(page)

            assert "logo-dark.svg" in source, str(page)
            assert 'rel="icon"' in source, str(page)


class TestWhereTheMarkGoes:
    """TOP-LEFT OF THE HEADER, LINKED HOME. The research is unanimous
    and quantified: Nielsen Norman measured an 89% higher brand recall
    for a top-left mark than a top-right one, and 96% of users reached
    the homepage in one click when it sat there. Centred, people found
    the homepage about six times harder to get back to.

    So the header is the conventional arrangement rather than an
    experiment -- mark and wordmark left, navigation centre-right, the
    call to action hard right where "users often look to the end of
    menus for action links".

    REPEATED IN THE FOOTER, the standard secondary placement, and there
    WITHOUT the wordmark: a reader who has got that far knows the name,
    so the mark alone is the stronger move."""

    LANDING = (SITE / "index.html").read_text(encoding="utf-8")

    def test_the_mark_is_the_first_thing_in_the_header(self):
        header = self.LANDING[self.LANDING.index("<header"):
                              self.LANDING.index("</header>")]
        mark = header.index("logo-dark.svg")
        nav = header.index("<nav")

        assert mark < nav, "the navigation comes before the mark"

    def test_it_links_to_the_homepage(self):
        """96% of users reached home in one click when it did. A mark
        that is not a link is furniture."""
        i = self.LANDING.index('class="wordmark"')
        anchor = self.LANDING[i - 60:i + 60]

        assert 'href="/"' in anchor

    def test_the_call_to_action_is_the_last_thing_in_the_header(self):
        header = self.LANDING[self.LANDING.index("<header"):
                              self.LANDING.index("</header>")]

        assert header.rindex("btn--primary") > header.rindex("logo-dark.svg")

    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_the_footer_repeats_it_without_the_wordmark(self, page):
        source = _text(page)
        i = source.index('class="footer"')
        footer = source[i:]

        assert "footer__mark" in footer, str(page)
        assert "<img" in footer, str(page)

    def test_the_header_uses_the_clean_mark_not_the_glitched_one(self):
        """The glitch is for places the brand is being SHOWN -- a title
        card, a deck, social. The header is somewhere people look fifty
        times a session to find their way home, and furniture should
        not flicker."""
        header = self.LANDING[self.LANDING.index("<header"):
                              self.LANDING.index("</header>")]

        assert "logo-glitch" not in header

    def test_both_grounds_are_still_shipped(self):
        """The site is dark, so it uses the off-white-on-navy mark. The
        navy-on-off-white one exists for everywhere the site is not:
        a letterhead, a slide, a printed page."""
        assert (SITE / "img/logo-light.svg").exists()
        assert (SITE / "img/logo-dark.svg").exists()


class TestTheTrustCentre:
    """The highest-value page on the site for a product that sells
    access control, and it was 160 words of apology for three patches.

    EVERY CLAIM ON IT IS A PROPERTY OF THE CODE, checked here against
    the repository rather than trusted. A trust page that drifts from
    what the software does is worse than no trust page."""

    PAGE = (SITE / "trust/index.html").read_text(encoding="utf-8")

    def test_it_is_no_longer_a_placeholder(self):
        assert "NOT YET WRITTEN" not in self.PAGE
        assert len(self.PAGE.split()) > 500

    def test_the_read_only_claim_matches_the_code(self):
        interface = (SITE.parent / "core/ontology/interface.py").read_text(encoding="utf-8")

        assert "Reads cannot write" in self.PAGE
        assert "class ExternalReadAdapter(ReadAdapter)" in interface

    def test_the_per_field_claim_matches_the_policy(self):
        policy = (SITE.parent / "deployment/etc/policy.yaml").read_text(encoding="utf-8")

        assert "read:Customer.email" in self.PAGE
        assert "read:" in policy and "." in policy

    def test_the_secrets_claim_matches_the_code(self):
        """"A plaintext password in a config file is rejected at load
        rather than warned about" -- there is a specific exception for
        it, which is the difference between a claim and a feature."""
        secrets = (SITE.parent / "core/secret_references.py").read_text(encoding="utf-8")

        assert "Credentials are never in config" in self.PAGE
        assert "class PlaintextSecret" in secrets

    def test_it_claims_no_certification_it_does_not_have(self):
        """THE STANDARD IS "DO NOT CLAIM WHAT IS NOT TRUE", NOT
        "ENUMERATE WHAT IS MISSING".

        This test used to require the page to list its own absent
        certifications -- no SOC 2, no penetration test, no ISO 27001 --
        which no company publishes and which made the site read as an
        apology. The owner was right to call it out.

        What actually matters is the opposite direction: an unearned
        badge is a lie a buyer can act on. So the page may say nothing
        about SOC 2, and may not say it has one."""
        lowered = self.PAGE.lower()

        for unearned in ("soc 2 certified", "soc 2 type ii", "iso 27001 certified",
                         "iso 27001 compliant", "hipaa compliant", "fedramp",
                         "pci dss compliant", "penetration tested by"):
            assert unearned not in lowered, unearned

    def test_it_offers_a_route_for_security_questions(self):
        """What a trust centre is FOR. A buyer with a questionnaire
        needs somewhere to send it; "we have nothing" is not an answer
        and neither is silence."""
        assert "on request" in self.PAGE
        assert "data processing agreement" in self.PAGE.lower()

    def test_it_is_honest_about_the_language_model(self):
        """The one place data can leave the customer's network. Omitting
        it would make every other claim on the page suspect."""
        assert "hosted model" in self.PAGE
        assert "local model sends nothing" in self.PAGE


class TestTheSiteIsFoundAndShared:
    """A link to this site pasted into Slack, LinkedIn or a DM rendered
    as a bare URL -- no title, no description, no image. That is the
    first thing a prospect sees, before the site itself."""

    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_every_page_has_a_share_card(self, page):
        source = _text(page)

        for tag in ("og:title", "og:description", "og:image",
                    "twitter:card", 'rel="canonical"'):
            assert tag in source, f"{page}: {tag}"

    @pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p))
    def test_the_share_title_matches_the_page_title(self, page):
        """A card that says something different from the page is worse
        than no card."""
        import re

        source = _text(page)
        title = " ".join(re.search(r"<title>(.*?)</title>", source, re.S).group(1).split())
        og = re.search(r'property="og:title" content="(.*?)"', source, re.S).group(1)

        assert og == title, f"{page}: {og!r} vs {title!r}"

    def test_the_share_card_image_exists(self):
        assert (SITE / "img/share-card.svg").exists()

    def test_there_is_a_sitemap_and_it_lists_every_page(self):
        sitemap = (SITE / "sitemap.xml").read_text(encoding="utf-8")

        for page in PAGES:
            path = "/" + str(page.relative_to(SITE)).replace("index.html", "")
            # THE 404 IS THE ONE EXCLUSION. A search result pointing at
            # a "page not found" is the clearest signal nobody is
            # maintaining a site, so it carries `noindex` and stays out
            # of the sitemap rather than being listed and ignored.
            if path == "/404/":
                assert 'content="noindex"' in _text(page)
                continue
            assert path in sitemap, path

    def test_there_is_a_security_contact(self):
        """Conspicuous by its absence on a security product. RFC 9116
        asks for a Contact and an Expires field."""
        security = (SITE / ".well-known/security.txt").read_text(encoding="utf-8")

        assert "Contact:" in security
        assert "Expires:" in security

    def test_the_model_summary_claims_nothing_unearned(self):
        """llms.txt is what a model repeats to a buyer who asks about
        Elysium before visiting. It must not invent certifications --
        and equally must not volunteer a list of what is missing, which
        is what it used to do."""
        summary = (SITE / "llms.txt").read_text(encoding="utf-8").lower()

        for unearned in ("soc 2 certified", "iso 27001", "hipaa", "fedramp"):
            assert unearned not in summary, unearned

        assert "do not state or imply certifications" in summary


class TestTheLegalPagesAreTrue:
    """Drafted in-house for a pre-customer test site, which is a
    reasonable thing to do and a dangerous thing to leave unchecked.

    THE RISK IS NOT THAT THEY ARE BADLY WRITTEN. It is that they stop
    being TRUE: a privacy notice saying "no analytics" survives the
    commit that adds analytics, because nobody rereads it. These tests
    tie each factual claim to something checkable in the site."""

    PRIVACY = (SITE / "legal/privacy/index.html").read_text(encoding="utf-8")
    TERMS = (SITE / "legal/terms/index.html").read_text(encoding="utf-8")

    def test_neither_page_undercuts_itself(self):
        """THIS TEST USED TO REQUIRE THE OPPOSITE. It asserted both
        pages carried "drafted in-house, not reviewed by a lawyer" --
        a sentence no company publishes, which turned a legal notice
        into an apology.

        The standard is that the pages must not claim false things, not
        that they must advertise their own provenance. What follows
        still ties every factual claim to something checkable."""
        for name, page in (("privacy", self.PRIVACY), ("terms", self.TERMS)):
            assert "not reviewed by a lawyer" not in page, name
            assert "pre-customer" not in page.lower(), name

    def test_the_no_analytics_claim_is_still_true(self):
        """The claim most likely to rot. If any page gains a script
        beyond the consent one, or a third-party host appears, this
        fails and the notice has to be rewritten before the tag
        ships."""
        assert "no analytics" in self.PRIVACY.lower()

        for page in PAGES:
            source = _text(page)
            assert source.count("<script") <= 1, f"{page} has extra scripts"
            for host in ("google-analytics", "googletagmanager", "plausible",
                         "segment.com", "hotjar", "mixpanel"):
                assert host not in source, f"{page}: {host}"

    def test_the_no_forms_claim_is_still_true(self):
        """"No form on this site that accepts personal data." The demo
        signup, when it exists, falsifies this -- which is the point of
        checking."""
        # COMPARE COLLAPSED TEXT. The claim is wrapped across lines in
        # the page, so a substring match on the raw file finds nothing.
        flat = " ".join(self.PRIVACY.split()).lower()

        assert "no form on this site accepts personal data" in flat

        for page in PAGES:
            source = _text(page)
            assert "<form" not in source, f"{page} has a form"
            assert 'type="email"' not in source, f"{page} collects an email"

    def test_the_storage_key_it_names_is_the_real_one(self):
        """A privacy notice naming a key that does not exist is worse
        than one naming none."""
        import re

        script = (SITE / "js/consent.js").read_text(encoding="utf-8")
        key = re.search(r"KEY = '([^']+)'", script).group(1)

        assert key in self.PRIVACY, f"the notice does not name {key}"

    def test_the_terms_defer_to_the_licence_and_the_code(self):
        """Two things that must stay said: the software has its own
        licence, and where the site and the code disagree the code
        wins. Both stop this page overreaching."""
        assert "under its own licence" in self.TERMS
        flat = " ".join(self.TERMS.split())

        assert "the software governs" in flat

    def test_they_point_at_the_trust_centre_for_substance(self):
        """Neither page should become the place where security claims
        live -- those belong somewhere that is tested against the
        code."""
        assert 'href="/trust/"' in self.PRIVACY
        assert 'href="/trust/"' in self.TERMS

    def test_only_the_demo_page_is_still_unwritten(self):
        """THE DEMO IS THE HONEST EXCEPTION. It describes an instance
        that does not exist yet, and a page inventing one would be the
        worst lie on the site. Every other page is written, and this
        asserts the list of exceptions is exactly one -- so a future
        placeholder cannot slip in unnoticed."""
        unwritten = [str(page.relative_to(SITE)) for page in PAGES
                     if "NOT YET WRITTEN" in _text(page)]

        assert unwritten == ["demo/index.html"], unwritten
