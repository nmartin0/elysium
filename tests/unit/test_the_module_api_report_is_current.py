"""The public module API, written down (BLOCKING.md item 3, step 4), held
to the code: ui/module-api.report.md is what scripts/module_api_report.py
makes of the declarations TypeScript emits today.

API EXTRACTOR'S RULE, which Backstage applies to every package: a build
whose report is stale fails, so a change to what modules may rely on --
a signature changed, or a module importing something it did not before
-- arrives as a diff of the report, reviewed as the API change it is.
A change to anything else the kit exports does not touch the report:
those are internal, and free to change."""

import shutil

import pytest

from scripts import module_api_report


@pytest.mark.skipif(shutil.which("npx") is None, reason="needs Node's npx, to run TypeScript")
def test_the_report_is_what_the_code_says():
    report, problems = module_api_report.build()

    assert problems == []
    assert module_api_report.REPORT.read_text() == report, (
        "ui/module-api.report.md is stale: the public module API changed. Run "
        "`python -m scripts.module_api_report`, and review the diff as an API change.")


def test_a_module_s_imports_are_read_as_names():
    assert module_api_report._names("Notice") == ["default"]
    assert module_api_report._names("{ getRoles, type Role, query as ask }") == ["getRoles", "Role", "query"]
    assert module_api_report._names("ViewSelector, { type ViewOption }") == ["default", "ViewOption"]


def test_a_declaration_file_is_cut_into_its_statements():
    text = """/** about it */
export interface A {
    b: { c: string; };
}
export type D = { e: number } | null;
export declare function f(x: A): Promise<D>;
declare const g: () => void;
export default g;
"""
    assert module_api_report.statements(text) == [
        "export interface A {\n    b: { c: string; };\n}",
        "export type D = { e: number } | null;",
        "export declare function f(x: A): Promise<D>;",
        "declare const g: () => void;",
        "export default g;",
    ]


def test_names_one_letter_case_apart_keep_one_order():
    # CreateReminder and createReminder came out in either order, by
    # Python's hash order, until the order was made total (24 October).
    a = "export interface CreateReminder {\n}"
    b = "export declare function createReminder(body: CreateReminder): Promise<Reminder>;"

    assert sorted([a, b], key=module_api_report._sort_key) == sorted([b, a], key=module_api_report._sort_key)
