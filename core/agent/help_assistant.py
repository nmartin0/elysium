"""The help assistant: questions about using Elysium, answered for the
person asking (BLOCKING.md's help-assistant item, wanted by the owner on
2026-10-12).

WHAT IT ANSWERS. "How do I filter Browse by region?", "Why can't I see
salary?", "What is the Approvals screen for?", "Which kinds of object
can I look at?" -- questions about the PRODUCT, as this caller
experiences it. Not questions about the data: those are what Query is
for, and this assistant has no data to answer them from.

THE SHAPE WAS DECIDED ON 5 OCTOBER, before it was wanted: it answers
from `visible_schema` and the caller's own grants -- not from the
repository's documentation, and not from `config`. The precedent is
blunt about the alternative: assistants that "tried (and failed) to
mirror or enforce fine-grained enterprise permissions". This one never
has to enforce anything, because NOTHING IT IS GIVEN IS SOMETHING THE
CALLER MAY NOT KNOW:

  - the screens they can open (api/apps.visible_apps_for -- the same
    list the navigation rail shows them);
  - the object types and fields their visible schema includes, with
    whether each field's VALUE is readable -- names and types, never a
    value, because a help answer must not become a second read path;
  - their own role's grants, which describe them.

What it could leak is therefore bounded by what the caller can already
see, which is the precedent's warning answered rather than noted: an
assistant "doesn't bypass permissions", but "amplifies whatever the
grants already allow". It is built ON the existing checks, not beside
them.

ONE CALL, NO TOOLS. It reads nothing at answer time, so a crafted
question has nothing to steer it towards.

THE SCREEN GUIDE IS PRODUCT KNOWLEDGE, in code, kept short and true to
the interface as built. It is the one part a change to the interface
can make wrong, which is why every screen's entry names controls by the
labels they carry on screen -- a test checks those labels exist in ui/.
"""

from collections.abc import Mapping

#: What each screen is for and how it is used, by its name in the rail.
#: Only the screens a caller can open are ever put in front of the model.
SCREEN_GUIDE: Mapping[str, str] = {
    "Browse": (
        "Find and look at objects. Choose an Object type, type in Search, use "
        "'Add a filter' for field conditions, 'Narrow by' to click a value, and "
        "'Sort by'. 'Columns' chooses which fields show. The view can be Table, "
        "Charts or Graph. 'Saved views' keeps a search to return to; 'Frozen sets' "
        "fixes a set of objects as they are now; 'Compare' compares two sets; "
        "'Export' downloads the results. Tick objects to act on a selection. "
        "'Ask about this set' opens a panel to ask the assistant about exactly the "
        "set shown, filters and all, without leaving Browse. Opening "
        "an object shows its fields, its links, its history, notes, the actions you "
        "may run on it, and 'Ask about this object'. When the data changes while you "
        "are looking, a notice offers 'Refresh'."
    ),
    "Query": (
        "Ask a question about your data in plain language. An assistant reads only "
        "what you are permitted to read and answers with what it found. Above the "
        "answer, 'What it did to answer' lists its steps; under it, 'Open:' leads to "
        "the objects and sets it used, and 'Ask next:' suggests questions -- choosing one "
        "puts it in the box to edit or ask. 'Every field it read' shows each read and "
        "any your permissions refused. If answering needs a change to data, it proposes "
        "one, and nothing changes until it is confirmed."
    ),
    "Schema": (
        "What kinds of object exist that you may know about: their fields, how they "
        "link to each other, and the actions defined on them, as lists and as a canvas "
        "under Overview. On the canvas each type shows its fields, links and how many "
        "actions it has; click one to see its details. Drag a type, or focus it and use "
        "the arrow keys, to move it -- it stays where you put it, and 'Auto-layout' puts "
        "everything back. 'Subject areas' are named groups of types to navigate by; make "
        "one with 'New subject area'. Someone who may change roles can switch on "
        "'Security chains' to see which type borrows its security from which. Fields may "
        "carry classification labels such as pii."
    ),
    "Inbox": (
        "What arrived and is waiting for you, in three tabs; each tab and the inbox "
        "button in the header say how many. 'Approvals': proposed changes waiting for "
        "a decision -- each shows what would change; approve or reject it. Some "
        "changes need more than one reviewer, and a deployment may not let you approve "
        "a change you proposed. 'Notifications': rules that fired on the data, answers "
        "to questions that waited on an approval, and warnings about the freshness "
        "and health of the data. 'Identity': proposed merges -- two records that may be "
        "the same real thing, shown by which fields agree rather than their values; "
        "decide whether they are one. A merge that would also join records already "
        "merged is approved as the whole group. 'Enrichment': rules a model wrote to "
        "fill in a field, for someone who manages the deployment to approve or reject; "
        "each shows the rules in words and how often they agreed with the model on rows "
        "they were not written from. An approved field is filled at the next sync."
    ),
    "Admin": (
        "Users, roles and grants. Only people who manage users see this screen. The "
        "configuration, data sources, metrics and mirror of the deployment are not here: "
        "they are on 'Server', under System, for someone who may change the "
        "deployment. There, under 'Deployment', they can alter a few settings in "
        "'Change settings': 'Review changes' shows the exact lines of config.yaml that "
        "will change, and 'Apply and reload' writes them and reloads."
    ),
}

#: What every screen shares -- the palette and how a withheld value
#: looks. Same rule as SCREEN_GUIDE: quoted labels are checked against ui/.
SHELL_GUIDE = (
    "On any screen, Ctrl-K (Cmd-K on a Mac) opens a list of commands: go to a "
    "screen, 'Help', switch the theme, change 'Row density', 'Log out'. A field "
    "shown as 'Not permitted' exists, but the role of this user may not read its value "
    "-- an administrator controls that; a dash means the field is empty. A value "
    "marked 'inferred' was chosen by rules a person approved, not recorded by anyone."
)

#: Added to SHELL_GUIDE only for someone who has Browse, because the
#: palette only offers these to them -- the model must not suggest a
#: command the user's palette does not have.
SHELL_GUIDE_WITH_BROWSE = (
    " The same list browses an object type, opens a saved view, runs an action "
    "on the object being looked at, and searches a type for whatever was typed."
)

#: How much of the caller's world goes into the prompt. A schema bigger
#: than this is summarised by type rather than cut mid-field.
MAX_CONTEXT_CHARS = 16_000
MAX_QUESTION_CHARS = 1_000

SYSTEM_PROMPT = """You are the help assistant for Elysium, a system for finding, reading \
and changing an organisation's data through a defined set of object types.

Answer the user's question about USING Elysium, using ONLY the context below, which \
describes what this user can see and do. Rules:
- Explain how to do things with the screens and controls named in the context.
- You do not have any data values and must never invent any. For questions about the \
data itself, tell them to use the Query screen.
- If a field is listed as "value hidden", the user may know it exists but not read it; \
say so, and that an administrator controls access.
- If something is not in the context, the user cannot see it or it does not exist; say \
you cannot help with that rather than guessing. Never suggest a screen, type or field \
that is not listed.
- Be brief: a few sentences, or a short list of steps."""


def _schema_lines(visible_schema: Mapping) -> list[str]:
    lines = []
    for type_name, type_def in visible_schema.items():
        parts = []
        for field_name, field in (type_def.get("fields") or {}).items():
            label = field.get("display_name") or field_name
            if field.get("type") == "link":
                kind = f"link to {field.get('target')}"
            else:
                kind = str(field.get("data_type") or "text")
            hidden = "" if field.get("readable", True) else ", value hidden"
            parts.append(f"{label} ({kind}{hidden})")
        lines.append(f"- {type_name}: " + ("; ".join(parts) if parts else "no fields you may see"))
    return lines


def build_context(screens, visible_schema: Mapping, grants, current_screen: str | None) -> str:
    """Everything the model is told, all of it already the caller's."""
    screen_names = [screen["name"] for screen in screens]
    sections = ["SCREENS THIS USER CAN OPEN:"]
    sections += [f"- {name}: {SCREEN_GUIDE.get(name, '')}" for name in screen_names]
    sections.append("\nON EVERY SCREEN: " + SHELL_GUIDE
                    + (SHELL_GUIDE_WITH_BROWSE if "Browse" in screen_names else ""))
    if current_screen:
        sections.append(f"\nTHE USER IS ON: {current_screen}")
    schema = _schema_lines(visible_schema)
    sections.append("\nOBJECT TYPES AND FIELDS THIS USER MAY KNOW ABOUT:")
    sections += schema if schema else ["- none"]
    sections.append("\nTHIS USER'S OWN GRANTS: " + (", ".join(sorted(grants)) or "none"))
    context = "\n".join(sections)
    if len(context) > MAX_CONTEXT_CHARS:
        # SUMMARISED, NOT CUT: a field list truncated mid-way would tell
        # the model a type has fields it does not.
        sections = sections[: sections.index("\nOBJECT TYPES AND FIELDS THIS USER MAY KNOW ABOUT:")]
        sections.append("\nOBJECT TYPES THIS USER MAY KNOW ABOUT (fields omitted, too many to list): "
                        + ", ".join(visible_schema))
        sections.append("\nTHIS USER'S OWN GRANTS: (too many to list)")
        context = "\n".join(sections)[:MAX_CONTEXT_CHARS]
    return context


def answer(llm, question: str, context: str, *, deadline: float | None = None) -> str:
    """One call to the deployment's synthesis model."""
    question = question.strip()
    if not question:
        raise ValueError("Ask a question.")
    if len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f"Questions are limited to {MAX_QUESTION_CHARS} characters.")
    return llm.chat(
        f"{SYSTEM_PROMPT}\n\nCONTEXT:\n{context}",
        question,
        temperature=0,
        deadline=deadline,
    ).strip()
