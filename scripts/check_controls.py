"""
check_controls.py  (proving the tests would notice)

WHY THIS EXISTS, and the reason is an observed pattern rather than a
principle. Every commit in this project claims its negative controls
fired: a deliberate break was made, the relevant test failed, the break
was reverted. Nothing checked that claim, and by the time it was
counted, NINE controls across the project had failed to fire -- each
one a test that proved nothing, every one found by hand.

Three of those nine came in a row, on the same cause: a test that
asserted a check RAN rather than that it would CATCH something. Asking
whether the name of a check appears in some output, or whether a
command exited zero, is equally true of a check that looks at nothing.
Only breaking the code on purpose tells the two apart, and doing that
by hand is exactly the ritual a script should hold.

WHAT A CONTROL IS HERE. One declared break -- a file, an exact string,
and what to replace it with -- paired with the tests that must fail
when it is applied. The runner applies it, runs those tests, and
expects failure. A control that PASSES is the finding: either the
break was not the break it claimed, or the tests do not check what they
appear to.

WHY NOT A MUTATION-TESTING LIBRARY. Those generate mutations
automatically and report a survival rate, which is a different and
weaker thing. A generated mutation nobody chose says little about
whether a specific guarantee is guarded; a declared one names the
guarantee and fails loudly when it stops being true. The list below is
therefore short and deliberate, and grows when a guarantee is worth
pinning rather than when coverage looks thin.

This does NOT run in lint.sh. Each control runs a slice of the suite
against real databases, so the whole set takes minutes -- which is
exactly the kind of thing that stops being run if it is bolted to
something that has to be fast. Run it before a release, or when a
guarantee has been rewritten.
"""

import argparse
import json
import pathlib
import subprocess
import sys
from dataclasses import dataclass, field

# THE REPOSITORY ROOT, not sim/'s. This tool arrived with the
# simulator and knew only about the simulator; it now holds the
# declared controls for BOTH projects, so every path below is relative
# to the repository and sim's own are prefixed `sim/`.
ROOT = pathlib.Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Control:
    """One deliberate break, and the tests that must notice it."""

    #: What is being broken, in the terms the guarantee is stated in.
    describes: str
    path: str
    #: Must appear EXACTLY once in the file. A break that silently
    #: matches nothing runs the unmodified code and passes, which has
    #: happened here more than once by hand.
    old: str
    new: str
    #: Tests expected to fail. Named individually rather than as a
    #: whole file, so a control that fires for an unrelated reason is
    #: visible as the wrong test failing.
    tests: list[str] = field(default_factory=list)


CONTROLS = [
    Control(
        describes="a schema change that did not take effect is caught",
        path="sim/simulator/drift.py",
        old="        verify_schema(silo, database, schema)",
        new="        pass",
        tests=["sim/tests/test_drift.py::test_a_change_that_did_not_take_effect_is_caught"],
    ),
    Control(
        describes="a name that is really SQL is refused where it enters a statement",
        path="sim/simulator/dialect.py",
        old="{Identifier(identifier)}",
        new="{identifier}",
        tests=["sim/tests/test_drift.py::test_a_rename_refuses_a_name_that_is_really_sql"],
    ),
    Control(
        describes="a process that cannot be signalled counts as running",
        path="sim/simulator/silos/process.py",
        old="    except PermissionError:",
        new="    except NotImplementedError:",
        tests=["sim/tests/test_postgres_silo.py::"
               "test_a_process_that_cannot_be_signalled_counts_as_running"],
    ),
    Control(
        # This control was SILENT on its first run, and the finding was
        # real: breaking the narrowed `except` changed nothing, because
        # the silo lookup the test exercises sits OUTSIDE the try and
        # its KeyError propagates whatever the except clause says. So
        # the break is now the thing the test actually guards -- the
        # lookup's placement -- and the narrowing has a control of its
        # own below.
        describes="a watch naming a silo that does not exist is a mistake, not drift",
        path="sim/simulator/oracle.py",
        old="            silo = world.silo(watch.silo)\n"
            "            dialect = dialect_for(silo.kind)\n"
            "            try:",
        new="            try:\n"
            "                silo = world.silo(watch.silo)\n"
            "                dialect = dialect_for(silo.kind)",
        tests=["sim/tests/test_oracle.py::"
               "test_a_mistake_in_a_watch_is_not_reported_as_drift"],
    ),
    Control(
        describes="a failure that is not the driver's is not recorded as a sample",
        path="sim/simulator/oracle.py",
        old="            except silo.driver_errors():",
        new="            except Exception:  # noqa: BLE001",
        tests=["sim/tests/test_oracle.py::"
               "test_a_failure_that_is_not_the_databases_is_not_recorded"],
    ),
    Control(
        describes="prose keeps its sentences in the order they were declared",
        path="sim/simulator/generators.py",
        old="        chosen = sorted(sample_without_replacement(\n"
            "            context.rng, range(len(self.sentences)), count))",
        new="        chosen = sample_without_replacement(\n"
            "            context.rng, range(len(self.sentences)), count)",
        tests=["sim/tests/test_generators.py::"
               "test_prose_reads_in_the_order_it_was_declared"],
    ),
    Control(
        describes="a rule's first matching clause wins",
        path="sim/simulator/generators.py",
        old="        for condition, generator in self.clauses:\n"
            "            if _is_true(evaluate(condition, context)):",
        new="        for condition, generator in reversed(self.clauses):\n"
            "            if _is_true(evaluate(condition, context)):",
        tests=["sim/tests/test_generators.py::test_the_first_matching_clause_wins"],
    ),
    Control(
        describes="text cannot be done arithmetic to",
        path="sim/simulator/expression.py",
        old="        if isinstance(left, str) or isinstance(right, str):",
        new="        if False:",
        tests=["sim/tests/test_expression.py::test_text_cannot_be_done_arithmetic_to"],
    ),
    Control(
        describes="seeding writes in chunks rather than building every row first",
        path="sim/simulator/runner.py",
        old="        if len(chunk) >= SEED_CHUNK_ROWS:",
        new="        if False:",
        tests=["sim/tests/test_runner.py::test_seeding_really_writes_in_chunks"],
    ),
    Control(
        describes="the migration history records when a change really happened",
        path="sim/simulator/drift.py",
        old="            cursor.execute(insert, [at, datetime.now(UTC), operation, detail,",
        new="            cursor.execute(insert, [at, at, operation, detail,",
        tests=["sim/tests/test_drift.py::test_every_change_records_both_clocks"],
    ),
    Control(
        describes="a seed step with a count writes that many rows per subject",
        path="sim/simulator/runner.py",
        old="        [row for row in world.subject_rows(step.per) for _ in range(step.count)]",
        new="        list(world.subject_rows(step.per))",
        tests=["sim/tests/test_field_service.py::test_every_engineer_has_more_than_one_row",
               "sim/tests/test_field_service.py::"
               "test_engineers_hold_skills_through_a_join_table"],
    ),
    Control(
        describes="a seed step's picks reach the row being built",
        path="sim/simulator/runner.py",
        old="            context.picked[name] = context.rng.choice(candidates)",
        new="            context.picked[name] = candidates[0]",
        tests=["sim/tests/test_field_service.py::"
               "test_a_pair_can_repeat_and_that_is_the_documented_behaviour"],
    ),
    Control(
        describes="a resume with no live entities refuses rather than continuing",
        path="sim/simulator/resume.py",
        old="    if not any(entities.values()) and still_held:",
        new="    if False:",
        tests=["sim/tests/test_resume.py::test_a_resume_with_no_entities_refuses"],
    ),
    Control(
        describes="a resumed world's ids continue past what is already there",
        path="sim/simulator/resume.py",
        old="    world.counters.update(highest)",
        new="    pass",
        tests=["sim/tests/test_resume.py::"
               "test_a_second_leg_continues_rather_than_colliding"],
    ),
    Control(
        describes="a row whose state is not a lifecycle state is not loaded",
        path="sim/simulator/resume.py",
        old="            if str(state) not in states:",
        new="            if False:",
        tests=["sim/tests/test_resume.py::"
               "test_a_row_whose_state_is_not_a_lifecycle_state_is_left_alone"],
    ),
    Control(
        describes="a dispute voids one bill rather than a whole history",
        path="sim/packs/field_service.yaml",
        old="        where: {work_order_id: {generator: reference, "
            "from: subject.work_order_id}}\n"
            "        columns:\n"
            "          is_void:   {generator: constant, value: true}",
        new="        where: {customer_id: {generator: reference, "
            "from: subject.customer_id}}\n"
            "        columns:\n"
            "          is_void:   {generator: constant, value: true}",
        tests=["sim/tests/test_field_service.py::"
               "test_a_dispute_voids_one_bill_and_not_a_history"],
    ),
    Control(
        describes="an export with a window reaches back only that far",
        path="sim/simulator/event.py",
        old="    if window is not None:\n"
            "        window_column = world.lineage.column(silo_name, table_name, window.column)",
        new="    if False:\n"
            "        window_column = world.lineage.column(silo_name, table_name, window.column)",
        tests=["sim/tests/test_field_service.py::"
               "test_the_payroll_file_holds_real_pay_lines"],
    ),
    Control(
        describes="rotated log parts are read oldest first",
        path="sim/simulator/silos/logs.py",
        old="        key=lambda candidate: int(candidate.suffix.lstrip(\".\")), reverse=True,",
        new="        key=lambda candidate: int(candidate.suffix.lstrip(\".\")),",
        tests=["sim/tests/test_audit.py::"
               "test_a_log_is_read_in_the_order_things_happened"],
    ),
    Control(
        describes="rotation moves a log aside rather than truncating it",
        path="sim/simulator/silos/logs.py",
        old="    path.rename(moved)",
        new="    moved.write_text(path.read_text()[:0]); path.unlink()",
        tests=["sim/tests/test_audit.py::test_rotation_keeps_everything"],
    ),
    Control(
        describes="seeding leaves no stale view of a table it wrote",
        path="sim/simulator/runner.py",
        old="    world.forget_subject_rows()",
        new="    pass",
        tests=["sim/tests/test_runner.py::"
               "test_seeding_leaves_no_stale_view_of_a_table_it_wrote",
               "sim/tests/test_field_service.py::"
               "test_both_copies_of_a_household_accumulate_work"],
    ),
    Control(
        describes="a duplicated household agrees with itself",
        path="sim/packs/field_service.yaml",
        old="      phone:        {generator: reference, from: picked.customers.phone}",
        new="      phone:        {generator: template, pattern: \"0117 {customer_id}\"}",
        tests=["sim/tests/test_field_service.py::test_a_duplicate_agrees_with_itself"],
    ),
    Control(
        describes="a dispute claws back the commission it paid",
        path="sim/packs/field_service.yaml",
        old="      - update: dispatch.pay_lines\n"
            "        where: {work_order_id: {generator: reference, "
            "from: subject.work_order_id}}\n"
            "        columns:\n"
            '          amount: {generator: constant, value: "0.0000"}',
        new="      - update: dispatch.customers\n"
            "        where: {customer_id: {generator: reference, "
            "from: subject.customer_id}}\n"
            "        columns:\n"
            "          updated_at: {generator: now}",
        tests=["sim/tests/test_field_service.py::"
               "test_a_dispute_claws_back_the_engineers_commission",
               "sim/tests/test_field_service.py::"
               "test_the_payroll_files_and_dispatch_disagree_about_what_was_earned"],
    ),
    Control(
        describes="an emitted reference's aggregate is checked at load",
        path="sim/simulator/spec/references.py",
        old="        if aggregate not in AGGREGATES:",
        new="        if False:",
        tests=["sim/tests/test_pack_loader.py::"
               "test_an_emitted_reference_must_name_a_real_aggregate"],
    ),
    Control(
        describes="the shop's delivery rule follows the order total",
        path="sim/packs/retail.yaml",
        old='              - if: "goods_total >= 50"',
        new='              - if: "goods_total >= 0"',
        tests=["sim/tests/test_retail.py::"
               "test_delivery_follows_the_rule_the_shop_wrote_down"],
    ),
    Control(
        describes="cleanup will not signal something that is not a server",
        path="sim/simulator/cleanup.py",
        old="        if not _is_engine(command):",
        new="        if False:",
        tests=["sim/tests/test_cleanup.py::"
               "test_a_process_naming_the_directory_is_found_only_if_it_is_a_server"],
    ),
    Control(
        describes="a stray is asked to stop rather than killed",
        path="sim/simulator/cleanup.py",
        old="        os.kill(stray.pid, signal.SIGTERM)",
        new="        os.kill(stray.pid, signal.SIGKILL)",
        tests=["sim/tests/test_cleanup.py::"
               "test_one_that_will_not_stop_is_reported_rather_than_forced"],
    ),
    Control(
        describes="the world view's parameter names match the world's",
        path="sim/simulator/worldview.py",
        old="    def database(self, silo_name: str) -> str: ...",
        new="    def database(self, name: str) -> str: ...",
        tests=["sim/tests/test_worldview.py::test_the_call_signatures_match"],
    ),
    Control(
        describes="a lookup table writes the rows it declares",
        path="sim/simulator/runner.py",
        old="    if step.rows:",
        new="    if False:",
        tests=["sim/tests/test_field_service.py::"
               "test_the_skills_are_the_ones_a_plumbing_firm_really_has"],
    ),
    Control(
        describes="declared rows must all name the same columns",
        path="sim/simulator/spec/seed.py",
        old="    if len(keys) > 1:",
        new="    if False:",
        tests=["sim/tests/test_effects.py::"
               "test_every_declared_row_names_the_same_columns"],
    ),
    Control(
        describes="distinct picks do not repeat within a subject",
        path="sim/simulator/runner.py",
        old="            if step.distinct_picks:",
        new="            if False:",
        tests=["sim/tests/test_runner.py::"
               "test_distinct_picks_refuse_to_repeat_within_a_subject",
               "sim/tests/test_field_service.py::"
               "test_no_engineer_holds_the_same_ticket_twice"],
    ),
    Control(
        describes="one subject's picks do not constrain another's",
        path="sim/simulator/runner.py",
        old="        if subject is not previous_subject:",
        new="        if False:",
        tests=["sim/tests/test_runner.py::"
               "test_distinct_picks_refuse_to_repeat_within_a_subject"],
    ),
    Control(
        describes="an update's pick is read fresh, not from the cache",
        path="sim/simulator/event.py",
        old="    rows = fetch_all(silo, world.database(silo_name),\n"
            '                     f"SELECT {selected} FROM {dialect.quote(table.name)}") '
            "if table else []",
        new="    rows = [tuple(row.get(name) for name in names)\n"
            "            for row in world.subject_rows(qualified)]",
        tests=["sim/tests/test_runner.py::"
               "test_an_updates_pick_sees_rows_written_during_the_run"],
    ),
    Control(
        describes="a withheld table really is refused to the reader",
        path="sim/simulator/runner.py",
        old="            withhold(silos[silo_name], database,",
        new="            _ = (lambda *a, **k: None)(silos[silo_name], database,",
        tests=["sim/tests/test_field_service.py::"
               "test_the_reader_cannot_see_what_the_engineers_earn"],
    ),
    Control(
        describes="a withheld table naming nothing is caught at load",
        path="sim/simulator/spec/loader.py",
        old="        if missing:",
        new="        if False:",
        tests=["sim/tests/test_pack_loader.py::"
               "test_a_withheld_table_must_be_one_the_silo_declares"],
    ),
    Control(
        describes="a resumed entity keeps the dwell it had",
        path="sim/simulator/resume.py",
        old="            entered = row[2] if entered_column is not None else None",
        new="            entered = None",
        tests=["sim/tests/test_resume.py::test_a_resumed_entity_keeps_the_dwell_it_had"],
    ),
    Control(
        describes="the moment a state was entered is written at birth",
        path="sim/simulator/event.py",
        old="                    row[where.entered_column] = entity.entered_state_at",
        new="                    pass",
        tests=["sim/tests/test_resume.py::"
               "test_the_moment_is_written_whenever_a_state_changes"],
    ),
    Control(
        describes="verification compares column types, not just names",
        path="sim/simulator/relational.py",
        old="        if got.type is not want.type:",
        new="        if False:",
        tests=["sim/tests/test_relational.py::"
               "test_verification_notices_a_column_whose_type_changed"],
    ),
    Control(
        describes="verification compares a decimal's precision",
        path="sim/simulator/relational.py",
        old="        if want.type is ColumnType.DECIMAL and (",
        new="        if False and (",
        tests=["sim/tests/test_relational.py::"
               "test_verification_notices_a_decimal_that_lost_its_pence"],
    ),
    Control(
        describes="an attached world takes its shape from the engine",
        path="sim/simulator/runner.py",
        old="        schemas[silo_name] = (read_schema(silo, database) if database is not None",
        new="        schemas[silo_name] = (pack.schemas[silo_name] if database is not None",
        tests=["sim/tests/test_resume.py::"
               "test_a_drifted_world_resumes_with_the_shape_drift_left"],
    ),
    Control(
        describes="a resume with the wrong pack is refused",
        path="sim/simulator/resume.py",
        old="    if saved.pack and saved.pack != world.pack.name:",
        new="    if False:",
        tests=["sim/tests/test_resume.py::test_resuming_with_a_different_pack_is_refused"],
    ),
    Control(
        describes="a database changed behind the world's back is refused",
        path="sim/simulator/resume.py",
        old="    if saved.shape and saved.shape != fingerprint(world):",
        new="    if False:",
        tests=["sim/tests/test_resume.py::"
               "test_a_database_that_changed_while_the_world_was_down_is_refused"],
    ),
    Control(
        describes="a failed tick puts memory back where the databases are",
        path="sim/simulator/runner.py",
        old="        _restore(world, before)",
        new="        pass",
        tests=["sim/tests/test_runner.py::"
               "test_a_failed_tick_leaves_memory_where_the_databases_are"],
    ),
    Control(
        describes="a restored entity is a copy, not the same object",
        path="sim/simulator/runner.py",
        old="        \"entities\": {name: [replace(entity) for entity in entities]",
        new="        \"entities\": {name: list(entities)",
        tests=["sim/tests/test_runner.py::"
               "test_a_failed_tick_leaves_memory_where_the_databases_are"],
    ),
    Control(
        describes="an emission has exactly one destination",
        path="sim/simulator/spec/events.py",
        old="    if len(named) > 1:",
        new="    if False:",
        tests=["sim/tests/test_events.py::test_an_emission_has_exactly_one_destination"],
    ),
    Control(
        describes="a pack's watches reach the oracle",
        path="sim/simulator/runner.py",
        old="        ports=registry,\n        oracle=Oracle(watches=pack.watches),",
        new="        ports=registry,",
        tests=["sim/tests/test_field_service.py::"
               "test_the_pack_watches_the_numbers_the_firm_would_notice"],
    ),
    Control(
        describes="a watch is checked against the schema at load",
        path="sim/simulator/spec/watches.py",
        old="        if column is None:",
        new="        if False:",
        tests=["sim/tests/test_watches.py::"
               "test_a_watch_naming_something_that_is_not_there_is_refused"],
    ),
    Control(
        describes="the consumer accounts must send a password",
        path="sim/simulator/silos/postgres.py",
        old="        self._require_passwords_of_consumers()",
        new="        pass",
        tests=["sim/tests/consumer/test_read_only.py::"
               "test_the_reader_must_send_a_password"],
    ),
    Control(
        describes="each consumer account has its own password",
        path="sim/simulator/silos/reader.py",
        # The whole returned value, not just the digest: the account
        # name is also in the PREFIX, so hashing the seed alone still
        # gives two different passwords. A first version of this break
        # did exactly that and the control stayed silent.
        old="    return f\"{account}-{digest[:16]}\"",
        new="    return f\"shared-{digest[:16]}\"",
        tests=["sim/tests/consumer/test_read_only.py::"
               "test_the_writer_has_its_own_password",
               "sim/tests/test_relational.py::"
               "test_a_password_is_the_same_for_the_same_world"],
    ),
    Control(
        describes="a replica is refreshed only when its interval comes round",
        path="sim/simulator/runner.py",
        old="        if due is not None and elapsed - due < spec.refresh_seconds:",
        new="        if False:",
        tests=["sim/tests/test_replicas.py::test_a_replica_falls_behind_and_catches_up"],
    ),
    Control(
        describes="a replica is rebuilt rather than added to",
        path="sim/simulator/runner.py",
        old="            truncate(target, database, table)",
        new="            pass",
        tests=["sim/tests/test_replicas.py::"
               "test_a_replica_reflects_changes_and_not_just_additions"],
    ),
    Control(
        describes="each world keeps its own replica refresh clock",
        path="sim/simulator/runner.py",
        # BOTH the read and the write. A first version broke only the
        # read, so the shared dict stayed empty, every lookup returned
        # None and the replica refreshed every tick -- the opposite of
        # the bug, and the control stayed silent.
        old="        due = world.replica_refreshed.get(name)\n"
            "        if due is not None and elapsed - due < spec.refresh_seconds:\n"
            "            continue\n"
            "        world.replica_refreshed[name] = elapsed",
        new="        due = _SHARED_REFRESH.get(name)\n"
            "        if due is not None and elapsed - due < spec.refresh_seconds:\n"
            "            continue\n"
            "        _SHARED_REFRESH[name] = elapsed",
        tests=["sim/tests/test_replicas.py::"
               "test_two_worlds_do_not_share_a_refresh_clock"],
    ),
    Control(
        describes="a DELETE that failed for another reason is not a refusal",
        path="sim/simulator/health.py",
        old="            if not _is_permission_error(error):",
        new="            if False:",
        tests=["sim/tests/test_cli.py::"
               "test_verify_does_not_call_a_broken_delete_a_refusal"],
    ),
    Control(
        describes="the hygiene check catches a test that asserts over nothing",
        path="sim/tests/test_field_service.py",
        old="    assert len(notes) == 6, notes\n",
        new="",
        tests=["sim/tests/test_suite_hygiene.py::"
               "test_no_test_asserts_about_every_row_of_nothing"],
    ),
    Control(
        describes="the hygiene check catches a shouted comment",
        path="sim/simulator/clock.py",
        old="#: One real second becomes one simulated minute.",
        new="#: ONE REAL SECOND BECOMES one simulated minute.",
        tests=["sim/tests/test_suite_hygiene.py::test_comments_are_not_shouted"],
    ),
    Control(
        describes="verify notices a table with no primary key",
        path="sim/simulator/health.py",
        old='            raise RuntimeError(f"no primary key on {sorted(missing)}")',
        new="            pass",
        tests=["sim/tests/test_cli.py::test_verify_notices_a_table_with_no_primary_key"],
    ),

    # ------------------------------------------------------------
    # ELYSIUM'S OWN, from the manual sweep in patches 467, 472 and
    # 473. Thirteen guarantees were broken by hand and the suite
    # watched; all thirteen were caught. Declaring them here is what
    # stops that being a one-off afternoon.
    #
    # THE SWEEP ALSO FOUND ITS OWN METHOD BROKEN: the unit suite was
    # split `head -160` and `tail -146` of 318 files, so twelve never
    # ran, and one published result was wrong because of it. A control
    # names the tests it expects to fail, so there is no split to get
    # wrong.
    # ------------------------------------------------------------
    Control(
        describes="a sync takes the single-writer lock",
        path="scripts/run_sync.py",
        old="from core.mirror.sync_lock import single_writer",
        new=("import contextlib\n"
             "@contextlib.contextmanager\n"
             "def single_writer(*a, **k):\n"
             "    yield"),
        tests=["tests/unit/test_repair_waits_for_the_sync.py::TestBothWritersUseIt::test_the_sync_takes_it"],
    ),
    Control(
        describes="repair takes the same lock as the sync",
        path="scripts/repair_catalog.py",
        old="from core.mirror.sync_lock import single_writer",
        new=("import contextlib\n"
             "@contextlib.contextmanager\n"
             "def single_writer(*a, **k):\n"
             "    yield"),
        tests=["tests/unit/test_repair_waits_for_the_sync.py::TestBothWritersUseIt::test_and_so_does_the_repair"],
    ),
    Control(
        describes="silver leaves the security field exactly as stored",
        path="core/mirror/sync_targets.py",
        old="        if field_name == security_field:",
        new="        if False:",
        tests=["tests/unit/test_silver_standardisation.py::TestDeclaringTheRules::test_the_rules_reach_the_sync_target",
               "tests/unit/test_the_pipeline_does_not_move_access.py::TestTheTwoPathsAgreeAboutVisibility::test_whatever_whitespace_the_source_holds[us-west"],
    ),
    Control(
        describes="an approval re-reads the generation inside the lock",
        path="api/routes.py",
        old=("        config = latest_generation(request).config\n"
             "        every, active = _holders(request)"),
        new=("        config = _generation(request).config\n"
             "        every, active = _holders(request)"),
        tests=["tests/integration/test_role_changes.py::TestApprovalsDoNotLoseEachOther::test_a_request_pinned_before_another_approval_keeps_it"],
    ),
    Control(
        describes="the CSRF token is compared, not assumed",
        path="api/csrf_middleware.py",
        old="secrets.compare_digest(",
        new="(lambda _a, _b: True)(",
        tests=["tests/integration/test_csrf_constant_time.py::TestPinnedAtSource::test_the_token_is_compared_with_compare_digest",
               "tests/integration/test_csrf_constant_time.py::TestTheBehaviourAroundIt::test_a_different_token_is_refused"],
    ),
    Control(
        describes="a write is refused without the execute grant",
        path="core/ontology/write_mediator.py",
        old="        if not rbac_allowed:",
        new="        if False:",
        tests=["tests/unit/test_write_mediator.py::test_propose_action_denied_for_ungranted_action_even_with_a_different_action_granted"],
    ),
    Control(
        describes="gold refuses a publication that lost most of its rows",
        path="core/mirror/gold_arrow.py",
        old=("    if previous_count and table.num_rows < previous_count "
             "* (1 - MAX_DELETED_FRACTION):"),
        new="    if False:",
        tests=["tests/unit/test_gold_streaming.py::TestTheThreeAuditsAgree::test_word_for_word[rows2-10]",
               "tests/unit/test_gold_streaming.py::TestTheThreeAuditsAgree::test_word_for_word[rows6-100]"],
    ),
    Control(
        describes="a declared on_violation: fail stops the build",
        path="core/mirror/expectations.py",
        old=("        failed = [v for v in violations if v.policy == FAIL]\n"
             "        if failed:"),
        new=("        failed = [v for v in violations if v.policy == FAIL]\n"
             "        if False:"),
        tests=["tests/unit/test_silver_expectations.py::TestTheThreePolicies::test_fail_stops_the_build",
               "tests/unit/test_silver_expectations.py::TestThroughTheSync::test_fail_leaves_the_mirror_unchanged"],
    ),
    Control(
        describes="an expired session is refused",
        path="core/auth/session_store.py",
        old="        if datetime.now(UTC) >= expires_at:",
        new="        if False:",
        tests=["tests/integration/test_expired_session_is_refused.py::test_a_session_that_has_expired_is_refused",
               "tests/integration/test_expired_session_is_refused.py::test_the_refusal_is_the_same_uniform_401_as_no_session_at_all"],
    ),
    # ------------------------------------------------------------
    # THE LINEAGE ROUTES, which answered "nothing recorded" on every
    # real deployment because they looked for a `_catalog` attribute
    # GoldConnector does not have -- and since GOLD-9 made reads
    # gold-only, GoldConnector is the only adapter there is. Their
    # tests guarded their assertions with `if body is not None`.
    # ------------------------------------------------------------
    Control(
        describes="the lineage routes can actually find the deployment's catalog",
        path="api/routes.py",
        old='        (adapter.catalog for adapter in mediator.adapters.values()\n'
            '         if getattr(adapter, "catalog", None) is not None),',
        new='        (getattr(adapter, "_catalog", None) for adapter in mediator.adapters.values()\n'
            '         if getattr(adapter, "_catalog", None) is not None),',
        tests=["tests/integration/test_the_provenance_route.py::TestWhatItAnswers::test_IT_ACTUALLY_ANSWERS_SOMETHING",
               "tests/integration/test_the_conflicts_route.py::TestTheLosingValueComesBack::test_it_says_what_the_other_source_held_and_where_each_came_from"],
    ),
    Control(
        describes="a conflict about another compartment's object is not served",
        path="api/routes.py",
        # ANCHORED ON THE LINE AFTER IT, because _may_read_object
        # guards the notes route too and the bare call matches twice --
        # which this script refuses, correctly: a break matching
        # several places could silently change the wrong one.
        old=("    if not _may_read_object(mediator, current_user, object_type, "
             "object_id):\n        return []\n\n"
             "    catalog = _deployment_catalog(mediator)"),
        new=("    if not True:\n        return []\n\n"
             "    catalog = _deployment_catalog(mediator)"),
        tests=["tests/integration/test_the_conflicts_route.py::TestMACSTILLAPPLIES::test_an_administrator_in_another_compartment_gets_nothing"],
    ),
    Control(
        describes="a conflict's values are withheld when the field is not readable",
        path="api/routes.py",
        old="        may_read = field_name is None or field_name in readable",
        new="        may_read = True",
        tests=["tests/integration/test_the_conflicts_route.py::TestAFieldTheyMayNotRead::test_and_neither_value_is_anywhere_in_the_body"],
    ),
    # ------------------------------------------------------------
    # THE MERGE REVIEWER'S SURFACE, which had no control either and
    # spent months telling a reviewer "one side missing" about every
    # field of every proposal. Found by the R52 sweep. A feature with
    # a typed client and no screen: nobody would ever have seen it.
    # ------------------------------------------------------------
    Control(
        describes="the reviewer's readable fields are actually looked up",
        path="api/routes.py",
        old="    type_def = (schema or {}).get(object_type) or {}",
        new='    type_def = (schema or {}).get("object_types", {}).get(object_type) or {}',
        tests=["tests/integration/test_a_merge_reviewer_sees_verdicts.py::TestTheReviewerSeesVerdictsNotValues::test_a_field_the_reviewer_CAN_read_carries_its_values",
               "tests/integration/test_a_merge_reviewer_sees_verdicts.py::TestTheReviewerSeesVerdictsNotValues::test_and_NOTHING_is_withheld_when_everything_is_readable"],
    ),
    Control(
        describes="a WITHHELD field is not reported as a missing one",
        path="core/masked_review.py",
        old="    if readable and not (left_has_value and right_has_value):",
        new="    if not (left_has_value and right_has_value):",
        tests=["tests/unit/test_a_reviewer_sees_verdicts_not_values.py::TestTheVerdictIsAlwaysGiven::test_A_WITHHELD_FIELD_IS_NOT_CALLED_MISSING",
               "tests/integration/test_a_merge_reviewer_sees_verdicts.py::TestTheReviewerSeesVerdictsNotValues::test_A_FIELD_THE_REVIEWER_MAY_NOT_READ_IS_STILL_WITHHELD"],
    ),
    Control(
        describes="a null comparison is not reported as a disagreement",
        path="core/mirror/matching.py",
        old="    if value < 0:\n        return None",
        new="    if False:\n        return None",
        tests=["tests/unit/test_probabilistic_matching.py::TestANullIsNotADISAGREEMENT::test_a_null_comparison_is_not_compared"],
    ),
    # ------------------------------------------------------------
    # THE DRIFT VERDICTS HAD NO NEGATIVE CONTROL, which the R19 sweep
    # found: drift_policy.py is the module whose whole purpose is that
    # "storage behaviour must not become policy by default", and
    # nothing here broke either verdict to check the tests noticed.
    # ------------------------------------------------------------
    Control(
        describes="a vanished column with writes against it REFUSES the sync",
        path="core/mirror/drift_policy.py",
        old="    if applied == 0 and pending == 0:",
        new="    if True:",
        tests=["tests/unit/test_drift_policy.py::TestRemovedColumn::test_refuses_when_a_pending_write_depends_on_it",
               "tests/unit/test_drift_policy.py::TestRemovedColumn::test_refuses_when_applied_history_depends_on_it"],
    ),
    Control(
        describes="a type that stopped matching is refused even with no writes",
        path="core/mirror/drift_policy.py",
        old="        absorbed=False,\n        shape=DriftShape.TYPE_CHANGED,",
        new="        absorbed=True,\n        shape=DriftShape.TYPE_CHANGED,",
        tests=["tests/unit/test_drift_policy.py::TestTypeChange::test_is_always_refused_even_with_no_writes"],
    ),
    Control(
        describes="a rename is reported as a rename, not as a bare removal",
        path="core/mirror/iceberg_sync.py",
        old="        appeared = tuple(sorted(set(present) - set(columns) - (before or set())))",
        new="        appeared = ()",
        tests=["tests/unit/test_a_source_changes_and_what_a_reader_sees.py::TestARenamedColumn::test_a_rename_holds_the_table_at_its_last_good_copy"],
    ),
    Control(
        describes="a bare removal is NOT reported as a possible rename",
        path="core/mirror/drift_policy.py",
        old="        if appeared:",
        new="        if True:",
        tests=["tests/unit/test_a_source_changes_and_what_a_reader_sees.py::TestARenamedColumn::test_an_ordinary_DROP_is_not_described_as_a_possible_rename"],
    ),
    Control(
        describes="a partial source read does not overwrite the mirror",
        path="core/mirror/iceberg_sync.py",
        old=("        if not previous or row_count >= previous "
             "* (1 - MAX_DELETED_FRACTION):"),
        new="        if True:",
        tests=["tests/unit/test_a_partial_read_does_not_overwrite.py::TestTheMirrorIsLeftAlone::test_a_truncated_read_is_refused",
               "tests/unit/test_a_partial_read_does_not_overwrite.py::TestTheMirrorIsLeftAlone::test_silver_still_serves_every_row"],
    ),
    Control(
        describes="a field declaring no_invisible_characters is enforced",
        path="core/ontology/constraints.py",
        old='    if constraints.get("no_invisible_characters"):',
        new="    if False:",
        tests=["tests/unit/test_invisible_characters_can_be_declared.py::TestTheDeclaredRule::test_a_violation_is_reported[Acme",
               "tests/unit/test_invisible_characters_can_be_declared.py::TestTheDeclaredRule::test_a_violation_is_reported[Acme"],
    ),
    Control(
        describes="a field declaring no_misleading_text is enforced",
        path="core/ontology/constraints.py",
        old='    if constraints.get("no_misleading_text"):',
        new="    if False:",
        tests=["tests/unit/test_misleading_text_can_be_declared.py::TestTheDeclaredRule::test_a_violation_is_reported",
               "tests/unit/test_misleading_text_can_be_declared.py::TestTheDeclaredRule::test_the_two_rules_are_independent"],
    ),
    Control(
        describes="a stranded catalog refuses instead of crashing",
        path="core/deployment_loader.py",
        old="        except (FileNotFoundError, OSError) as missing:",
        new="        except RuntimeError as missing:",
        tests=["tests/unit/test_a_stranded_catalog_says_so.py::"
               "TestTheLoaderRaisesIt::"
               "test_a_missing_metadata_file_is_turned_into_this"],
    ),
    Control(
        describes="bronze expires its own snapshots",
        path="core/mirror/iceberg_sync.py",
        # ANCHORED ON THE COMMENT ABOVE THE CALL, not the call itself.
        # Bronze's call line is indented twelve spaces and silver's
        # sixteen, so the shorter is a SUBSTRING of the longer -- a
        # break written against it matched two places, then none.
        old=("            # request could be holding is a candidate.\n"
             "            try:"),
        new=("            # request could be holding is a candidate.\n"
             "            if False:"),
        tests=["tests/unit/test_bronze_and_silver_expire_too.py::"
               "TestBothLayersCallIt::test_bronze_does"],
    ),
    Control(
        describes="silver expires its own snapshots",
        path="core/mirror/iceberg_sync.py",
        old=("                # expire and a commit there would be pure cost.\n"
             "                try:"),
        new=("                # expire and a commit there would be pure cost.\n"
             "                if False:"),
        tests=["tests/unit/test_bronze_and_silver_expire_too.py::"
               "TestBothLayersCallIt::test_silver_does"],
    ),
    Control(
        describes="compare: the overlap is an intersection",
        path="api/routes.py",
        old='        "both": len(left_set & right_set),',
        new='        "both": len(left_set | right_set),',
        tests=["tests/integration/test_compare_sets.py::TestComparing::"
               "test_it_counts_the_three_regions"],
    ),
    Control(
        describes="compare: a saved view runs with its own conditions",
        path="api/routes.py",
        old="        conditions = parse_filters(checked.runnable) if checked.runnable else []",
        new="        conditions = []",
        tests=["tests/integration/test_compare_sets.py::TestComparing::"
               "test_a_saved_view_is_run_as_its_owner_saved_it"],
    ),
    Control(
        describes="compare: a saved view is compared as saved",
        path="api/routes.py",
        old="    if reference.saved_view and narrowed:",
        new="    if False:",
        tests=["tests/integration/test_compare_sets.py::TestWhatCannotBeCompared::"
               "test_a_saved_view_with_more_filters_is_refused"],
    ),
    Control(
        describes="compare: a saved view is looked up among the caller's own",
        path="api/routes.py",
        old="        if view is None or view.object_type != object_type:\n"
            "            raise HTTPException(status_code=404, detail=\"No such saved view\")",
        new="        if view is None:\n"
            "            from core.saved_views import SavedViewStore as _S\n"
            "            view = _S(request.app.state.runtime_paths.data_dir / \"saved_views.db\")"
            ".get(reference.saved_view)",
        tests=["tests/integration/test_compare_sets.py::TestWhatCannotBeCompared::"
               "test_somebody_elses_saved_view_is_no_view"],
    ),
    Control(
        describes="combine: the right-hand region excludes the left",
        path="api/routes.py",
        old='        "right_only": lambda member: member not in left_set,',
        new='        "right_only": lambda member: member in right_set,',
        tests=["tests/integration/test_compare_sets.py::TestKeepingAPart::"
               "test_the_right_hand_part_is_the_right_hand_part"],
    ),
    Control(
        describes="combine: both is in both, not merely in the right",
        path="api/routes.py",
        old='        "both": lambda member: member in left_set and member in right_set,',
        new='        "both": lambda member: member in right_set,',
        tests=["tests/integration/test_compare_sets.py::TestKeepingAPart::"
               "test_both_means_both_when_each_side_has_its_own"],
    ),
    Control(
        describes="combine: an empty region is refused",
        path="api/routes.py",
        old='        raise HTTPException(status_code=400, detail="That part is empty, '
            'so there is nothing to keep.")',
        new="        pass",
        tests=["tests/integration/test_compare_sets.py::TestKeepingAPart::"
               "test_an_empty_part_is_refused_not_saved"],
    ),

    Control(
        describes="bench: get_object refuses another type's id",
        path="core/agent/agentic_loop.py",
        old='        _reject_ids_of_another_type(step["object_type"], object_ids, gathered, visible_schema)\n',
        new='',
        tests=["tests/unit/test_bench_failures_are_answered.py::TestAnotherTypesId::test_the_bench_s_wrong_step_is_refused_with_the_link_to_follow"],
    ),
    Control(
        describes="bench: get_field refuses an unknown field",
        path="core/agent/agentic_loop.py",
        old='            {"object_type": step.get("object_type"), "field_names": [step.get("field_name")]},',
        new='            {"object_type": step.get("object_type"), "field_names": []},',
        tests=["tests/unit/test_bench_failures_are_answered.py::TestACountIsNotAField::test_get_field_is_refused_too_rather_than_answering_none"],
    ),
    Control(
        describes="bench: a count-shaped field name gets the aggregate step",
        path="core/agent/agentic_loop.py",
        old="        if id_field in unknown or any(str(name).lower() in _AGGREGATE_WORDS for name in unknown):",
        new="        if id_field in unknown:",
        tests=["tests/unit/test_bench_failures_are_answered.py::TestACountIsNotAField::test_get_object_names_the_step_that_counts"],
    ),
    Control(
        describes="bench: the asymmetry nudge names what is missing",
        path="core/agent/agentic_loop.py",
        old='                    f"{_what_is_missing(object_type, id_map)}")',
        new='                    "")',
        tests=["tests/unit/test_bench_failures_are_answered.py::TestTheNudgeSaysWhatIsMissing::test_it_names_the_object_and_the_field"],
    ),
    Control(
        describes="bench: an id from a link result is never refused",
        path="core/agent/agentic_loop.py",
        old="        if owner is None or object_id in this_type or object_id in any_type:",
        new="        if owner is None or object_id in this_type:",
        tests=["tests/unit/test_bench_failures_are_answered.py::TestTheIdGuardIsConservative::test_an_id_also_seen_in_a_link_result_is_allowed"],
    ),
    Control(
        describes="bench: an id read as this type is never refused",
        path="core/agent/agentic_loop.py",
        old="        if owner is None or object_id in this_type or object_id in any_type:",
        new="        if owner is None or object_id in any_type:",
        tests=["tests/unit/test_bench_failures_are_answered.py::TestTheIdGuardIsConservative::test_an_id_already_read_as_this_type_is_allowed"],
    ),

    Control(
        describes="bench: a refused step is not 'already had'",
        path="core/agent/agentic_loop.py",
        old="                seen_signatures.difference_update(remembered)",
        new="                pass",
        tests=["tests/unit/test_bench_failures_are_answered.py::TestARefusedStepIsNotAlreadyHad::"
               "test_the_repeat_is_refused_with_its_reason_not_called_a_duplicate"],
    ),
    Control(
        describes="bench: asking for the id field is explained",
        path="core/agent/agentic_loop.py",
        old="        if id_field and id_field in unknown:",
        new="        if False:",
        tests=["tests/unit/test_bench_failures_are_answered.py::TestARefusedStepIsNotAlreadyHad::"
               "test_asking_for_the_id_field_says_the_ids_are_already_in_hand"],
    ),

    Control(
        describes="bench: a postponed finish is granted when its gap closes",
        path="core/agent/agentic_loop.py",
        old="            if finish_postponed and _detect_asymmetry(gathered) is None:",
        new="            if False:",
        tests=["tests/unit/test_bench_failures_are_answered.py::TestThePostponedFinish::test_the_finish_it_asked_for_is_granted_once_the_gap_is_closed"],
    ),
    Control(
        describes="bench: only a genuine finish is resumed",
        path="core/agent/agentic_loop.py",
        old="                finish_postponed = not already_nudged and fallback is None",
        new="                finish_postponed = not already_nudged",
        tests=["tests/unit/test_bench_failures_are_answered.py::TestThePostponedFinish::test_a_finish_fabricated_from_an_unusable_reply_is_not_resumed"],
    ),

    Control(
        describes="AR-5: Ollama receives the step schema",
        path="adapters/ollama_adapter.py",
        old='            payload["format"] = json_mode if isinstance(json_mode, dict) else "json"',
        new='            payload["format"] = "json"',
        tests=["tests/unit/test_step_schema.py::TestItReachesTheServer::test_ollama_sends_the_schema_as_format"],
    ),
    Control(
        describes="AR-5: a filter value is one scalar",
        path="core/llm/step_schema.py",
        old='_SCALAR = {"type": ["string", "number", "integer", "boolean"]}',
        new='_SCALAR = {"type": ["string", "number", "integer", "boolean", "array"]}',
        tests=["tests/unit/test_step_schema.py::TestWhatTheBenchsModelSentCannotBeSent::test_refused_by_the_grammar[list-filter]"],
    ),
    Control(
        describes="AR-5: each type's fields belong to that type",
        path="core/llm/step_schema.py",
        old='    this_type = {"const": object_type}',
        new='    this_type = {"type": "string"}',
        tests=["tests/unit/test_step_schema.py::TestWhatTheBenchsModelSentCannotBeSent::test_a_field_of_another_type_is_refused"],
    ),
    Control(
        describes="AR-5: next_step sends the schema when constrained",
        path="core/llm/agent_step_prompt.py",
        old="                           if constrain else True),",
        new="                           if False else True),",
        tests=["tests/unit/test_step_schema.py::TestItReachesTheServer::test_next_step_passes_a_schema_only_when_constrained"],
    ),

    Control(
        describes="AR-5: a plan is no longer than the hop limit",
        path="core/llm/step_schema.py",
        old='                                "minItems": 1, "maxItems": max_steps}},',
        new='                                "minItems": 1}},',
        tests=["tests/unit/test_step_schema.py::TestThePlanSchema::test_a_plan_longer_than_the_hop_limit_is_refused"],
    ),
    Control(
        describes="AR-5: a handle inside a list is refused",
        path="core/llm/step_schema.py",
        old='                                                                 "items": _PLAN_ID,',
        new='                                                                 "items": _ID,',
        tests=["tests/unit/test_step_schema.py::TestThePlanSchema::test_a_wrapped_handle_is_refused"],
    ),

    Control(
        describes="AR-5: a date filter is ISO-8601",
        path="core/llm/step_schema.py",
        old="    return _TEMPORAL if data_type in _TEMPORAL_TYPES else _SCALAR",
        new="    return _SCALAR",
        tests=["tests/unit/test_step_schema.py::TestWhatTheBenchsModelSentCannotBeSent::test_a_date_that_is_not_iso_is_refused"],
    ),
    Control(
        describes="AR-5: group_by is a data field",
        path="core/llm/step_schema.py",
        old='        aggregate["group_by"] = _enum(data)',
        new='        aggregate["group_by"] = _enum(list(fields))',
        tests=["tests/unit/test_step_schema.py::TestWhatTheBenchsModelSentCannotBeSent::test_a_link_is_not_something_to_group_by"],
    ),

    Control(
        describes="R12: a removed label comes off the table",
        path="core/mirror/classifications.py",
        old="                        tx.remove_properties(CLASSIFICATIONS_PROPERTY)",
        new="                        pass",
        tests=["tests/unit/test_classifications_propagate.py::TestTheRealSyncRecordsThem::test_a_label_removed_from_the_ontology_comes_off_every_table"],
    ),
    Control(
        describes="R12: the sync records the labels",
        path="scripts/run_sync.py",
        old="        relabelled = record_classifications(sync._catalog, config.schema)",
        new="        relabelled = []",
        tests=["tests/unit/test_classifications_propagate.py::TestTheRealSyncRecordsThem::test_the_shipped_labels_reach_bronze_silver_and_gold"],
    ),
    Control(
        describes="R12: a many-field column carries the union",
        path="core/mirror/classifications.py",
        old='        _merge(by_table.setdefault(f"{_GOLD_HISTORY}.{object_type}", {}), "values", everything)',
        new='        pass',
        tests=["tests/unit/test_classifications_propagate.py::TestWhereTheLabelsGo::test_a_column_holding_any_field_s_values_carries_every_label"],
    ),
    Control(
        describes="R12: a bad label stops the ontology loading",
        path="core/ontology/object_type_validation.py",
        old="            validate_field_classification(object_type_name, field_name, field_info)",
        new="            pass",
        tests=["tests/unit/test_classifications_propagate.py::TestWhatALabelMayBe::test_a_bad_label_stops_the_ontology_loading"],
    ),

    Control(
        describes="a JSON reply is capped",
        path="adapters/ollama_adapter.py",
        old="        if json_mode and \"num_predict\" not in options and self.json_num_predict:",
        new="        if False:",
        tests=["tests/unit/test_ollama_adapter.py::TestAJsonReplyIsCapped::test_a_json_call_is_capped"],
    ),

    Control(
        describes="R8: declared standardisation is told apart from a fault",
        path="core/mirror/reconcile.py",
        old="            if as_standardised == gold_comparable:",
        new="            if False:",
        tests=["tests/unit/test_reconcile_against_the_source.py::TestTheComparison::test_declared_standardisation_is_expected_not_a_fault"],
    ),
    Control(
        describes="R8: a row only in gold is found",
        path="core/mirror/reconcile.py",
        old="    result.only_in_gold = sorted(set(gold_by_id) - set(source_by_id))",
        new="    result.only_in_gold = []",
        tests=["tests/unit/test_reconcile_against_the_source.py::TestAgainstARealSourceAndARealSync::test_changes_behind_the_mirror_are_found_exactly"],
    ),
    Control(
        describes="R8: a difference fails the run",
        path="scripts/reconcile.py",
        old="    return 0 if all(result.clean or result.skipped for result in results) else 1",
        new="    return 0",
        tests=["tests/unit/test_reconcile_against_the_source.py::TestAgainstARealSourceAndARealSync::test_changes_behind_the_mirror_are_found_exactly"],
    ),

    Control(
        describes="R66: run_sync carries --accept-deletions to gold",
        path="scripts/run_sync.py",
        old="                                 unsynced=unsynced, run_id=run_id, accepted=accepted,",
        new="                                 unsynced=unsynced, run_id=run_id,",
        tests=["tests/unit/test_accept_deletions_reaches_gold.py::test_the_accepted_deletion_reaches_the_reader"],
    ),
    Control(
        describes="R66: gold honours an accepted deletion",
        path="core/mirror/gold.py",
        old="        previous_count = None if accept_deletions else len(published_now)",
        new="        previous_count = len(published_now)",
        tests=["tests/unit/test_a_source_changes_and_what_a_reader_sees.py::"
               "TestAChangeTheMirrorRefuses::test_AND_GOLD_TOO_SO_THE_READER_SEES_IT"],
    ),
    Control(
        describes="R66: an identity-resolved type needs every source accepted",
        path="scripts/run_sync.py",
        old="    if type_def.get(\"identity\"):",
        new="    if False:",
        tests=["tests/unit/test_a_source_changes_and_what_a_reader_sees.py::"
               "TestWhichTablesLicenseAType::test_an_identity_resolved_type_needs_every_source"],
    ),

    Control(
        describes="R64: the agent's aggregate hears the scan was cut",
        path="core/agent/agentic_loop.py",
        old=("        if outcome.scan_truncated:\n"
             "            grouped = _what_a_truncated_aggregate_may_say(step, grouped)"),
        new="        pass",
        tests=["tests/unit/test_a_short_count_never_reaches_the_model.py::"
               "TestTheAgent::test_a_short_count_is_a_lower_bound",
               "tests/unit/test_a_short_count_never_reaches_the_model.py::"
               "TestTheAgent::test_a_short_sum_is_refused_with_what_to_do"],
    ),
    Control(
        describes="R64: a function gets no short number",
        path="core/functions/ontology_access.py",
        old="    if outcome.scan_truncated:\n        raise ValueError(",
        new="    if False:\n        raise ValueError(",
        tests=["tests/unit/test_a_short_count_never_reaches_the_model.py::"
               "TestAFunction::test_a_short_count_is_refused"],
    ),

    Control(
        describes="R65: the notifications read checks the sync is running",
        path="api/routes.py",
        old="    _check_the_sync_is_running(request, current_user, store)\n",
        new="",
        tests=["tests/integration/test_the_sync_is_watched.py::test_an_administrator_is_told_when_the_sync_stopped"],
    ),
    Control(
        describes="R65: once per lapse",
        path="core/mirror/health_condition.py",
        old="    if summary is None or store.already_notified(_OVERDUE_KEY, user_id, summary):",
        new="    if summary is None:",
        tests=["tests/integration/test_the_sync_is_watched.py::test_once_per_lapse_however_often_the_client_polls"],
    ),
    Control(
        describes="R65: only somebody who can fix it is told",
        path="api/routes.py",
        old="    if not authorize(user, config.roles, RECIPIENT_GRANT):\n        return",
        new="    if False:\n        return",
        tests=["tests/integration/test_the_sync_is_watched.py::test_somebody_who_cannot_fix_it_is_not_told"],
    ),

    Control(
        describes="R67a: a fill from a less-preferred source is recorded",
        path="core/mirror/survivorship.py",
        old="                    if passed_over is not None:\n                        fused.conflicts.append(",
        new="                    if False:\n                        fused.conflicts.append(",
        tests=["tests/unit/test_survivorship.py::TestChoosingAValue::"
               "test_a_fill_from_a_less_preferred_source_is_recorded"],
    ),

    Control(
        describes="R7: a column going empty is drift",
        path="core/mirror/profiles.py",
        old="        if null_now - null_then > NULL_RISE:",
        new="        if False:",
        tests=["tests/unit/test_column_drift.py::TestTheRules::test_a_column_going_empty_is_drift"],
    ),
    Control(
        describes="R7: a collapse in distinct values is drift",
        path="core/mirror/profiles.py",
        old="            if abs(ratio - 1) > DISTINCT_CHANGE:",
        new="            if False:",
        tests=["tests/unit/test_column_drift.py::TestTheRules::test_a_collapse_in_distinct_values_is_drift",
               "tests/unit/test_column_drift.py::TestARealSync::test_a_column_that_collapsed_is_reported"],
    ),
    Control(
        describes="R7: a shifted average is drift",
        path="core/mirror/profiles.py",
        old="            if sigmas > MEAN_SIGMAS:",
        new="            if False:",
        tests=["tests/unit/test_column_drift.py::TestTheRules::test_a_shifted_average_is_drift"],
    ),

    Control(
        describes="R11: a young orphan is spared",
        path="core/mirror/integrity.py",
        old="                    if path.name not in live and path.stat().st_mtime < cutoff]",
        new="                    if path.name not in live]",
        tests=["tests/unit/test_orphan_files_are_reclaimed.py::test_a_young_orphan_is_left_alone"],
    ),
    Control(
        describes="R11: a dry run deletes nothing",
        path="scripts/remove_orphan_files.py",
        old="            if write:\n",
        new="            if True:\n",
        tests=["tests/unit/test_orphan_files_are_reclaimed.py::test_a_dry_run_reports_and_deletes_nothing"],
    ),
    Control(
        describes="R11: nothing is swept during a sync",
        path="scripts/remove_orphan_files.py",
        old="        if not acquired:\n",
        new="        if False:\n",
        tests=["tests/unit/test_orphan_files_are_reclaimed.py::test_nothing_is_touched_while_a_sync_holds_the_lock"],
    ),

    Control(
        describes="R10: an update carries its before-image",
        path="core/mirror/changelog.py",
        old="            if before_images:\n                rows.append({**was, \"_change\": UPDATE_BEFORE})",
        new="            if False:\n                rows.append({**was, \"_change\": UPDATE_BEFORE})",
        tests=["tests/unit/test_changelog.py::TestBeforeImages::test_an_update_carries_where_the_row_came_from"],
    ),
    Control(
        describes="R10: the sync asks for before-images",
        path="core/mirror/iceberg_sync.py",
        old="                                      before_images=True)",
        new="                                      before_images=False)",
        tests=["tests/unit/test_history_of_a_source_row.py::"
               "test_a_renamed_customer_has_two_versions_and_one_is_current"],
    ),
    Control(
        describes="R10: an unseen start is unknown, not invented",
        path="core/mirror/changelog.py",
        old='                version = {**values, "_valid_from": None, "_valid_to": at, "_current": False}',
        new='                version = {**values, "_valid_from": at, "_valid_to": at, "_current": False}',
        tests=["tests/unit/test_changelog.py::TestTheChangelogAsSCD2::"
               "test_a_row_older_than_the_changelog_has_an_unknown_start"],
    ),

    Control(
        describes="R13: the unreferenced files are deleted",
        path="core/mirror/erasure.py",
        old="        for path in files:\n            path.unlink()\n    return removed",
        new="        pass\n    return removed",
        tests=["tests/unit/test_erasure.py::TestErasing::test_nothing_on_disk_holds_them_afterwards"],
    ),
    Control(
        describes="R13: older snapshots and tags are dropped",
        path="core/mirror/erasure.py",
        old="            _forget_every_other_snapshot(catalog.load_table(identifier))",
        new="            pass",
        tests=["tests/unit/test_erasure.py::TestErasing::test_nothing_on_disk_holds_them_afterwards"],
    ),
    Control(
        # THE BATCHED READ, which every normal sync takes. This control
        # was anchored on the FALLBACK read below until 14 Oct and was
        # silent: it broke a path the test never took.
        describes="R13: a sync drops erased rows on the way in",
        path="core/mirror/iceberg_sync.py",
        old="            if suppression is not None:\n                from core.mirror.erasure import suppress_rows",
        new="            if False:\n                from core.mirror.erasure import suppress_rows",
        tests=["tests/unit/test_erasure.py::TestErasing::test_while_the_source_still_returns_them_every_sync_drops_them"],
    ),
    Control(
        describes="R13: the fallback read (bronze could not be written) drops erased rows too",
        path="core/mirror/iceberg_sync.py",
        old="        if suppression is not None:\n            from core.mirror.erasure import suppress_rows",
        new="        if False:\n            from core.mirror.erasure import suppress_rows",
        tests=["tests/unit/test_erasure.py::TestBothReadPathsSuppress::test_the_fallback_read_drops_erased_keys_too"],
    ),
    Control(
        describes="R13: a restore keeps the newer register",
        path="scripts/restore_deployment.py",
        old="    kept = aside / \"erasures.db\"\n    if kept.exists():",
        new="    kept = aside / \"erasures.db\"\n    if False:",
        tests=["tests/unit/test_erasure.py::TestARestore::test_the_register_is_the_newer_one",
               "tests/unit/test_erasure.py::TestARestore::test_an_older_backup_does_not_bring_them_back"],
    ),
    Control(
        describes="R13: the cascade reaches what links to the person",
        path="core/mirror/erasure.py",
        old="        frontier = found - erased",
        new="        frontier = set()",
        tests=["tests/unit/test_erasure.py::TestErasing::test_a_dry_run_counts_and_changes_nothing",
               "tests/unit/test_erasure.py::TestErasing::test_nothing_on_disk_holds_them_afterwards"],
    ),

    Control(
        describes="R13: the server refuses a lake with unapplied erasures",
        path="api/app.py",
        old="        if ErasureRegister(erasures_db).unpurged():",
        new="        if False:",
        tests=["tests/unit/test_erasure.py::test_the_server_will_not_serve_a_lake_with_unapplied_erasures"],
    ),

    Control(
        describes="R67b: only fields the caller was shown are described",
        path="api/routes.py",
        old="        [name for name, value in fields.items() if value is not None])",
        new="        list(fields))",
        tests=["tests/integration/test_the_object_page_says_what_is_overlaid.py::"
               "test_an_object_outside_the_compartment_says_nothing"],
    ),
    Control(
        describes="R67b: a pending approved write is named",
        path="core/ontology/mediator.py",
        old='            if field_name in pending:\n                found[field_name] = "pending"',
        new='            if False:\n                found[field_name] = "pending"',
        tests=["tests/unit/test_an_overlaid_value_says_so.py::"
               "test_an_approved_write_still_being_applied_is_pending"],
    ),

    Control(
        describes="a declared standardisation resolves on the frozen schema",
        path="core/mirror/standardise.py",
        old="    if not isinstance(declared, Mapping):",
        new="    if not isinstance(declared, dict):",
        tests=["tests/unit/test_declared_rules_survive_the_frozen_schema.py::"
               "test_a_declared_standardisation_resolves_on_a_frozen_schema"],
    ),
    Control(
        describes="R20: the preview reports values that would change",
        path="scripts/preview_ontology.py",
        old="                if differing:\n",
        new="                if False:\n",
        tests=["tests/unit/test_preview_an_ontology_change.py::"
               "test_a_change_to_values_is_reported_and_nothing_live_changes"],
    ),

    Control(
        describes="B6: a labelled field needs its label",
        path="core/ontology/classifications.py",
        old="                elif field_grant in grants:\n                    grants.discard(field_grant)",
        new="                elif False:\n                    grants.discard(field_grant)",
        tests=["tests/unit/test_labels_decide_field_access.py::TestTheRule::test_a_labelled_field_needs_its_label_whatever_was_granted_by_name",
               "tests/unit/test_labels_decide_field_access.py::TestThroughTheRealMediator::test_on_a_labelled_field_is_withheld_without_its_label"],
    ),
    Control(
        describes="B6: a label never opens a type",
        path="core/ontology/classifications.py",
        old=("            if f\"read:{object_type}\" not in grants:\n"
             "                continue\n            for field_name, info"),
        new="            if False:\n                continue\n            for field_name, info",
        tests=["tests/unit/test_labels_decide_field_access.py::TestTheRule::test_a_label_never_opens_a_type"],
    ),
    Control(
        describes="B6: the mediators decide with the compiled roles",
        path="core/deployment_loader.py",
        old="    if config.label_enforcement:\n        from core.ontology.classifications import compile_label_access",
        new="    if False:\n        from core.ontology.classifications import compile_label_access",
        tests=["tests/unit/test_labels_decide_field_access.py::TestThroughTheRealMediator::test_on_a_labelled_field_is_withheld_without_its_label"],
    ),
    Control(
        describes="B6: a label grant must name a label in use",
        path="core/intermediate_layer/policy_validation.py",
        old="        if label not in declared:",
        new="        if False:",
        tests=["tests/unit/test_labels_decide_field_access.py::TestTheGrantItself::test_a_label_nothing_carries_is_refused"],
    ),

    Control(
        describes="R15: every child run names the sync run as its parent",
        path="core/mirror/openlineage.py",
        old="        if parent and job != RUN_JOB:",
        new="        if False:",
        tests=["tests/unit/test_openlineage_events.py::TestWhatASyncEmits::test_every_child_names_the_run_as_its_parent"],
    ),
    Control(
        describes="R15: a gold type that started also finishes",
        path="scripts/run_sync.py",
        old="            lineage.emit(FAIL if failed else COMPLETE, f\"gold.{object_type}\",",
        new="            lineage.emit(FAIL if failed else START, f\"gold.{object_type}\",",
        tests=["tests/unit/test_openlineage_events.py::TestWhatASyncEmits::test_every_job_that_started_finished_with_the_same_run_id"],
    ),
    Control(
        describes="R15: a failing service warns once, naming the kind not the message",
        path="core/mirror/openlineage.py",
        old="({type(exc).__name__})",
        new="({exc})",
        tests=["tests/unit/test_openlineage_events.py::TestTheEmitter::test_a_failing_service_warns_once_and_the_file_still_has_everything"],
    ),
    Control(
        describes="R15: an unknown lineage key is refused",
        path="core/mirror/openlineage.py",
        old="    if unknown:\n        raise ValueError(f\"config.yaml lineage:",
        new="    if False:\n        raise ValueError(f\"config.yaml lineage:",
        tests=["tests/unit/test_openlineage_events.py::TestTheConfigBlock::test_a_mistake_is_refused_at_load"],
    ),
    Control(
        describes="R16: a reverse link is not a column of the contract",
        path="core/mirror/data_contracts.py",
        old="        if info.get(\"type\") == \"link\" and is_reverse_link(info):\n            continue",
        new="        if False:\n            continue",
        tests=["tests/unit/test_data_contracts.py::TestTheMapping::test_a_reverse_link_is_not_a_column"],
    ),
    Control(
        describes="R16: a decimal is promised at the scale gold writes",
        path="core/mirror/data_contracts.py",
        old="        physical = f\"decimal({DECIMAL_PRECISION}, {DECIMAL_SCALE})\"",
        new="        physical = \"decimal(38, 2)\"",
        tests=["tests/unit/test_data_contracts.py::TestTrueOfWhatGoldWrote::test_every_column_and_type_the_contract_promises_is_in_gold"],
    ),
    Control(
        describes="R16: the contract version is a digest of the declaration",
        path="core/mirror/data_contracts.py",
        old="    canonical = json.dumps(_plain(type_def), sort_keys=True, default=str)",
        new="    canonical = \"fixed\"",
        tests=["tests/unit/test_data_contracts.py::TestTheMapping::test_the_version_changes_with_the_declaration_and_only_then"],
    ),
    Control(
        describes="R16: a data contract requires manage:users",
        path="api/routes.py",
        old=("    _require_manage_users(request, current_user)\n    config = _generation(request).config\n"
             "    if object_type not in"),
        new="    config = _generation(request).config\n    if object_type not in",
        tests=["tests/integration/test_api.py::test_a_data_contract_requires_manage_users"],
    ),
    Control(
        describes="R38: survivorship records which source won each field",
        path="core/mirror/survivorship.py",
        old="            if chosen_source is not None:\n                field_sources[field_name] = chosen_source",
        new="            if False:\n                field_sources[field_name] = chosen_source",
        tests=["tests/unit/test_which_source_supplied_each_value.py::TestThroughARealBuild::test_every_value_names_the_source_that_supplied_it"],
    ),
    Control(
        describes="R38: a null value names no source",
        path="core/mirror/fusion.py",
        old="                if fused_row[field_name] is not None:",
        new="                if True:",
        tests=["tests/unit/test_which_source_supplied_each_value.py::TestTheJoinPath::test_a_null_or_an_absent_storage_supplied_nothing"],
    ),
    Control(
        describes="R38: per-field sources are withheld outside the caller's compartment",
        path="api/routes.py",
        old=("        if not _may_read_object(mediator, current_user, object_type, object_id):\n"
             "            provenance[\"field_sources\"] = None"),
        new="        if False:\n            provenance[\"field_sources\"] = None",
        tests=["tests/integration/test_the_provenance_route.py::TestWhichSourceSuppliedEachValue::test_the_field_from_the_second_silo_says_so"],
    ),
    Control(
        describes="R38: a field the caller cannot read is not named",
        path="api/routes.py",
        old="                if name in readable}",
        new="                if True}",
        tests=["tests/integration/test_the_provenance_route.py::TestWhichSourceSuppliedEachValue::test_a_field_the_caller_cannot_read_is_not_named"],
    ),
    Control(
        describes="B3: no PostgreSQL fails the suite, never skips it",
        path="tests/postgres_server.py",
        old="        pytest.fail(NONE_AVAILABLE, pytrace=False)",
        new="        pytest.skip(NONE_AVAILABLE)",
        tests=["tests/unit/test_postgres_is_never_silently_skipped.py::"
               "test_with_no_postgresql_at_all_it_fails_and_says_what_to_install"],
    ),
    Control(
        describes="ZOO-11: a quarantined row names the cell that failed, not the table's first",
        path="core/mirror/iceberg_sync.py",
        old="                failed = transformed.mismatched_cells.get(index) or [",
        new="                failed = [",
        tests=["tests/unit/test_one_bad_cell_does_not_stop_a_table.py::"
               "TestTheQuarantineRecordNamesTheCellThatFailed::test_each_row_names_its_own_failing_column"],
    ),
    Control(
        describes="ZOO-24: a declared casefold folds the identity key",
        path="core/mirror/identity.py",
        old="        values.append(key.casefold() if field_name in rule.casefold else key)",
        new="        values.append(key)",
        tests=["tests/unit/test_identity_resolution.py::TestADeclaredCasefold::"
               "test_declared_the_two_spellings_are_one_entity"],
    ),
    Control(
        describes="F-24: an over-long system prompt is refused before the CLI starts",
        path="adapters/claude_agent_sdk_adapter.py",
        old="        if size >= MAX_ARGUMENT_BYTES:",
        new="        if False:",
        tests=["tests/unit/test_claude_agent_sdk_adapter.py::"
               "test_a_prompt_past_the_argument_limit_is_refused_by_name"],
    ),
    Control(
        describes="ZOO-11: a new deployment from the template quarantines rows",
        path="templates/config.yaml",
        old="on_type_mismatch: quarantine",
        new="# on_type_mismatch: quarantine",
        tests=["tests/unit/test_template_is_a_valid_deployment.py::"
               "test_a_new_deployment_starts_on_the_new_installation_defaults"],
    ),
    Control(
        describes="DEP-1: a number the database typed is never read through the locale",
        path="core/mirror/iceberg_sync.py",
        old="                    if column not in text_columns and any(issubclass(kind, str) for kind in kinds):",
        new="                    if column not in text_columns:",
        tests=["tests/unit/test_numbers_and_dates_as_sources_write_them.py::TestThroughARealSync::test_a_number_the_database_typed_is_never_read_through_the_locale"],
    ),
    Control(
        describes="DEP-1: grouping is strict, so 1.5 under pt_BR is refused, not fifteen",
        path="core/ontology/localised_values.py",
        old="        return parse_decimal(stripped, locale=locale, strict=True)",
        new="        return parse_decimal(stripped, locale=locale, strict=False)",
        tests=["tests/unit/test_numbers_and_dates_as_sources_write_them.py::TestTheRules::test_what_is_refused_rather_than_guessed"],
    ),
    Control(
        describes="DEP-1: a two-digit year is refused",
        path="core/ontology/localised_values.py",
        old="    if len(by_letter[\"Y\"]) != 4:",
        new="    if False:",
        tests=["tests/unit/test_numbers_and_dates_as_sources_write_them.py::TestTheRules::test_what_is_refused_rather_than_guessed"],
    ),
    Control(
        describes="DEP-1: a silo's own locale overrides the deployment's",
        path="core/deployment_loader.py",
        old="        if \"locale\" in (silo or {}):",
        new="        if False:",
        tests=["tests/unit/test_numbers_and_dates_as_sources_write_them.py::TestTheDeclaration::test_a_silo_overrides_the_deployment"],
    ),
    Control(
        describes="Live: a hint reaches only a caller who may know the type exists",
        path="api/live_updates.py",
        old="            for allowed in hints_for(visible_schema, [object_type]):",
        new="            for allowed in [object_type]:",
        tests=["tests/integration/test_live_updates.py::test_a_type_the_caller_may_not_know_exists_is_never_mentioned"],
    ),
    Control(
        describes="Live: only a write that was applied is announced",
        path="api/routes.py",
        old="    if outcome is not None and outcome.get(\"status\") == \"written\":",
        new="    if True:",
        tests=["tests/integration/test_live_updates.py::test_a_rejected_write_tells_nobody"],
    ),
    Control(
        describes="Live: following a publication rebuilds from the running configuration, not disk",
        path="api/reload.py",
        old=("            new = build_generation(scratch, app.state.runtime_paths.data_dir,\n"
             "                                   app.state.runtime_paths.log_dir)"),
        new=("            new = build_generation(app.state.runtime_paths.config_dir,\n"
             "                                   app.state.runtime_paths.data_dir,\n"
             "                                   app.state.runtime_paths.log_dir)"),
        tests=["tests/integration/test_live_updates.py::test_following_a_publication_never_applies_an_unreloaded_edit"],
    ),
    Control(
        describes="Live: a new publication is served without a restart",
        path="api/reload.py",
        old=("        app.state.generation = new\n"
             "        record_generation(app.state.config_history, new)\n        current.mediator"),
        new="        record_generation(app.state.config_history, new)\n        current.mediator",
        tests=["tests/integration/test_live_updates.py::test_a_new_publication_is_served_without_a_restart"],
    ),
    Control(
        describes="Help: the assistant is told the caller's visible schema, not the whole ontology",
        path="api/routes.py",
        old="    context = build_context(screens, visible, grants, screen)",
        new="    context = build_context(screens, generation.mediator.schema, grants, screen)",
        tests=["tests/integration/test_help_assistant.py::test_it_is_told_only_what_the_caller_may_know"],
    ),
    Control(
        describes="Help: a screen the caller cannot open is not passed on",
        path="api/routes.py",
        old="    screen = body.screen if body.screen in {app[\"name\"] for app in screens} else None",
        new="    screen = body.screen",
        tests=["tests/integration/test_help_assistant.py::test_a_screen_the_caller_cannot_open_is_not_named_as_theirs"],
    ),
    Control(
        describes="Help: a field known but unreadable is described as hidden",
        path="core/agent/help_assistant.py",
        old="            hidden = \"\" if field.get(\"readable\", True) else \", value hidden\"",
        new="            hidden = \"\"",
        tests=["tests/integration/test_help_assistant.py::test_a_field_known_but_unreadable_says_so"],
    ),
    Control(
        describes="Help: an unreachable model never shows its address",
        path="api/routes.py",
        old="            detail=\"The help assistant cannot reach its model right now. Try again later, \"",
        new="            detail=str(e) + \"The help assistant cannot reach its model right now. Try again later, \"",
        tests=["tests/integration/test_help_assistant.py::test_an_unreachable_model_is_a_503_that_says_so"],
    ),
    Control(
        describes="ZOO-15: an exactly whole exponent-form value is an integer",
        path="core/ontology/field_types.py",
        old="    if isinstance(value, str) and _SCIENTIFIC.match(value.strip()):",
        new="    if False:",
        tests=["tests/unit/test_numbers_and_dates_as_sources_write_them.py::TestExponentFormIntegers::test_an_exactly_whole_one_loads"],
    ),
    Control(
        describes="ZOO-22: a declared silo's Excel serials are dates",
        path="core/ontology/field_types.py",
        old="    if excel_dates and data_type in _TEMPORAL and _EXCEL_SERIAL.match(str(value).strip()):",
        new="    if False:",
        tests=["tests/unit/test_numbers_and_dates_as_sources_write_them.py::TestExcelDateSerials::test_through_a_real_sync"],
    ),
    Control(
        describes="AL-10: a spent token budget stops the next model call",
        path="core/agent/agentic_loop.py",
        old="            if (self.max_tokens_per_query and usage is not None",
        new="            if (False and usage is not None",
        tests=["tests/unit/test_a_question_has_a_token_budget.py::"
               "test_the_budget_stops_the_next_call_once_spent"],
    ),
    Control(
        describes="R29: a write breaking a rule between two fields is refused",
        path="core/ontology/write_mediator.py",
        old="            problems.extend(self._rule_violations(sub_write, declared))",
        new="            pass",
        tests=["tests/unit/test_rules_between_two_fields.py::TestOnAWrite::test_a_change_that_breaks_it_against_the_current_value_is_refused"],
    ),
    Control(
        describes="R29: an update is judged with the untouched side's current value",
        path="core/ontology/write_mediator.py",
        old="            if untouched and sub_write.operation == \"update\":",
        new="            if False:",
        tests=["tests/unit/test_rules_between_two_fields.py::TestOnAWrite::test_a_change_that_breaks_it_against_the_current_value_is_refused"],
    ),
    Control(
        describes="R29: silver applies the rule's declared policy",
        path="core/mirror/expectations.py",
        old="            reason = rule_violation(rule, expected[\"type_def\"], values)",
        new="            reason = None",
        tests=["tests/unit/test_rules_between_two_fields.py::TestInSilver::test_quarantine_holds_the_row_and_names_the_rule"],
    ),
    Control(
        describes="A field's declared timezone reaches the sync without other rules",
        path="core/mirror/sync_targets.py",
        old="        timezone_name = field_config.get(\"timezone\")",
        new="        timezone_name = None",
        tests=["tests/unit/test_declared_timezone.py::TestTheZoneReachesTheSync::"
               "test_a_field_with_no_other_rules_keeps_its_zone"],
    ),
    Control(
        describes="R4: a supported database is read as one snapshot",
        path="adapters/sqlalchemy_adapter.py",
        old="        isolation = SNAPSHOT_ISOLATION.get(self._engine.dialect.name)",
        new="        isolation = None",
        tests=["tests/unit/test_one_consistent_read_per_silo.py::test_a_write_between_two_reads_is_not_seen_inside_the_snapshot"],
    ),
    Control(
        describes="R4: a failed read inside the snapshot costs only that read",
        path="adapters/sqlalchemy_adapter.py",
        old=("                with pinned.begin_nested():\n"
             "                    return [dict(row) for row in pinned.execute(statement).mappings()]"),
        new="                return [dict(row) for row in pinned.execute(statement).mappings()]",
        tests=["tests/unit/test_one_consistent_read_per_silo.py::test_a_failed_read_does_not_poison_the_rest_of_the_snapshot"],
    ),
    Control(
        describes="R4: the run reads each silo's tables inside its snapshot",
        path="scripts/run_sync.py",
        old="            with _consistent_read(sync.adapters.get(silo_name)) as consistent:",
        new="            with _consistent_read(None) as consistent:",
        tests=["tests/unit/test_one_consistent_read_per_silo.py::test_the_run_opens_one_snapshot_per_silo_around_its_tables"],
    ),
    Control(
        describes="R5: the bronze write streams the source rather than gathering it",
        path="core/mirror/iceberg_sync.py",
        old="            for rows in itertools.chain(_drain(pending), batches):",
        new="            for rows in list(itertools.chain(_drain(pending), batches)):",
        tests=["tests/unit/test_sync_reads_in_batches.py::test_the_source_rows_are_not_kept_while_the_next_batch_is_read"],
    ),
    Control(
        describes="R5: bronze is cleaned a bounded batch at a time",
        path="core/mirror/iceberg_sync.py",
        old="                batch.to_pylist() for batch in bronze.to_batches(max_chunksize=SYNC_BATCH_ROWS))",
        new="                batch.to_pylist() for batch in bronze.to_batches())",
        tests=["tests/unit/test_sync_reads_in_batches.py::TestBatchingChangesNothingButTheCost::"
               "test_no_batch_larger_than_the_bound_reaches_the_clean_step"],
    ),
    Control(
        describes="R5: SQLite fetches the table in pieces",
        path="adapters/sqlite_adapter.py",
        old="        while batch := cursor.fetchmany(batch_size):",
        new="        while batch := cursor.fetchall():",
        tests=["tests/unit/test_sync_reads_in_batches.py::TestTheAdapterBatches::test_sqlite_yields_the_same_rows_in_bounded_pieces"],
    ),
    Control(
        describes="R5: streaming inside the snapshot leaves the savepoint's RELEASE alone",
        path="adapters/sqlalchemy_adapter.py",
        old="                    result = pinned.execute(statement)",
        new=("                    result = pinned.execution_options(stream_results=True)"
             ".execute(statement)"),
        tests=["tests/unit/test_sqlalchemy_adapter.py::TestItStreamsTheTable::"
               "test_inside_a_consistent_read_it_streams_the_snapshot"],
    ),
    Control(
        describes="R5: merged batches number their bad rows as one table",
        path="core/mirror/transform.py",
        old="        mismatched.extend(offset + index for index in result.mismatched_row_indices)",
        new="        mismatched.extend(index for index in result.mismatched_row_indices)",
        tests=["tests/unit/test_sync_reads_in_batches.py::TestTransformBatchesIsTransformRows::test_the_merged_result_is_the_unbatched_one"],
    ),
    Control(
        describes="R5: merged batches report each column's FIRST bad value",
        path="core/mirror/transform.py",
        old="            drift.setdefault(item.column, item)",
        new="            drift[item.column] = item",
        tests=["tests/unit/test_sync_reads_in_batches.py::TestTransformBatchesIsTransformRows::test_the_merged_result_is_the_unbatched_one"],
    ),
    Control(
        describes="R5: the Arrow diff treats a null beside a value as a change",
        path="core/mirror/changelog.py",
        old="            equal = pc.fill_null(pc.equal(x, y), False)",
        new="            equal = pc.fill_null(pc.equal(x, y), True)",
        tests=["tests/unit/test_changelog_diff_in_arrow.py::test_randomised_snapshots_give_the_same_changes"],
    ),
    Control(
        describes="R5: the Arrow diff treats a changed set of columns as an update",
        path="core/mirror/changelog.py",
        old="    same_columns = set(previous.column_names) == set(current.column_names)",
        new="    same_columns = True",
        tests=["tests/unit/test_changelog_diff_in_arrow.py::test_randomised_snapshots_give_the_same_changes"],
    ),
    Control(
        describes="R5: the changelog is diffed in Arrow, not as whole-table dicts",
        path="core/mirror/changelog.py",
        old=("        return dict(zip(indices, (_as_strings(row) for row in "
             "table.take(pa.array(indices)).to_pylist()),"),
        new=("        return dict(zip(indices, (_as_strings(row) for row in "
             "table.take(pa.array(indices[:1])).to_pylist()),"),
        tests=["tests/unit/test_changelog_diff_in_arrow.py::test_randomised_snapshots_give_the_same_changes"],
    ),
    Control(
        describes="R2: a declared table reads only the rows at or after its mark",
        path="core/mirror/iceberg_sync.py",
        old=("            if reason is None and policy is not None:\n"
             "                changed_since = (policy.cursor, read_from("),
        new="            if False:\n                changed_since = (policy.cursor, read_from(",
        tests=["tests/unit/test_incremental_sync.py::TestTheNextSyncReadsOnlyWhatChanged::"
               "test_a_change_and_an_insert_arrive_and_nothing_else_is_read"],
    ),
    Control(
        describes="R2: the boundary is inclusive",
        path="adapters/sqlite_adapter.py",
        old="WHERE {_q(cursor_column)} >= ?",
        new="WHERE {_q(cursor_column)} > ?",
        tests=["tests/unit/test_incremental_sync.py::TestTheNextSyncReadsOnlyWhatChanged::test_the_boundary_is_inclusive"],
    ),
    Control(
        describes="R2: changed rows are merged onto what bronze held",
        path="core/mirror/iceberg_sync.py",
        old="    return pa.concat_tables([kept, changed])",
        new="    return changed",
        tests=["tests/unit/test_incremental_sync.py::TestTheNextSyncReadsOnlyWhatChanged::"
               "test_a_change_and_an_insert_arrive_and_nothing_else_is_read"],
    ),
    Control(
        describes="R2: a changed row replaces bronze's row under its id",
        path="core/mirror/iceberg_sync.py",
        old="        previous = previous.filter(pc.invert(pc.fill_null(replaced, False)))",
        new="        pass",
        tests=["tests/unit/test_incremental_sync.py::TestTheNextSyncReadsOnlyWhatChanged::"
               "test_a_change_and_an_insert_arrive_and_nothing_else_is_read"],
    ),
    Control(
        describes="R2: the scheduled full read happens, and sees deletions",
        path="core/mirror/incremental.py",
        old="    if now - last_full >= policy.full_read_every:",
        new="    if False:",
        tests=["tests/unit/test_incremental_sync.py::TestADeletionWaitsForTheFullRead::test_the_scheduled_full_read_sees_it"],
    ),
    Control(
        describes="R2: a full read is recorded as one",
        path="core/mirror/iceberg_sync.py",
        old="    if was_full:\n        properties[FULL_READ_PROPERTY] = started.isoformat()",
        new="    if False:\n        properties[FULL_READ_PROPERTY] = started.isoformat()",
        tests=["tests/unit/test_incremental_sync.py::TestTheFirstSyncIsFull::test_it_reads_everything_and_records_the_mark"],
    ),
    Control(
        describes="R2: --full reads everything",
        path="core/mirror/incremental.py",
        old="    if force:\n        return \"a full read was asked for\"",
        new="    if False:\n        return \"a full read was asked for\"",
        tests=["tests/unit/test_incremental_sync.py::TestADeletionWaitsForTheFullRead::test_asking_for_a_full_read_sees_it"],
    ),
    Control(
        describes="R2: a changed cursor column forces a full read",
        path="core/mirror/incremental.py",
        old="    if properties.get(CURSOR_PROPERTY) != policy.cursor:",
        new="    if False:",
        tests=["tests/unit/test_incremental_sync.py::TestWhenAChangedRowsReadWouldBeWrong::test_a_new_cursor_column_reads_in_full"],
    ),
    Control(
        describes="R2: which columns arrived as text is carried across reads",
        path="core/mirror/iceberg_sync.py",
        old="                text_columns |= set(json.loads(",
        new="                text_columns |= set() & set(json.loads(",
        tests=["tests/unit/test_incremental_sync.py::TestWhatIsCarriedForward::test_a_locale_still_applies_to_rows_that_were_not_re_read"],
    ),
    Control(
        describes="R2: the mark keeps its type",
        path="core/mirror/incremental.py",
        old="        \"datetime\": datetime.fromisoformat, \"date\": date.fromisoformat, \"int\": int,",
        new="        \"datetime\": str, \"date\": date.fromisoformat, \"int\": int,",
        tests=["tests/unit/test_incremental_sync.py::TestTheMarkKeepsItsType::test_it_round_trips",
               "tests/unit/test_sqlalchemy_adapter.py::TestItReadsOnlyWhatChanged::"
               "test_the_mark_read_back_is_the_mark_sent"],
    ),
    Control(
        describes="R2: a join table cannot be declared incremental",
        path="core/deployment_loader.py",
        old="                if not target.link_pair}",
        new="                }",
        tests=["tests/unit/test_incremental_sync.py::TestTheDeclaration::test_a_join_table_cannot_be_declared"],
    ),
    Control(
        describes="R37: a role that cannot read an input cannot read the result",
        path="core/ontology/derived_fields.py",
        old="            if grant in allowed and not all(f\"read:{type_name}.{name}\" in allowed for name in inputs):",
        new="            if False:",
        tests=["tests/unit/test_derived_fields.py::TestWhoMayReadOne::test_a_role_that_cannot_read_an_input_cannot_read_the_result",
               "tests/unit/test_derived_fields.py::TestThroughARealDeployment::test_a_role_without_an_input_is_refused_the_result"],
    ),
    Control(
        describes="R37: the mediator's roles are the gated ones",
        path="core/deployment_loader.py",
        old="    gated = gate_derived_grants(roles, config.schema)",
        new="    gated = roles",
        tests=["tests/unit/test_derived_fields.py::TestThroughARealDeployment::test_a_role_without_an_input_is_refused_the_result"],
    ),
    Control(
        describes="R37: a read computes the value from its inputs",
        path="core/ontology/mediator.py",
        old="        if derivation is not None:\n            # COMPUTED FROM ITS INPUTS",
        new="        if False:\n            # COMPUTED FROM ITS INPUTS",
        tests=["tests/unit/test_derived_fields.py::TestThroughARealDeployment::"
               "test_a_change_waiting_to_sync_is_in_the_value_beside_it"],
    ),
    Control(
        describes="R37: gold stores the computed value",
        path="core/mirror/gold_arrow.py",
        old="    return with_derived(pa.Table.from_arrays(columns, names=names), type_def)",
        new="    return pa.Table.from_arrays(columns, names=names)",
        tests=["tests/unit/test_derived_fields.py::TestThroughARealDeployment::test_gold_holds_it_so_a_filter_finds_by_it"],
    ),
    Control(
        describes="R37: gold's dict path computes it too",
        path="core/mirror/gold.py",
        old="    return with_derived(pa.Table.from_pylist(",
        new="    return (lambda table, _type_def: table)(pa.Table.from_pylist(",
        tests=["tests/unit/test_derived_fields.py::test_gold_s_dict_path_computes_it_too"],
    ),
    Control(
        describes="R37: the sync does not ask a source for a derived column",
        path="core/mirror/sync_targets.py",
        old="        if is_computed(field_config):\n            # COMPUTED FROM OTHER FIELDS (R37)",
        new="        if False:\n            # COMPUTED FROM OTHER FIELDS (R37)",
        tests=["tests/unit/test_derived_fields.py::TestThroughARealDeployment::test_the_sync_never_asks_a_source_for_it"],
    ),
    Control(
        describes="R37: a derived field cannot be written",
        path="core/ontology/write_mediator.py",
        old="        if derived:\n            # COMPUTED, NOT STORED (R37, R41).",
        new="        if False:\n            # COMPUTED, NOT STORED (R37, R41).",
        tests=["tests/unit/test_derived_fields.py::TestThroughARealDeployment::test_it_cannot_be_written"],
    ),
    Control(
        describes="R37: an action that sets a derived field is refused at load",
        path="core/ontology/action_types.py",
        old="        if is_computed(object_types[object_type][\"fields\"].get(property_name) or {}):",
        new="        if False:",
        tests=["tests/unit/test_derived_fields.py::test_an_action_that_sets_a_derived_field_is_refused_at_load"],
    ),
    Control(
        describes="R37: an empty input is an empty result, not zero",
        path="core/ontology/derived_fields.py",
        old="    if left is None or right is None:\n        return None",
        new="    if left is None or right is None:\n        left, right = left or 0, right or 0",
        tests=["tests/unit/test_derived_fields.py::TestTheFormulas::test_an_empty_input_is_an_empty_result_not_zero"],
    ),
    Control(
        describes="R37: years_since counts a birthday not yet reached this year",
        path="core/ontology/derived_fields.py",
        old="        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))",
        new="        return today.year - born.year",
        tests=["tests/unit/test_derived_fields.py::TestTheFormulas::test_years_since_counts_whole_years"],
    ),
    Control(
        describes="R37: a decimal result is rounded to gold's scale",
        path="core/ontology/derived_fields.py",
        old="    if data_type == \"decimal\":\n        # ROUNDED BEFORE coerce()",
        new="    if False:\n        # ROUNDED BEFORE coerce()",
        tests=["tests/unit/test_derived_fields.py::TestTheFormulas::test_a_decimal_result_is_rounded_to_what_gold_stores"],
    ),
    Control(
        describes="R37: arithmetic is exact to what was typed, not binary float",
        path="core/ontology/derived_fields.py",
        old="        exact_left, exact_right = Decimal(str(left)), Decimal(str(right))",
        new="        exact_left, exact_right = Decimal(left), Decimal(right)",
        tests=["tests/unit/test_derived_fields.py::TestTheFormulas::"
               "test_float_arithmetic_is_exact_to_what_was_typed"],
    ),
    Control(
        describes="DEP-4: a phone number is checked against its region",
        path="core/ontology/value_checks.py",
        old="    return number if phonenumbers.is_valid_number(number) else None",
        new="    return number",
        tests=["tests/unit/test_reference_data_checks.py::TestPhoneNumbers::test_a_number_that_cannot_exist_is_refused_naming_the_region"],
    ),
    Control(
        describes="DEP-4: an email address is never checked by asking DNS",
        path="core/ontology/value_checks.py",
        old="        validate_email(str(value), check_deliverability=False)",
        new="        validate_email(str(value), check_deliverability=True)",
        tests=["tests/unit/test_reference_data_checks.py::TestEmailAddresses::test_never_by_asking_dns"],
    ),
    Control(
        describes="DEP-4: a holiday calendar includes the declared subdivision",
        path="core/ontology/value_checks.py",
        old="    return holidays.country_holidays(country, subdiv=subdivision or None)",
        new="    return holidays.country_holidays(country)",
        tests=["tests/unit/test_reference_data_checks.py::TestPublicHolidays::test_a_subdivision_has_its_own"],
    ),
    Control(
        describes="DEP-4: mojibake is repaired when declared",
        path="core/mirror/standardise.py",
        old="        step(\"fix_text\", fixed_text(value))",
        new="        pass",
        tests=["tests/unit/test_reference_data_checks.py::TestStandardisation::test_mojibake_is_repaired_before_anything_else"],
    ),
    Control(
        describes="DEP-4: a valid phone number takes its E.164 form in silver",
        path="core/ontology/value_checks.py",
        old="    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)",
        new="    return value",
        tests=["tests/unit/test_reference_data_checks.py::TestStandardisation::test_a_valid_phone_number_takes_its_one_international_form",
               "tests/unit/test_reference_data_checks.py::test_silver_tidies_and_holds_back_through_a_real_sync"],
    ),
    Control(
        describes="DEP-4: a declared email constraint holds a row back in silver",
        path="core/ontology/constraints.py",
        old="    if constraints.get(\"email\"):",
        new="    if False:",
        tests=["tests/unit/test_reference_data_checks.py::test_silver_tidies_and_holds_back_through_a_real_sync",
               "tests/unit/test_reference_data_checks.py::TestEmailAddresses::test_syntax_is_checked"],
    ),
    Control(
        describes="DEP-4: a holiday setting the library does not know is refused at load",
        path="core/ontology/value_checks.py",
        old="    if country not in supported:",
        new="    if False:",
        tests=["tests/unit/test_reference_data_checks.py::TestRefusedAtLoad::test_a_check_that_could_never_work"],
    ),
    Control(
        describes="DEP-2: hypothesis finds the two changelog diffs disagreeing",
        path="core/mirror/changelog.py",
        old="            equal = pc.fill_null(pc.equal(x, y), False)",
        new="            equal = pc.fill_null(pc.equal(x, y), True)",
        tests=["tests/unit/test_properties.py::test_the_arrow_diff_is_the_dict_diff"],
    ),
    Control(
        describes="DEP-2: hypothesis finds a mark that is not the largest value",
        path="core/mirror/incremental.py",
        old="        return candidate if candidate > current else current",
        new="        return candidate",
        tests=["tests/unit/test_properties.py::test_the_mark_is_the_largest_value_whatever_the_order",
               "tests/unit/test_incremental_sync.py::TestWhatMutationTestingFound::"
               "test_the_mark_is_the_highest_value_not_the_last_read"],
    ),
    Control(
        describes="DEP-2: hypothesis finds a mark that changes type when stored",
        path="core/mirror/incremental.py",
        old="    if isinstance(value, int):\n        return json.dumps({\"type\": \"int\", \"value\": value})",
        new="    if isinstance(value, int):\n        return json.dumps({\"type\": \"float\", \"value\": value})",
        tests=["tests/unit/test_properties.py::test_a_mark_comes_back_as_the_value_and_type_it_went_in_as"],
    ),
    Control(
        describes="DEP-2: hypothesis finds an age off by a birthday",
        path="core/ontology/derived_fields.py",
        old="        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))",
        new="        return today.year - born.year - ((today.month, today.day) <= (born.month, born.day))",
        tests=["tests/unit/test_properties.py::test_years_since_agrees_with_counting_birthdays"],
    ),
    Control(
        describes="LB-3: every early stop reaches synthesis as possibly incomplete",
        path="api/routes.py",
        old="            result.possibly_incomplete,",
        new="            result.hit_max_hops or result.ran_out_of_time or result.hit_token_budget,",
        tests=["tests/integration/test_api.py::test_every_early_stop_reaches_synthesis_as_possibly_incomplete"],
    ),
    Control(
        describes="PA001-F3: a whole number written with a point is read as an integer",
        path="core/ontology/field_types.py",
        old="    if isinstance(value, str) and _DECIMAL_POINT.match(value.strip()):",
        new="    if False:",
        tests=["tests/unit/test_whole_numbers_however_written.py::test_a_whole_number_is_read_however_it_is_written"],
    ),
    Control(
        describes="PA001-F3: a fractional value is refused, never truncated",
        path="core/ontology/field_types.py",
        old="        if value != int(value):\n            raise ValueError(f\"{value!r} is not a whole number.\")",
        new="        if False:\n            raise ValueError(f\"{value!r} is not a whole number.\")",
        tests=["tests/unit/test_whole_numbers_however_written.py::test_a_fraction_is_refused_not_truncated"],
    ),
    Control(
        describes="PA001-A13: a changelog entry names the bronze snapshot it was compared with",
        path="core/mirror/iceberg_sync.py",
        old="                                   compared_with=bronze_table.current_snapshot().snapshot_id)",
        new="                                   compared_with=None)",
        tests=["tests/unit/test_changelog_says_where_it_came_from.py::"
               "test_an_entry_names_its_bronze_snapshot_and_its_run"],
    ),
    Control(
        describes="R3: bronze records how each column's text decodes",
        path="core/mirror/iceberg_sync.py",
        old="                    arrived[column] |= kinds",
        new="                    pass",
        tests=["tests/unit/test_bronze_round_trip.py::test_the_encodings_are_recorded_per_column"],
    ),
    Control(
        describes="R3: a column that arrived as two types decodes as its text, never a guess",
        path="core/mirror/bronze_text.py",
        old="    return next(iter(names)) if len(names) == 1 else MIXED",
        new="    return sorted(names)[0]",
        tests=["tests/unit/test_bronze_round_trip.py::test_the_encodings_are_recorded_per_column"],
    ),
    Control(
        describes="R3: a changed-rows read keeps the encodings bronze already knew",
        path="core/mirror/iceberg_sync.py",
        old="                        if changed_since is not None else {}), sort_keys=True),",
        new="                        if False else {}), sort_keys=True),",
        tests=["tests/unit/test_bronze_round_trip.py::test_a_changed_rows_read_keeps_what_bronze_already_knew"],
    ),
    Control(
        describes="R3: hypothesis finds a value bronze cannot give back",
        path="core/mirror/bronze_text.py",
        old="        return -value if match.group(1) else value",
        new="        return value",
        tests=["tests/unit/test_properties.py::test_bronze_text_decodes_to_the_value_it_was_given"],
    ),
    Control(
        describes="R18: a type in a link cycle may link to what its partner publishes this run",
        path="scripts/run_sync.py",
        old="                known[partner] = set(known.get(partner) or ()) | coming",
        new="                pass",
        tests=["tests/unit/test_gold_builds_targets_first.py::TestALinkCycle::test_a_new_pair_pointing_at_each_other_publishes_together"],
    ),
    Control(
        describes="R18: a cycle partner that did not publish is named",
        path="scripts/run_sync.py",
        old="    for partner in sorted(not_published & set(leaned_on)):",
        new="    for partner in sorted(set()):",
        tests=["tests/unit/test_gold_builds_targets_first.py::TestALinkCycle::test_a_partner_that_is_refused_is_named"],
    ),
    Control(
        describes="R29: silver checks functional dependencies across rows",
        path="core/mirror/expectations.py",
        old="    _apply_dependencies(result, expectations)\n    _flag_outliers(result, expectations)",
        new="    _flag_outliers(result, expectations)",
        tests=["tests/unit/test_dependencies_across_rows.py::TestThroughARealSync::test_quarantine_holds_the_disagreeing_row_and_names_the_majority",
               "tests/unit/test_dependencies_across_rows.py::TestThroughARealSync::test_fail_stops_the_build"],
    ),
    Control(
        describes="R29: a strict majority holds only the rows that disagree with it",
        path="core/ontology/field_rules.py",
        old="        if counts[majority] * 2 > len(members):",
        new="        if False:",
        tests=["tests/unit/test_dependencies_across_rows.py::TestTheCheck::test_the_minority_against_a_strict_majority_is_named"],
    ),
    Control(
        describes="R29: an empty determinant agrees with nothing",
        path="core/ontology/field_rules.py",
        old="        if any(part is None for part in key):\n            continue",
        new="        if False:\n            continue",
        tests=["tests/unit/test_dependencies_across_rows.py::TestTheCheck::test_an_empty_determinant_or_dependent_is_not_a_disagreement"],
    ),
    Control(
        describes="R29: a dependency over a link is refused at load",
        path="core/ontology/field_rules.py",
        old="                if fields[field_name].get(\"type\") == \"link\" or is_computed(fields[field_name]):",
        new="                if False:",
        tests=["tests/unit/test_dependencies_across_rows.py::TestRefusedAtLoad::test_a_dependency_that_could_never_be_checked"],
    ),
    Control(
        describes="R30: silver flags unusual values",
        path="core/mirror/expectations.py",
        old="    _flag_outliers(result, expectations)\n    return result",
        new="    return result",
        tests=["tests/unit/test_unusual_values_are_flagged.py::test_a_flagged_row_still_lands"],
    ),

    Control(
        describes="R30: Tukey's fences are k times the interquartile range",
        path="core/mirror/outliers.py",
        old="    low, high = q1 - k * (q3 - q1), q3 + k * (q3 - q1)",
        new="    low, high = q1 - k, q3 + k",
        tests=["tests/unit/test_unusual_values_are_flagged.py::TestTheMethods::test_tukey_far_out_fences"],
    ),
    Control(
        describes="R30: free text has no usual shape to deviate from",
        path="core/mirror/outliers.py",
        old="        if held < DOMINANT_SHARE * len(present):\n            return {}",
        new="        if False:\n            return {}",
        tests=["tests/unit/test_unusual_values_are_flagged.py::TestTheMethods::test_free_text_has_no_usual_shape"],
    ),
    Control(
        describes="R28: the loader expands a value type into its rules",
        path="core/deployment_loader.py",
        old="    validate_and_expand_value_types(object_types_raw)",
        new="    pass",
        tests=["tests/unit/test_value_types.py::test_the_loader_expands_it"],
    ),
    Control(
        describes="R28: identity matching keys a declared value type canonically",
        path="core/mirror/identity.py",
        old="        key = canonical_key(value, (type_def.get(\"fields\") or {}).get(field_name) or {})",
        new="        key = str(value)",
        tests=["tests/unit/test_value_types.py::test_identity_matches_two_spellings_of_one_address"],
    ),
    Control(
        describes="R28: an address keys without case",
        path="core/ontology/value_types.py",
        old="        return email_normalised(text.strip()).casefold()",
        new="        return email_normalised(text.strip())",
        tests=["tests/unit/test_value_types.py::TestTheCanonicalKey::test_an_address_keys_without_case"],
    ),
    Control(
        describes="R33: silver records each cell its cleaning rules changed",
        path="core/mirror/iceberg_sync.py",
        old="        self._write_cleaning(silo_name, table_name, id_column, transformed)",
        new="        pass",
        tests=["tests/unit/test_cleaning_is_recorded_per_cell.py::test_each_changed_cell_is_recorded_with_its_rules"],
    ),
    Control(
        describes="R33: the record names the rule that changed the cell",
        path="core/mirror/standardise.py",
        old="        if after != value:\n            applied.append(name)",
        new="        if after != value:\n            applied.append(\"cleaned\")",
        tests=["tests/unit/test_cleaning_is_recorded_per_cell.py::test_each_changed_cell_is_recorded_with_its_rules",
               "tests/unit/test_cleaning_is_recorded_per_cell.py::test_it_is_replayable_from_bronze_and_the_rules"],
    ),
    Control(
        describes="R33: the record describes silver now rather than accumulating",
        path="core/mirror/iceberg_sync.py",
        old=("                table.overwrite(arrow_table)\n"
             "        except (OSError, ValueError, KeyError, pa.ArrowInvalid) as error:\n"
             "            logger.warning(f\"cleaning record"),
        new=("                table.append(arrow_table)\n"
             "        except (OSError, ValueError, KeyError, pa.ArrowInvalid) as error:\n"
             "            logger.warning(f\"cleaning record"),
        tests=["tests/unit/test_cleaning_is_recorded_per_cell.py::test_it_describes_silver_now_rather_than_accumulating"],
    ),
    Control(
        describes="R33: an erased person's cleaned cells are erased with them",
        path="core/mirror/erasure.py",
        old="    if namespace.startswith((\"quarantine_\", \"cleaning_\")):",
        new="    if namespace.startswith((\"quarantine_\",)):",
        tests=["tests/unit/test_cleaning_is_recorded_per_cell.py::test_an_erased_person_s_cells_go_with_them"],
    ),
    Control(
        describes="R40: silver records the reference-data versions it was judged with",
        path="core/mirror/iceberg_sync.py",
        old="        return {REFERENCE_DATA_PROPERTY: json.dumps(used, sort_keys=True)}",
        new="        return {}",
        tests=["tests/unit/test_reference_data_is_versioned.py::test_the_versions_used_are_recorded"],
    ),
    Control(
        describes="R40: a changed reference-data version is warned about on an unchanged table",
        path="core/mirror/iceberg_sync.py",
        old=("                    tx.set_properties({\n"
             "                        **_read_properties(read_started_at, self._run_id),\n"
             "                        **self._reference_data(table, silo_name, table_name,\n"
             "                                               standardisation, expectations)})"),
        new=("                    tx.set_properties({\n"
             "                        **_read_properties(read_started_at, self._run_id)})"),
        tests=["tests/unit/test_reference_data_is_versioned.py::test_a_changed_version_is_warned_about_even_when_the_data_did_not_change"],
    ),
    Control(
        describes="R46: an as-of read returns the version valid at that time",
        path="core/mirror/changelog.py",
        old="            if (start is None or start <= when) and (end is None or when < end):",
        new="            if end is None:",
        tests=["tests/unit/test_as_of_joins.py::TestAVersionAtATime::test_before_and_after_a_change",
               "tests/unit/test_as_of_joins.py::test_the_history_script_answers_as_of_a_time"],
    ),
    Control(
        describes="R46: an object inserted later did not exist then",
        path="core/mirror/changelog.py",
        old="        if not known:\n            return self._current.get(str(object_id))",
        new="        if True:\n            return self._current.get(str(object_id))",
        tests=["tests/unit/test_as_of_joins.py::TestAVersionAtATime::test_an_object_inserted_later_did_not_exist_then"],
    ),
    Control(
        describes="R46: the boundary of a change belongs to the new version",
        path="core/mirror/changelog.py",
        old="(end is None or when < end):",
        new="(end is None or when <= end):",
        tests=["tests/unit/test_as_of_joins.py::TestAVersionAtATime::test_the_boundary_belongs_to_the_new_version"],
    ),
    Control(
        describes="Review: a cleaned cell stays with its own person when rows are held for a mismatch",
        path="core/mirror/iceberg_sync.py",
        old=("                cleaned_cells=[(kept_position[index], *rest)\n"
             "                               for index, *rest in transformed.cleaned_cells\n"
             "                               if index in kept_position])"),
        new="                )",
        tests=["tests/unit/test_cleaning_is_recorded_per_cell.py::TestWhatAReviewFound::"
               "test_each_cell_stays_with_its_own_person"],
    ),
    Control(
        describes="Review: the cleaning record is bounded",
        path="core/mirror/transform.py",
        old="                    if len(cleaned_cells) < MAX_CLEANED_CELLS:",
        new="                    if True:",
        tests=["tests/unit/test_cleaning_is_recorded_per_cell.py::test_one_batch_is_bounded_too"],
    ),
    Control(
        describes="Review: an old row deleted later existed before its deletion",
        path="core/mirror/changelog.py",
        old="        if change == DELETE and key not in open_versions:",
        new="        if False:",
        tests=["tests/unit/test_as_of_joins.py::test_an_old_row_deleted_later_existed_before_its_deletion"],
    ),
    Control(
        describes="Review: a cycle partner skipped as stale is not leaned on",
        path="scripts/run_sync.py",
        old="            if coming is not None and partner not in not_published:",
        new="            if coming is not None:",
        tests=["tests/unit/test_gold_builds_targets_first.py::TestALinkCycle::"
               "test_a_partner_skipped_as_stale_is_not_leaned_on"],
    ),
    Control(
        describes="Review: the cycle warning names only links that were really made",
        path="scripts/run_sync.py",
        old="            if dangling:",
        new="            if True:",
        tests=["tests/unit/test_gold_builds_targets_first.py::TestALinkCycle::"
               "test_no_warning_when_no_row_points_at_a_new_id"],
    ),
    Control(
        describes="Review: Decimal NaN and Infinity are refused as values, not crashes",
        path="core/ontology/field_types.py",
        old="        if not finite:\n            raise ValueError(f\"{value!r} is not a whole number.\")",
        new="        if False:\n            raise ValueError(f\"{value!r} is not a whole number.\")",
        tests=["tests/unit/test_whole_numbers_however_written.py::test_a_fraction_is_refused_not_truncated"],
    ),
    Control(
        describes="Review: rules that stop using reference data leave no stale record",
        path="core/mirror/iceberg_sync.py",
        old="            return ({REFERENCE_DATA_PROPERTY: \"{}\"}",
        new="            return ({}",
        tests=["tests/unit/test_reference_data_is_versioned.py::"
               "test_a_table_whose_rules_stop_using_it_keeps_no_stale_record"],
    ),
    Control(
        describes="NEW-3: a proposer whose account is gone cannot have their write applied",
        path="core/ontology/write_mediator.py",
        old="            if proposer_now is None:\n                self.audit_log.log_access(",
        new="            if False:\n                self.audit_log.log_access(",
        tests=["tests/unit/test_proposer_is_reread_at_confirm.py::TestTheProposerIsWhoTheyAreNow::"
               "test_a_proposer_whose_account_is_gone_is_refused"],
    ),
    Control(
        describes="NEW-3: the checks use the proposer as they are now, not the snapshot",
        path="core/ontology/write_mediator.py",
        old="            proposer = proposer_now\n",
        new="            pass\n",
        tests=["tests/unit/test_proposer_is_reread_at_confirm.py::TestTheProposerIsWhoTheyAreNow::"
               "test_a_proposer_moved_to_another_compartment_is_refused"],
    ),
    Control(
        describes="NEW-3: a role reassigned without a reload is still rechecked",
        path="core/ontology/write_mediator.py",
        old="                and proposer.role_name == getattr(pending.proposer, \"role_name\", None)):",
        new="                and True):",
        tests=["tests/unit/test_proposer_is_reread_at_confirm.py::TestTheProposerIsWhoTheyAreNow::"
               "test_a_proposer_moved_to_a_role_without_the_grant_is_refused"],
    ),
    Control(
        describes="NEW-3: the approve route re-reads the proposer",
        path="api/routes.py",
        old="                proposer_now=_proposer_as_they_are_now(request, pending.user_id),\n",
        new="",
        tests=["tests/unit/test_proposer_is_reread_at_confirm.py::"
               "test_every_confirm_under_api_says_which_proposer_it_found"],
    ),
    Control(
        describes="NEW-3: a disabled account reads as gone",
        path="api/routes.py",
        old="    if not directory.user_exists(user_id) or directory.is_user_disabled(user_id):\n        return None",
        new="    if not directory.user_exists(user_id):\n        return None",
        tests=["tests/unit/test_proposer_is_reread_at_confirm.py::TestTheRouteLooksThemUp::"
               "test_a_disabled_account_is_none"],
    ),
    Control(
        describes="SEC-28: a create counts as a write into the compartment it sets",
        path="core/ontology/write_mediator.py",
        old="        return sub_write.changes.get(field_name) if field_name else None\n",
        new="        return None\n",
        tests=["tests/unit/test_cross_compartment_write.py::TestACreateIsAWriteToo::"
               "test_reading_one_compartment_and_creating_in_another_is_refused"],
    ),
    Control(
        describes="PA001-G12: a route without a response model sends a decimal as a string",
        path="api/app.py",
        old="fastapi.encoders.ENCODERS_BY_TYPE[decimal.Decimal] = decimal_text\n",
        new="",
        tests=["tests/unit/test_decimals_leave_the_api_exactly.py::TestTheApi::test_a_route_without_a_response_model_sends_a_string"],
    ),
    Control(
        describes="PA001-G12: the detail route answers at the declared scale",
        path="api/routes.py",
        old="            \"fields\": exact_decimals(fields, _declared_fields(mediator, object_type)),\n",
        new="            \"fields\": fields,\n",
        tests=["tests/unit/test_decimals_leave_the_api_exactly.py::test_the_detail_route_answers_at_the_declared_scale"],
    ),
    Control(
        describes="PA001-G12: a decimal is padded to its declared places",
        path="core/ontology/decimal_text.py",
        old="        if wanted is not None and isinstance(exponent, int) and exponent > wanted:",
        new="        if False:",
        tests=["tests/unit/test_decimals_leave_the_api_exactly.py::TestTheText::test_padded_to_the_declared_scale_in_plain_notation"],
    ),
    Control(
        describes="PA001-G12: a 38-digit decimal is not rounded by the default context",
        path="core/ontology/decimal_text.py",
        old="    exact = value.normalize(_EXACT)\n",
        new="    exact = value.normalize()\n",
        tests=["tests/unit/test_decimals_leave_the_api_exactly.py::TestTheText::test_a_38_digit_value_survives"],
    ),
    Control(
        describes="CONCERN-1: SQLite reads a misspelled double-quoted column as an error, not its name",
        path="core/sqlite_connection.py",
        old="    _refuse_double_quoted_strings(conn)\n",
        new="",
        tests=["tests/unit/test_source_column_names_are_never_sql.py::TestTheMisspellingHazard::"
               "test_the_adapter_now_refuses_it_itself"],
    ),
    Control(
        describes="PA001-G11: gold built from the same inputs is not published again",
        path="core/mirror/gold.py",
        old="    if inputs is not None and _published_from(catalog, object_type) == inputs:",
        new="    if False:",
        tests=["tests/unit/test_unchanged_gold_is_not_republished.py::TestNothingChanged::test_a_second_build_publishes_nothing"],
    ),
    Control(
        describes="PA001-G11: every publication restamps its inputs, not only the first",
        path="core/mirror/gold.py",
        old=("    _publish(table, audited)\n    _record_run(catalog, identifier, run_id)\n"
             "    _record_inputs(catalog, identifier, inputs)\n"),
        new="    _publish(table, audited)\n    _record_run(catalog, identifier, run_id)\n",
        tests=["tests/unit/test_unchanged_gold_is_not_republished.py::TestSomethingChanged::"
               "test_after_a_change_it_settles_again"],
    ),
    Control(
        describes="PA001-G11: an unpublished current snapshot is never skipped",
        path="core/mirror/gold.py",
        old="    if current is None or _latest_published_snapshot(table) != current.snapshot_id:\n        return None",
        new="    if current is None:\n        return None",
        tests=["tests/unit/test_unchanged_gold_is_not_republished.py::TestNeverSkipWrongly::test_a_current_snapshot_that_was_never_published_is_not_skipped"],
    ),
    Control(
        describes="PA001-G11: a link target's ids are part of the referrer's inputs",
        path="scripts/run_sync.py",
        old="            for target in targets if target in known\n",
        new="            for target in targets if False\n",
        tests=["tests/unit/test_unchanged_gold_is_not_republished.py::TestSomethingChanged::test_a_link_target_that_changed_rebuilds_the_referrer"],
    ),
    Control(
        describes="PA001-G11: published_at moves when a build confirms gold current",
        path="core/mirror/gold.py",
        old="                    made = max(made, datetime.fromisoformat(confirmed))",
        new="                    pass",
        tests=["tests/unit/test_unchanged_gold_is_not_republished.py::TestNothingChanged::test_published_at_still_moves"],
    ),
    Control(
        describes="RISK-4: on gold a fused type is one table, so its security column always pushes",
        path="core/ontology/gold_view.py",
        old="        rebound.pop(\"storage\", None)\n",
        new="",
        tests=["tests/unit/test_security_pushdown_guard.py::TestOnGoldStorageIsEnough::"
               "test_a_field_from_the_second_source_storage_pushes_on_gold"],
    ),
    Control(
        describes="FLAKE-1: a batched source read is one statement, so a write mid-read cannot tear it",
        path="adapters/sqlite_adapter.py",
        old=("        cursor = conn.execute(sql, params)\n"
             "        while batch := cursor.fetchmany(batch_size):\n"
             "            yield [dict(row) for row in batch]\n"),
        new=("        done = 0\n"
             "        while batch := conn.execute(sql, params).fetchall()[done:done + batch_size]:\n"
             "            done += len(batch)\n"
             "            yield [dict(row) for row in batch]\n"),
        tests=["tests/unit/test_sync_snapshot_semantics.py::"
               "test_the_sync_reads_a_consistent_snapshot_under_concurrent_source_writes"],
    ),
    Control(
        describes="PA001-F5: the loader reads an object-store mirror's sync times with its storage",
        path="core/deployment_loader.py",
        old=("    return IcebergMirrorSync(data_dir / \"mirror\", {},\n"
             "                             storage=dict(config.mirror_storage or {}))\n"),
        new="    return IcebergMirrorSync(data_dir / \"mirror\", {})\n",
        tests=["tests/unit/test_object_storage_can_be_served.py::TestEverySyncObjectIsGivenTheStorage::test_the_loaders_last_synced_time_reads_an_object_store_mirror"],
    ),
    Control(
        describes="PA001-F5: the mirror-status route opens the sync with the deployment's storage",
        path="api/routes.py",
        old="    sync = IcebergMirrorSync(mirror_dir, {}, storage=storage)\n",
        new="    sync = IcebergMirrorSync(mirror_dir, {})\n",
        tests=["tests/unit/test_object_storage_can_be_served.py::TestEverySyncObjectIsGivenTheStorage::test_no_construction_leaves_the_storage_out"],
    ),
    Control(
        describes="PA001-A17: a sync whose bronze copy failed is recorded as degraded, not synced",
        path="scripts/run_sync.py",
        old="    if getattr(result, \"degraded\", None):\n        # BEFORE 'unchanged'",
        new="    if False:\n        # BEFORE 'unchanged'",
        tests=["tests/unit/test_a_bronze_failure_never_serves_stale_data.py::TestTheAttemptSaysDegraded::"
               "test_it_is_recorded_as_degraded_not_synced"],
    ),
    Control(
        describes="NEW-8: the warehouse check knows every catalogued layer, not just silver and bronze",
        path="core/mirror/integrity.py",
        old="            catalog, warehouse_dir, _every_catalogued_table(catalog), report)",
        new="            catalog, warehouse_dir, silver | bronze, report)",
        tests=["tests/unit/test_mirror_integrity.py::"
               "test_gold_and_its_history_on_disk_are_not_reported_as_unknown"],
    ),
    Control(
        describes="PA001-G4: readers pin the newest published tag, not an unaudited current snapshot",
        path="core/mirror/gold.py",
        old="    if not numbered:\n        return None\n    return max(numbered)[1]\n",
        new=("    if not numbered:\n"
             "        current = table.current_snapshot()\n"
             "        return current.snapshot_id if current else None\n"
             "    return max(numbered)[1]\n"),
        tests=["tests/unit/test_readers_pin_a_publication.py::TestACrashBeforeThePublication::"
               "test_nothing_is_pinned"],
    ),
    Control(
        describes="BACKLOG-3: an id in the history that silver lacks and was never deleted is reported",
        path="core/mirror/integrity.py",
        old="        unaccounted = sorted(named - live - deleted)\n",
        new="        unaccounted = sorted(named - live - deleted - named)\n",
        tests=["tests/unit/test_the_changelog_names_real_objects.py::TestWhatIsReported::"
               "test_an_id_that_is_gone_with_no_deletion_recorded"],
    ),
    Control(
        describes="a link table whose silver has not moved is not copied again",
        path="scripts/run_sync.py",
        old="        elif stamp is not None and table.properties.get(LINK_SOURCE_PROPERTY) == stamp:",
        new="        elif False:",
        tests=["tests/unit/test_gold_serves_many_to_many_links.py::TestALinkTableIsNotRebuiltForNothing::test_an_unchanged_link_table_is_left_alone"],
    ),
    Control(
        describes="a changed link table is overwritten in place, never dropped and recreated",
        path="scripts/run_sync.py",
        old="        else:\n            table.overwrite(silver)\n",
        new=("        else:\n            sync._catalog.drop_table(identifier)\n"
             "            table = sync._catalog.create_table(identifier, schema=silver.schema)\n"
             "            table.append(silver)\n"),
        tests=["tests/unit/test_gold_serves_many_to_many_links.py::TestALinkTableIsNotRebuiltForNothing::test_a_changed_one_is_overwritten_in_place_not_recreated"],
    ),
    Control(
        describes="--workers: startup resume waits for every process's in-flight write",
        path="core/ontology/write_mediator.py",
        old="        with _applying(self.write_log.db_path, exclusive=True):\n",
        new="        if True:\n",
        tests=["tests/unit/test_resume_waits_for_live_writers.py::TestTwoRealWorkers::test_a_live_writers_batch_is_left_to_it"],
    ),
    Control(
        describes="--workers: an apply is visible to other processes' resume",
        path="core/ontology/write_mediator.py",
        old="        with _applying(self.write_log.db_path, exclusive=False):\n",
        new="        if True:\n",
        tests=["tests/unit/test_resume_waits_for_live_writers.py::TestTwoRealWorkers::test_a_live_writers_batch_is_left_to_it"],
    ),
    Control(
        describes="SEC-02: a source column named _security is refused, not overwritten",
        path="core/mirror/lineage.py",
        old="    clashes = sorted(set(columns) & set(CARRIED_COLUMNS))",
        new="    clashes = sorted(set(columns) & set(LINEAGE_COLUMNS))",
        tests=["tests/unit/test_system_columns_are_not_silently_taken.py::TestTheSyncRefusesTheCollision::"
               "test_a_source_security_column_is_refused_too"],
    ),
    Control(
        describes="NEW-1: a forward link to an object the caller may not see answers None",
        path="core/ontology/mediator.py",
        old="        if is_link_field(field_info) and value is not None:\n            # A FORWARD LINK",
        new="        if False:\n            # A FORWARD LINK",
        tests=["tests/unit/test_link_fields_respect_mac.py::TestAForwardLinkHidesItsTargetToo::"
               "test_a_foreign_key_to_a_hidden_object_is_withheld"],
    ),
    Control(
        describes="WIRED-3: a match at or above the type's auto_propose_above is flagged for pre-selection",
        path="api/routes.py",
        old="        if float(proposal.score) >= settings.auto_propose_above:",
        new="        if False:",
        tests=["tests/unit/test_high_confidence_matches_are_preselected.py::"
               "test_at_or_above_the_declared_threshold_is_high_confidence"],
    ),
    Control(
        describes="WIRED-2: an approval finishes the asker's paused question",
        path="api/routes.py",
        old="functools.partial(_finish_paused_query, request.app, _generation(request),",
        new="functools.partial(lambda *_: None, request.app, _generation(request),",
        tests=["tests/integration/test_a_question_is_answered_after_approval.py::"
               "test_after_approval_the_asker_is_sent_the_answer"],
    ),
    Control(
        describes="WIRED-2: a question that pauses for a write is kept",
        path="api/routes.py",
        old=("            _paused_queries(request.app).save(\n"
             "                write_id, current_user.user_id, question,"),
        new=("            (lambda *a, **k: None)(\n"
             "                write_id, current_user.user_id, question,"),
        tests=["tests/integration/test_a_question_is_answered_after_approval.py::"
               "test_after_approval_the_asker_is_sent_the_answer"],
    ),
    Control(
        describes="WIRED-2: a gone or disabled asker gets nothing resumed",
        path="api/routes.py",
        old="    asker = asker_now()\n    if asker is None:\n        return\n",
        new="    asker = asker_now() or directory.get_user_record(paused.user_id)\n",
        tests=["tests/unit/test_a_paused_question_runs_as_the_asker_now.py::"
               "test_a_disabled_asker_gets_nothing_resumed"],
    ),
    Control(
        describes="E-06: a source failure is a word from a closed list, not the exception class",
        path="core/source_health.py",
        old="            failures[name] = failure_kind(exc)\n",
        new="            failures[name] = type(exc).__name__\n",
        tests=["tests/unit/test_sources_checked.py::TestSourceFailures::test_a_failing_one_is_named_by_what_failed"],
    ),
    Control(
        describes="ZOO-14: an integer read with leading zeros dropped is counted for a warning",
        path="core/mirror/transform.py",
        old="                if declared == \"integer\" and _has_leading_zeros(value):",
        new="                if False:",
        tests=["tests/unit/test_leading_zeros_are_warned.py::test_a_real_sync_warns"],
    ),
    Control(
        describes="E-14: a memory is hidden from a reader who cannot see a field it came from",
        path="core/memory/guard.py",
        old="        seen = [memory for memory in memories if set(memory.sources) <= readable]",
        new="        seen = list(memories)",
        tests=["tests/unit/test_memory_guard.py::TestWhoSees::test_a_reader_missing_a_source_field_does_not_see_it"],
    ),
    Control(
        describes="E-14: a stale memory is never given to the agent",
        path="core/memory/guard.py",
        old="        return [memory for memory, stale in self.visible(user, object_type, object_id) if not stale]",
        new="        return [memory for memory, stale in self.visible(user, object_type, object_id)]",
        tests=["tests/unit/test_memory_guard.py::TestStaleness::"
               "test_a_changed_source_marks_it_stale_and_keeps_it_from_the_agent",
               "tests/unit/test_memory_guard.py::TestTheAgentReadsThem::test_a_stale_memory_is_not_given_to_the_agent"],
    ),
    Control(
        describes="E-14: a memory cannot be pinned to an object that does not exist",
        path="core/memory/guard.py",
        old="                             value=object_id)]) > 0",
        new="                             value=object_id)]) >= 0",
        tests=["tests/unit/test_memory_guard.py::TestWriting::test_an_object_that_does_not_exist_cannot_be_written_about"],
    ),
    Control(
        describes="E-14: only its author or someone who may change the object forgets a memory",
        path="core/memory/guard.py",
        old="        return memory.author == user.user_id or authorize(",
        new="        return True or authorize(",
        tests=["tests/unit/test_memory_guard.py::TestForgetting::test_another_reader_may_not",
               "tests/integration/test_memories_api.py::test_only_the_author_forgets_it_here"],
    ),
    Control(
        describes="E-14: an erasure forgets what people remembered about them",
        path="core/mirror/erasure.py",
        old="        counts[\"memories\"] = MemoryStore(path).forget_erased(key_hash, hashes)",
        new="        counts[\"memories\"] = 0",
        tests=["tests/unit/test_erasure.py::TestWhatPeopleRemembered::"
               "test_an_erasure_forgets_every_memory_about_them"],
    ),
    Control(
        describes="E-14: a restore does not bring back a memory about someone erased",
        path="scripts/restore_deployment.py",
        old="    forget_beyond_the_mirror(data_dir, register)",
        new="    pass",
        tests=["tests/unit/test_erasure.py::TestWhatPeopleRemembered::"
               "test_a_restore_does_not_bring_them_back"],
    ),
    Control(
        describes="E-14: the agent is given what people remembered about an object it read",
        path="core/agent/agentic_loop.py",
        old="            self._gather_memories(user_record, step[\"object_type\"], object_id, gathered)",
        new="            pass",
        tests=["tests/unit/test_memory_guard.py::TestTheAgentReadsThem::"
               "test_reading_an_object_brings_its_fresh_memories_once"],
    ),
    Control(
        describes="R13: an erasure deletes the notes people wrote about them",
        path="core/mirror/erasure.py",
        old="        counts[\"notes\"] = ArtifactStore(path).forget_erased_notes(key_hash, hashes)",
        new="        counts[\"notes\"] = 0",
        tests=["tests/unit/test_erasure.py::TestWhatPeopleWroteAboutThem::"
               "test_an_erasure_deletes_every_note_about_them"],
    ),
    Control(
        describes="R13: a restore does not bring back a note about someone erased",
        path="core/artifact_store.py",
        old="                if key_hash(object_type, object_id) in hashes_by_type.get(object_type, ()):",
        new="                if False:",
        tests=["tests/unit/test_erasure.py::TestWhatPeopleWroteAboutThem::"
               "test_a_restore_does_not_bring_them_back"],
    ),
    Control(
        describes="R50: an automation does not propose an object it already has waiting",
        path="core/count_condition.py",
        old="    if already_waiting:",
        new="    if False:",
        tests=["tests/unit/test_trigger_actions.py::TestItDoesNotProposeWhatIsAlreadyWaiting::test_a_second_crossing_while_the_first_waits_proposes_nothing",
               "tests/unit/test_action_effect.py::TestWhatIsAlreadyWaitingIsLeftOut::"
               "test_when_everything_is_waiting_nothing_is_proposed"],
    ),
    Control(
        describes="R50: only the automation's own waiting writes are left out",
        path="core/pending_write_store.py",
        old="            if (pending.user_id == user_id and pending.origin == origin",
        new="            if (pending.origin == origin or True",
        tests=["tests/unit/test_trigger_actions.py::TestItDoesNotProposeWhatIsAlreadyWaiting::test_the_same_change_proposed_by_a_person_does_not_count"],
    ),
    Control(
        describes="Backups: a truncated archive is refused (the last-segment flag)",
        path="core/encrypted_archive.py",
        old="    return prefix + struct.pack(\">I\", index) + (b\"\\x01\" if last else b\"\\x00\")",
        new="    return prefix + struct.pack(\">I\", index) + b\"\\x00\"",
        tests=["tests/unit/test_encrypted_backups.py::TestTheArchive::test_a_truncation_at_a_segment_boundary_is_refused"],
    ),
    Control(
        describes="Backups: a key file kept inside what it protects is refused",
        path="core/encrypted_archive.py",
        old="        if resolved == place or place in resolved.parents:",
        new="        if False:",
        tests=["tests/unit/test_encrypted_backups.py::TestTheKeyFile::test_a_key_inside_what_it_protects_is_refused"],
    ),
    Control(
        describes="Backups: without a key the command refuses rather than writing plain",
        path="scripts/backup_deployment.py",
        old="        if not key_file:",
        new="        if False:",
        tests=["tests/unit/test_encrypted_backups.py::TestTheCommands::test_without_a_key_it_refuses_rather_than_writing_plain"],
    ),
    Control(
        describes="Storage: only a CRYPT- device-mapper target counts as encrypted",
        path="core/storage_encryption.py",
        old="    if uuid.is_file() and uuid.read_text().startswith(\"CRYPT-\"):",
        new="    if uuid.is_file():",
        tests=["tests/unit/test_encrypted_backups.py::TestTheVolumeCheck::test_a_plain_device_is_unknown_and_warned"],
    ),
    Control(
        describes="BULK-1: a proposal naming more than the deployment's limit is refused",
        path="core/ontology/write_mediator.py",
        old="            if len(object_ids) > self.bulk_limit:",
        new="            if len(object_ids) > MAX_BULK_OBJECTS:",
        tests=["tests/integration/test_bulk_actions.py::test_one_beyond_the_ceiling_is_refused"],
    ),
    Control(
        describes="BULK-1: absent from config.yaml, the limit is 256",
        path="core/deployment_loader.py",
        old="    if declared is None:\n        return DEFAULT_BULK_OBJECTS",
        new="    if declared is None:\n        return MAX_BULK_OBJECTS",
        tests=["tests/integration/test_bulk_actions.py::TestTheLimitIsTheDeployments::"
               "test_absent_means_256"],
    ),
    Control(
        describes="BULK-1: select-all-matching refuses past the deployment's limit",
        path="api/routes.py",
        old="    limit = _generation(request).config.bulk_action_limit",
        new="    limit = MAX_BULK_OBJECTS",
        tests=["tests/integration/test_api.py::test_matching_ids_refuses_rather_than_truncating"],
    ),
    Control(
        describes="R61: a proposal's source-qualified ids are read as the entities they name",
        path="api/routes.py",
        old="    left = entity_id_of(type_def, proposal.left_id)",
        new="    left = proposal.left_id",
        tests=["tests/integration/test_a_merge_reviewer_sees_verdicts.py::TestAProposalAsTheMatcherWritesIt::test_the_values_of_a_readable_pair_are_shown"],
    ),
    Control(
        describes="R61: a merge proposal with a side MAC hides is not listed",
        path="api/routes.py",
        old="    visible = any(readable) if proposal.decision == APPROVED else all(readable)",
        new="    visible = True",
        tests=["tests/integration/test_a_merge_reviewer_sees_verdicts.py::TestAProposalAsTheMatcherWritesIt::test_a_pair_with_a_side_this_reviewer_cannot_see_is_not_shown"],
    ),
    Control(
        describes="R61: a merge proposal with a side MAC hides cannot be decided",
        path="api/routes.py",
        old="    if _proposal_sides(request, current_user, proposal) is None:",
        new="    if False:",
        tests=["tests/integration/test_a_merge_reviewer_sees_verdicts.py::TestAProposalAsTheMatcherWritesIt::test_nor_may_they_decide_it"],
    ),
    Control(
        describes="AL-11: cancelling a model call closes its connection, so the server stops",
        path="adapters/http_transport.py",
        old="                opened.shut_down()",
        new="                pass",
        tests=["tests/unit/test_cancel_stops_the_model_call.py::TestTheTransport::test_cancelling_closes_the_connection_and_the_server_sees_it"],
    ),
    Control(
        describes="AL-11: the agent loop hands its cancel event to the model call",
        path="core/agent/agentic_loop.py",
        old="                    constrain=self.constrain_steps, cancel=cancel_event,",
        new="                    constrain=self.constrain_steps, cancel=None,",
        tests=["tests/unit/test_cancel_stops_the_model_call.py::TestTheLoop::test_a_cancelled_call_ends_the_run_as_cancelled"],
    ),
    Control(
        describes="AL-11: a question queued for the model slot gives up when its asker leaves",
        path="core/concurrency.py",
        old="                if abandon.is_set():\n                    raise WaitAbandoned()",
        new="                if False:\n                    raise WaitAbandoned()",
        tests=["tests/unit/test_cancel_stops_the_model_call.py::TestWaitingForASlot::test_a_waiter_gives_up_when_cancelled"],
    ),
    Control(
        describes="R31: a dismissed suggestion stays dismissed when the next scan finds it again",
        path="core/rule_suggestions.py",
        old="                if row[\"state\"] == DISMISSED:",
        new="                if False:",
        tests=["tests/unit/test_rule_suggestions.py::TestTheQueue::test_a_dismissal_survives_the_next_scan"],
    ),
    Control(
        describes="R31: a suggestion on a field the caller cannot read is neither shown nor decidable",
        path="api/routes.py",
        old="            if authorize(user, roles, f\"read:{item.object_type}.{item.field}\")]",
        new="            if True]",
        tests=["tests/integration/test_rule_suggestions_api.py::"
               "test_a_field_the_caller_cannot_read_is_not_shown_nor_decidable"],
    ),
    Control(
        describes="R31: a value the schema already nulls reads as declared",
        path="core/mirror/rule_suggestion_scan.py",
        old="            handled = item[\"value\"] in ((field.get(\"standardise\") or {}).get(\"null_if\") or ())",
        new="            handled = False",
        tests=["tests/unit/test_rule_suggestions.py::TestTheScan::test_a_value_the_schema_already_nulls_is_declared"],
    ),
    Control(
        describes="R62: each merge proposal records what produced it",
        path="scripts/run_sync.py",
        old="                       provenance=provenance)",
        new="                       provenance=\"\")",
        tests=["tests/unit/test_inference_wiring.py::TestWhatProducedIt::"
               "test_each_proposal_carries_its_provenance"],
    ),
    Control(
        describes="R62: a merge store from before provenance still reads",
        path="core/identity_decisions.py",
        old="        return connection_with_schema(self._database, SCHEMA, migrations=_MIGRATIONS)",
        new="        return connection_with_schema(self._database, SCHEMA)",
        tests=["tests/unit/test_inference_wiring.py::TestWhatProducedIt::"
               "test_a_store_from_before_provenance_still_reads"],
    ),
    Control(
        describes="R54: a column already declared as a link is not suggested again",
        path="core/mirror/link_discovery.py",
        old="                if (fields.get(field_name) or {}).get(\"type\") == \"link\" or field_name == security:",
        new="                if field_name == security:",
        tests=["tests/unit/test_link_discovery.py::test_a_declared_link_is_not_suggested_again"],
    ),
    Control(
        describes="R54: a column of a few values is not taken for a link",
        path="core/mirror/link_discovery.py",
        old="                if len(values) < MIN_DISTINCT:",
        new="                if False:",
        tests=["tests/unit/test_link_discovery.py::test_a_column_of_few_values_is_not_a_link"],
    ),
    Control(
        describes="R55: a column is matched to a field by its values, not only its name",
        path="core/mirror/binding_suggestions.py",
        old="                if score >= NAME_BAR or (value_share or 0) >= VALUE_BAR:",
        new="                if score >= NAME_BAR:",
        tests=["tests/unit/test_binding_suggestions.py::"
               "test_values_find_a_field_whatever_the_column_is_called"],
    ),
    Control(
        describes="R55: a link field is not offered as a column's match",
        path="core/mirror/binding_suggestions.py",
        old="                if config.get(\"type\", \"data\") != \"data\":",
        new="                if False:",
        tests=["tests/unit/test_binding_suggestions.py::test_a_link_field_is_not_offered"],
    ),
    Control(
        describes="AR-5: on the Claude CLI a step schema is enforced with --json-schema",
        path="adapters/claude_agent_sdk_adapter.py",
        old="            command += [\"--json-schema\", schema]",
        new="            command += []",
        tests=["tests/unit/test_claude_agent_sdk_adapter.py::test_a_schema_is_passed_to_the_cli_to_enforce"],
    ),
    Control(
        describes="F-07: the mirror's single reverse-link read follows a join table's target column",
        path="core/mirror/mirror_adapter.py",
        old="            selected_fields=(route.result_column,),",
        new="            selected_fields=(target_id_column,),",
        tests=["tests/unit/test_link_route.py::test_the_mirror_single_reverse_read_follows_the_join_table"],
    ),
    Control(
        describes="AGENT-FEATURES: the prompt grows only for a switch that is on",
        path="core/llm/agent_step_prompt.py",
        old="        (features.free_text_search, FREE_TEXT_SECTION),",
        new="        (True, FREE_TEXT_SECTION),",
        tests=["tests/unit/test_agent_features.py::TestOffChangesNothing::test_the_prompt_carries_no_section_of_a_switch_that_is_off"],
    ),
    Control(
        describes="AGENT-FEATURES: a remember step is unknown while its switch is off",
        path="core/llm/agent_step_prompt.py",
        old="    if step == \"remember\" and features.remember_from_query:",
        new="    if step == \"remember\":",
        tests=["tests/unit/test_agent_features.py::TestOffChangesNothing::test_the_new_steps_are_unrecognised"],
    ),
    Control(
        describes="AGENT-FEATURES: a filter condition is refused while filter_operators is off",
        path="core/agent/agentic_loop.py",
        old="        if features.filter_operators and isinstance(value, dict):",
        new="        if isinstance(value, dict):",
        tests=["tests/unit/test_agent_features.py::TestOffChangesNothing::test_a_condition_is_refused_when_off"],
    ),
    Control(
        describes="AGENT-FEATURES: a condition becomes its operator, not equality",
        path="core/agent/agentic_loop.py",
        old="            return agent_conditions(filter_)",
        new="            return as_equality_conditions(filter_)",
        tests=["tests/unit/test_agent_features.py::TestFilterOperators::test_a_range_finds_by_range"],
    ),
    Control(
        describes="AGENT-FEATURES: the cap truncates and states the total",
        path="core/agent/agentic_loop.py",
        old="        if cap is not None and isinstance(object_ids, list) and len(object_ids) > cap:",
        new="        if False:",
        tests=["tests/unit/test_agent_features.py::TestSearchResultCap::test_over_the_cap_shows_the_first_and_says_how_many"],
    ),
    Control(
        describes="AGENT-FEATURES: a memory is written only when the question asks",
        path="core/agent/agentic_loop.py",
        old="        if not self.ASKS_TO_REMEMBER.search(query_text or \"\"):",
        new="        if False:",
        tests=["tests/unit/test_agent_features.py::TestRememberFromQuery::test_a_question_that_did_not_ask_records_nothing"],
    ),
    Control(
        describes="AGENT-FEATURES: at most one memory per answer",
        path="core/agent/agentic_loop.py",
        old="        if any(entry.get(\"step\") == \"remember\" for entry in gathered):",
        new="        if False:",
        tests=["tests/unit/test_agent_features.py::TestRememberFromQuery::test_only_once_per_answer"],
    ),
    Control(
        describes="AGENT-FEATURES: a memory is graded on the object it was filed against",
        path="core/agent/evaluation.py",
        old="            object_type == expected.object_type and object_id == expected.object_id",
        new="            object_type == expected.object_type",
        tests=["tests/unit/test_agent_features.py::TestRememberFromQuery::test_graded_on_the_object"],
    ),
    Control(
        describes="AGENT-FEATURES: an arm that did not finish gives no verdict",
        path="scripts/feature_bench.py",
        old="        if len(trials) < len(arm.cases) * args.trials:",
        new="        if False:",
        tests=["tests/unit/test_feature_bench.py::test_an_unreachable_model_decides_nothing"],
    ),
    Control(
        describes="R13: a frozen set loses an erased member",
        path="core/frozen_sets.py",
        old="                        if not is_erased(key_hash, hashes_by_type, row[\"object_type\"], member)]",
        new="                        if True]",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_frozen_set_loses_them_and_the_criteria_that_found_them"],
    ),
    Control(
        describes="R13: a frozen set's criteria naming an erased id go",
        path="core/frozen_sets.py",
        old="                if len(kept) == len(set_.member_ids) and not origin_names_one:",
        new="                if len(kept) == len(set_.member_ids):",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_frozen_set_loses_them_and_the_criteria_that_found_them"],
    ),
    Control(
        describes="R13: the write log forgets an erased object's edits",
        path="core/ontology/write_log.py",
        old="            doomed = [row for row in rows if erased(row[\"object_type\"], row[\"object_id\"])]",
        new="            doomed = []",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_the_write_log_forgets_their_edits_and_keeps_the_rest"],
    ),
    Control(
        describes="R13: a batch that touched them keeps its other sub-writes, without its description",
        path="core/ontology/write_log.py",
        old="                if len(kept) == len(sub_writes) and batch[\"id\"] not in touched:",
        new="                if True:",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_the_write_log_forgets_their_edits_and_keeps_the_rest"],
    ),
    Control(
        describes="R13: a waiting write naming an erased id as a parameter is withdrawn",
        path="core/pending_write_store.py",
        old="        if any(is_erased_as_any_type(key_hash, hashes_by_type, item) for item in values):",
        new="        if False:",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_waiting_write_about_them_is_withdrawn_and_audited_without_them"],
    ),
    Control(
        describes="R13: a waiting write targeting an erased object is withdrawn",
        path="core/pending_write_store.py",
        old="                if _about_erased(pending, key_hash, hashes_by_type):",
        new="                if False:",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_waiting_write_about_them_is_withdrawn_and_audited_without_them"],
    ),
    Control(
        describes="R13: a paused question that read an erased object is dropped",
        path="core/paused_queries.py",
        old="                if row[\"write_id\"] in withdrawn or any_erased(",
        new="                if row[\"write_id\"] in withdrawn and any_erased(",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_paused_question_that_read_them_is_dropped_and_its_asker_told"],
    ),
    Control(
        describes="R13: the asker of a dropped question is told",
        path="core/mirror/erasure.py",
        old="        notices.notify(user_id, ERASED_NOTICE_KIND, ERASED_QUESTION)",
        new="        pass",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_paused_question_that_read_them_is_dropped_and_its_asker_told"],
    ),
    Control(
        describes="R13: an answer built from an erased object is forgotten",
        path="core/notifications.py",
        old="                if any_erased(key_hash, hashes_by_type, subjects):",
        new="                if False:",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_an_answer_built_from_them_is_forgotten"],
    ),
    Control(
        describes="R13: a restore forgets them in every store again",
        path="core/mirror/erasure.py",
        old="        counts[\"frozen_set_members\"] = FrozenSetStore(path).forget_erased(key_hash, hashes)",
        new="        counts[\"frozen_set_members\"] = 0",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_restore_forgets_them_in_every_store_again"],
    ),
    Control(
        describes="R13: a merge proposal naming an erased record goes",
        path="core/identity_decisions.py",
        old="            doomed = [(row[\"proposal_id\"],) for row in rows",
        new="            doomed = [(row[\"proposal_id\"],) for row in rows if False",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_merge_proposal_naming_them_goes_with_its_decisions"],
    ),
    Control(
        describes="R58: a chained approval needs the group it joins",
        path="api/routes.py",
        old="        if shown and (sorted(body.confirm_group or []) != shown[\"group\"]):",
        new="        if False:",
        tests=["tests/integration/test_a_merge_reviewer_sees_verdicts.py::TestAChainIsApprovedAsAGroup::test_approving_without_the_group_is_refused_with_it"],
    ),
    Control(
        describes="R58: approved neighbours are pulled into the group",
        path="core/identity_decisions.py",
        old="        for left, right in [*pairs, (proposal.left_id, proposal.right_id)]:",
        new="        for left, right in [(proposal.left_id, proposal.right_id)]:",
        tests=["tests/unit/test_identity_decisions_group.py::test_an_approved_neighbour_is_pulled_in"],
    ),
    Control(
        describes="R58: an unreadable member of the group is counted, not named",
        path="api/routes.py",
        old="             or _may_read_object(generation.mediator, user, proposal.object_type,",
        new="             or True or _may_read_object(generation.mediator, user, proposal.object_type,",
        tests=["tests/integration/test_a_merge_reviewer_sees_verdicts.py::TestAChainIsApprovedAsAGroup::test_the_card_says_what_else_it_would_join"],
    ),
    Control(
        describes="R57: a rejection shown pre-selected is not calibration evidence",
        path="core/mirror/match_calibration.py",
        old="            if score >= float(auto):",
        new="            if False:",
        tests=["tests/unit/test_match_calibration.py::TestWhatCountsAsEvidence::test_a_rejection_that_was_pre_selected_does_not_count"],
    ),
    Control(
        describes="R57: a rejection scored under other weights is not evidence",
        path="core/mirror/match_calibration.py",
        old="            if scoring_key(_provenance(proposal)) != key:",
        new="            if False:",
        tests=["tests/unit/test_match_calibration.py::TestWhatCountsAsEvidence::test_a_rejection_scored_under_other_weights_does_not_count"],
    ),
    Control(
        describes="R57: too few rejections is uncalibrated",
        path="core/mirror/match_calibration.py",
        old="    if len(reference) < needed:",
        new="    if False:",
        tests=["tests/unit/test_match_calibration.py::TestWhatCountsAsEvidence::test_too_few_rejections_is_uncalibrated_and_selects_nothing"],
    ),
    Control(
        describes="R57: Benjamini-Hochberg's bar falls with the number waiting",
        path="core/mirror/match_calibration.py",
        old="        if p <= rank * alpha / m:",
        new="        if p <= alpha:",
        tests=["tests/unit/test_match_calibration.py::TestWhatCountsAsEvidence::test_more_waiting_pairs_need_more_rejections"],
    ),
    Control(
        describes="R57: below the declared threshold only an uncalibrated type ticks nothing",
        path="api/routes.py",
        old="        elif calibration.status == CALIBRATED and proposal.proposal_id in calibration.selected:",
        new="        elif True:",
        tests=["tests/unit/test_match_calibration.py::TestTheListing::test_one_rejection_short_ticks_nothing_and_says_uncalibrated"],
    ),
    Control(
        describes="R56: scoring never proposes a pair the declared rule merged",
        path="core/mirror/match_cascade.py",
        old="        if same is not None and same == groups.get(candidate.right_id):\n            continue",
        new="        pass",
        tests=["tests/unit/test_match_cascade.py::TestTheRuleIsStageOne::test_scoring_never_proposes_what_the_rule_merged"],
    ),
    Control(
        describes="R56: a fuzzy field's close level is reported as close, not agree",
        path="core/mirror/matching.py",
        old="        return True if value >= 2 else CLOSE if value == 1 else False",
        new="        return value > 0",
        tests=["tests/unit/test_match_cascade.py::TestTheScores::test_a_typo_now_reaches_review"],
    ),
    Control(
        describes="R56: a reviewer is shown close, not agree",
        path="core/masked_review.py",
        old="    if agreement == CLOSE:\n        return CLOSE\n",
        new="",
        tests=["tests/unit/test_match_cascade.py::TestTheCloseLevel::test_a_reviewer_is_told_close_not_agree"],
    ),
    Control(
        describes="R56: fuzzy means one edit unless declared otherwise",
        path="core/mirror/matching.py",
        old="DEFAULT_FUZZY_EDITS = 1\n",
        new="DEFAULT_FUZZY_EDITS = 2\n",
        tests=["tests/unit/test_match_cascade.py::TestTheScores::test_two_edits_are_not_close_by_default"],
    ),
    Control(
        describes="R60: when the preferred source moves, the other source held",
        path="core/mirror/source_record.py",
        old="            held, moved = losing_source, chosen_source",
        new="            held, moved = chosen_source, losing_source",
        tests=["tests/unit/test_source_track_record.py::TestHowADisagreementEnds::test_the_preferred_source_moving_means_the_other_held"],
    ),
    Control(
        describes="R60: both moving to a third value is no evidence",
        path="core/mirror/source_record.py",
        old="            continue  # both moved to a third value: no evidence either way",
        new="            held, moved = chosen_source, losing_source",
        tests=["tests/unit/test_source_track_record.py::TestHowADisagreementEnds::test_both_moving_to_a_third_value_is_no_evidence"],
    ),
    Control(
        describes="R60: the browser sees nothing below ten ended disagreements",
        path="core/mirror/source_record.py",
        old="        if self.total < SHOWN_FROM:",
        new="        if False:",
        tests=["tests/unit/test_source_track_record.py::TestWhatTheBrowserMaySee::test_nothing_below_the_minimum"],
    ),
    Control(
        describes="R60: an erasure forgets the ended disagreements about them",
        path="core/mirror/erasure.py",
        old='    if path := present("source_record.db"):',
        new="    if False:",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_an_ended_disagreement_about_them_is_forgotten"],
    ),
    Control(
        describes="R60: a copy's vote is discounted",
        path="core/mirror/source_vote.py",
        old="                    weight *= 1 - COPY_RATE * copying.get(frozenset((source, earlier)), 0.0)",
        new="                    pass",
        tests=["tests/unit/test_source_vote.py::TestCopies::test_discounting_the_copy_gets_more_answers_right"],
    ),
    Control(
        describes="R60: error rates are estimated, so accurate sources are not copies",
        path="core/mirror/source_vote.py",
        old="        errors = _error_rates(items, winners)\n",
        new="        errors = {s: ERROR_RATE for s in sources}\n",
        tests=["tests/unit/test_source_vote.py::TestCopies::test_accurate_independent_sources_are_not_copies"],
    ),
    Control(
        describes="R60: a tie names no majority",
        path="core/mirror/source_vote.py",
        old="        winners[key] = leaders[0] if len(leaders) == 1 else None",
        new="        winners[key] = sorted(leaders)[0]",
        tests=["tests/unit/test_source_vote.py::TestThePlainVote::test_a_tie_says_nothing"],
    ),
    Control(
        describes="R60: an erasure forgets the votes about them",
        path="core/mirror/source_record.py",
        old='            conn.executemany("DELETE FROM votes WHERE rowid = ?", voted)',
        new="            pass",
        tests=["tests/unit/test_erasure.py::TestEverythingButTheAuditLog::test_a_vote_about_them_is_forgotten"],
    ),
    Control(
        describes="R63: code appends the inferred-values note to the answer",
        path="core/llm/synthesis_prompt.py",
        old="    return answer + cut + for_the_reader(found)",
        new="    return answer + cut",
        tests=["tests/unit/test_answers_say_what_is_inferred.py::TestCodeEnforcesIt::test_the_note_is_appended_whatever_the_model_wrote"],
    ),
    Control(
        describes="R63: a search filtered on an inferred field counts as inferred data",
        path="core/llm/inferred_values.py",
        old='        names.update(k for k in item["filter"] if isinstance(k, str))',
        new="        pass",
        tests=["tests/unit/test_answers_say_what_is_inferred.py::TestWhatCountsAsInferredData"],
    ),
    Control(
        describes="DEV_UI 13.3: a field a role only knows exists is not called readable",
        path="core/ontology/who_can_see.py",
        old='else READ if shown[name].get("readable") else DISCOVER)',
        new="else READ)",
        tests=["tests/integration/test_who_can_see.py::TestFields::test_discover_without_read_is_its_own_answer"],
    ),
    Control(
        describes="DEV_UI 13.3: a borrowed compartment is followed to the field compared",
        path="core/ontology/who_can_see.py",
        old='        path.append({"type": current, "field": via})\n        current = target',
        new='        return {"attribute": attribute, "path": path, "type": current, "field": via}',
        tests=["tests/integration/test_who_can_see.py::TestCompartments::test_a_borrowed_one_is_followed_to_its_end"],
    ),
    Control(
        describes="DEV_UI 13.3: who-can-see is for manage:roles only",
        path="api/routes.py",
        old=("    _require_manage_roles(request, current_user)\n"
             "    generation = _generation(request)\n"
             "    every, _active = _holders(request)\n    schema"),
        new=("    generation = _generation(request)\n"
             "    every, _active = _holders(request)\n    schema"),
        tests=["tests/integration/test_who_can_see.py::TestWhoMayAsk::test_an_ordinary_user_is_refused"],
    ),
    Control(
        describes="DEV_UI 13.5: proposed grants are compiled as the mediators compile them",
        path="core/role_impact.py",
        old="    proposed = access_roles(dataclasses.replace(config, roles=declared))",
        new="    proposed = declared",
        tests=["tests/integration/test_role_change_impact.py::TestItAsksThePermissionCode::test_a_label_grant_shows_as_the_fields_it_opens"],
    ),
    Control(
        describes="DEV_UI 13.5: a preview refuses what proposing would refuse",
        path="api/routes.py",
        old=("    if problem is not None:\n        raise HTTPException(status_code=400, detail=problem)\n"
             "    from core.role_impact import role_change_impact"),
        new="    from core.role_impact import role_change_impact",
        tests=["tests/integration/test_role_change_impact.py::TestItChangesNothingAndRefusesWhatProposingWould::"
               "test_a_change_proposing_would_refuse_is_refused_with_its_reason"],
    ),
    Control(
        describes="DEV_UI 13.5: the approver sees what a waiting change would do",
        path="api/routes.py",
        old='                         "impact": _impact_or_none(request, change.role_name, change.after, every)}',
        new='                         "impact": None}',
        tests=["tests/integration/test_role_change_impact.py::TestTheApproverSeesIt::test_a_pending_change_carries_its_impact"],
    ),
    Control(
        describes="DEV_UI 14.5: a type the caller may only discover gets no count",
        path="api/routes.py",
        old=("        if not authorize(current_user, generation.config.roles, f\"read:{object_type}\"):\n"
             "            continue\n        outcome = SearchOutcome()"),
        new="        outcome = SearchOutcome()",
        tests=["tests/integration/test_type_counts.py::TestOnlyWhatTheyMayRead::test_a_type_they_may_only_discover_gets_no_count"],
    ),
    Control(
        describes="DEV_UI 14.5: one type's failed count is one type, not the answer",
        path="api/routes.py",
        old=("        except Exception:  # noqa: BLE001 - see the docstring: one type, not the answer\n"
             "            continue"),
        new="        except ZeroDivisionError:\n            continue",
        tests=["tests/integration/test_type_counts.py::TestOneFailureIsOneType::test_a_type_whose_count_fails_is_left_out"],
    ),
    Control(
        describes="DEV_UI 13.7: a key off the describing allowlist is refused",
        path="core/config_editing.py",
        old=("        if key not in allowed:\n"
             "            raise ConfigEditError(f\"{where}'s {key} cannot be edited here.\")"),
        new="        if False:\n            pass",
        tests=["tests/unit/test_describing_the_ontology_lines.py::TestTheAllowlist::test_shape_and_access_are_out_of_reach",
               "tests/integration/test_describing_the_ontology.py::test_security_is_out_of_reach_however_it_is_asked"],
    ),
    Control(
        describes="DEV_UI 13.7: an edit that would change the file's meaning is refused",
        path="core/config_editing.py",
        old="    if means != expected:\n        raise ConfigEditError(f\"That change could not be made",
        new="    if False:\n        raise ConfigEditError(f\"That change could not be made",
        tests=["tests/unit/test_describing_the_ontology_lines.py::TestTheMeaningCheck::test_a_layout_it_cannot_edit_cleanly_is_refused_not_mangled"],
    ),
    Control(
        describes="DEV_UI 13.7: a value running onto lines below goes with it",
        path="core/config_editing.py",
        old="            del lines[at + 1:last + 1]",
        new="            pass",
        tests=["tests/unit/test_describing_the_ontology_lines.py::TestOnlyItsLines::test_a_folded_description_is_replaced_whole"],
    ),
    Control(
        describes="DEV_UI 13.7: a hash inside a value is not a comment",
        path="core/config_editing.py",
        old="            if plain_yaml.safe_load(\"k:\" + tail[:at]) == {\"k\": old}:",
        new="            if True:",
        tests=["tests/unit/test_describing_the_ontology_lines.py::TestTextThatYamlWouldMisread::test_a_hash_inside_a_quoted_value_is_not_taken_for_a_comment"],
    ),
    Control(
        describes="DEV_UI 13.7: a new key goes beside its kind, not under the last field",
        path="core/config_editing.py",
        old="    if after is not None and parent_line is not None:",
        new="    if False:",
        tests=["tests/unit/test_describing_the_ontology_lines.py::TestOnlyItsLines::test_a_new_key_goes_first_in_the_type_not_under_its_last_field",
               "tests/integration/test_describing_the_ontology.py::test_only_the_changed_lines_differ"],
    ),
    Control(
        describes="DEV_UI 13.7 labels: a widening waits rather than applying",
        path="api/routes.py",
        old="        if not impact[\"widens\"]:\n            result = _write_config_file(",
        new="        if True:\n            result = _write_config_file(",
        tests=["tests/integration/test_access_labels.py::TestWhenLabelsDecideAccess::test_removing_a_label_opens_the_field_and_waits"],
    ),
    Control(
        describes="DEV_UI 13.7 labels: widening is asked of the permission code, gains included",
        path="core/role_impact.py",
        old='_GAINS = ("types_gained", "fields_gained", "actions_gained", "other_gained")',
        new='_GAINS = ("types_gained", "actions_gained", "other_gained")',
        tests=["tests/integration/test_access_labels.py::TestWhenLabelsDecideAccess::test_adding_a_label_can_open_a_field_too"],
    ),
    Control(
        describes="DEV_UI 13.7 proposals: the proposer cannot approve their own",
        path="api/routes.py",
        old="        if proposal.proposed_by == current_user.user_id:\n            raise HTTPException(status_code=409",
        new="        if False:\n            raise HTTPException(status_code=409",
        tests=["tests/integration/test_access_labels.py::TestTheSecondPerson::test_the_proposer_cannot_approve_their_own"],
    ),
    Control(
        describes="DEV_UI 13.7 proposals: approving is for role managers",
        path="api/routes.py",
        old=(
            "    _require_manage_roles(request, current_user)\n"
            "    store = _proposals(request)\n"
            "    with _config_edit_lock:"
        ),
        new="    store = _proposals(request)\n    with _config_edit_lock:",
        tests=["tests/integration/test_access_labels.py::TestTheSecondPerson::test_a_deployment_manager_cannot_approve"],
    ),
    Control(
        describes="DEV_UI 13.7 proposals: a file changed since is stale, not merged",
        path="api/routes.py",
        old=(
            "        if any(digest(current[name]) != proposal.base.get(name) for name in proposal.files):\n"
            "            reason = ("
        ),
        new="        if False:\n            reason = (",
        tests=["tests/integration/test_access_labels.py::TestTheSecondPerson::test_a_file_changed_since_is_stale_not_merged"],
    ),
    Control(
        describes="DEV_UI 13.7 proposals: rejecting someone else's needs manage:roles",
        path="api/routes.py",
        old="    if not own:\n        _require_manage_roles(request, current_user)\n",
        new="",
        tests=["tests/integration/test_access_labels.py::TestTheSecondPerson::test_only_role_managers_reject_someone_elses"],
    ),
    Control(
        describes="DEV_UI 13.7 labels: a widening needs a reason",
        path="api/routes.py",
        old=(
            "    if not reason:\n"
            "        raise HTTPException(status_code=400, detail=(\n"
            "            \"This lets people read more"
        ),
        new=(
            "    if False:\n"
            "        raise HTTPException(status_code=400, detail=(\n"
            "            \"This lets people read more"
        ),
        tests=["tests/integration/test_access_labels.py::TestWhenLabelsDecideAccess::test_a_widening_without_a_reason_is_refused"],
    ),
    Control(
        describes="DEV_UI 13.7 labels: a label has one spelling",
        path="core/config_editing.py",
        old="            if not shape.match(label):",
        new="            if False:",
        tests=["tests/unit/test_describing_the_ontology_lines.py::TestLabels::test_a_label_has_one_spelling"],
    ),
    Control(
        describes="DEV_UI 13.7 restore: a data type does not go back",
        path="api/routes.py",
        old="        if moved:\n            raise HTTPException(status_code=400, detail=(",
        new="        if False:\n            raise HTTPException(status_code=400, detail=(",
        tests=["tests/integration/test_putting_a_version_back.py::TestWhatItRefuses::test_a_data_type_does_not_go_back"],
    ),
    Control(
        describes="DEV_UI 13.7 restore: a widening restore waits",
        path="api/routes.py",
        old="        if not impact[\"widens\"]:\n            result = _write_config_files(",
        new="        if True:\n            result = _write_config_files(",
        tests=["tests/integration/test_putting_a_version_back.py::TestPuttingItBack::test_a_widening_restore_waits_with_its_reason_and_the_approver_applies_it"],
    ),
    Control(
        describes="DEV_UI 13.7 restore: a file changed since the preview is refused",
        path="api/routes.py",
        old="        if _files_digest(now) != body.digest:",
        new="        if False:",
        tests=["tests/integration/test_putting_a_version_back.py::TestPuttingItBack::test_a_file_changed_since_the_preview_is_refused"],
    ),
    Control(
        describes="DEV_UI 13.7 restore: a file that comes or goes is refused",
        path="api/routes.py",
        old="    if set(then) != set(now):",
        new="    if False:",
        tests=["tests/integration/test_putting_a_version_back.py::TestWhatItRefuses::test_a_file_that_comes_or_goes"],
    ),
    Control(
        describes="DEV_UI 13.7 restore: nothing to put back says so",
        path="api/routes.py",
        old="    if not changed:\n        raise HTTPException(status_code=400, detail=(",
        new="    if False:\n        raise HTTPException(status_code=400, detail=(",
        tests=["tests/integration/test_putting_a_version_back.py::TestWhatItRefuses::test_nothing_to_put_back"],
    ),
    Control(
        describes="DEV_UI 13.7 restore: files holding connections are named, never shown",
        path="core/config_editing.py",
        old="    if filename == ONTOLOGY_FILE:\n        return diff(before, after, filename)",
        new="    if True:\n        return diff(before, after, filename)",
        tests=["tests/integration/test_putting_a_version_back.py::TestWhatItShows::test_files_that_hold_connections_are_named_not_shown",
               "tests/integration/test_putting_a_version_back.py::test_an_approved_restore_does_not_return_lines_it_never_showed"],
    ),
    Control(
        describes="TRIGGERS: an action may let an automation's owner approve its proposal",
        path="core/ontology/write_mediator.py",
        old='        if pending.origin == "automation" and action_def.get("owner_may_approve_automation") is True:',
        new='        if False:',
        tests=["tests/unit/test_write_mediator.py::test_an_action_may_let_the_owner_approve_their_automations_proposal"],
    ),
    Control(
        describes="TRIGGERS: the owner setting covers automations, not the owner's own proposals",
        path="core/ontology/write_mediator.py",
        old='        if pending.origin == "automation" and action_def.get("owner_may_approve_automation") is True:',
        new='        if action_def.get("owner_may_approve_automation") is True:',
        tests=["tests/unit/test_write_mediator.py::test_the_setting_is_about_automations_not_the_owners_own_proposals"],
    ),
    Control(
        describes="TRIGGERS: owner approval beside automatable false is refused",
        path="core/ontology/action_types.py",
        old='    if value and action_def.get("automatable") is False:',
        new='    if False:',
        tests=["tests/unit/test_automatable.py::TestOwnerMayApproveAutomation::test_beside_automatable_false_it_is_a_contradiction"],
    ),
    Control(
        describes="TRIGGERS: the Watch dialog's second-person answer honours the owner setting",
        path="core/ontology/action_types.py",
        old='    if action_def.get("owner_may_approve_automation") is True:\n        return False',
        new='    if False:\n        return False',
        tests=["tests/unit/test_automatable.py::TestWhetherAnotherPersonApproves::test_unless_the_action_lets_the_owner"],
    ),
    Control(
        describes="TIMERS: a timer moved while it fired is kept",
        path="core/timers.py",
        old=('                "DELETE FROM timers WHERE kind = ? AND key = ? AND due_at = ?",\n'
             '                (timer.kind, timer.key, timer.due_at),'),
        new=('                "DELETE FROM timers WHERE kind = ? AND key = ?",\n'
             '                (timer.kind, timer.key),'),
        tests=["tests/unit/test_timers.py::test_done_keeps_a_timer_moved_while_it_fired"],
    ),
    Control(
        describes="TIMERS: a failing timer is dropped after its attempts",
        path="core/timers.py",
        old="            self.done(timer)\n            return False",
        new="            return False",
        tests=["tests/unit/test_timers.py::test_a_failure_is_retried_later_then_dropped"],
    ),
    Control(
        describes="TIMERS: setting one wakes this process's loop",
        path="core/timers.py",
        old="        for listener in list(_listeners):\n            try:\n                listener(float(due_at))",
        new="        for listener in []:\n            try:\n                listener(float(due_at))",
        tests=["tests/unit/test_timers.py::test_this_process_is_told_when_a_timer_is_set"],
    ),
    Control(
        describes="TIMERS: one worker fires, the others do not",
        path="api/timer_service.py",
        old=("            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
             "        except BlockingIOError:\n            return 0"),
        new="            pass\n        except BlockingIOError:\n            return 0",
        tests=["tests/integration/test_timer_service.py::test_another_worker_firing_means_this_one_does_not"],
    ),
    Control(
        describes="TIMERS: a kind nobody handles is dropped, not retried forever",
        path="api/timer_service.py",
        old="                store.done(timer)\n                continue\n            now = clock()",
        new="                continue\n            now = clock()",
        tests=["tests/integration/test_timer_service.py::test_a_kind_nobody_handles_is_dropped"],
    ),
    Control(
        describes="TIMERS: an overdue timer is a short sleep, not a spin",
        path="api/timer_service.py",
        old="    return max(MIN_SLEEP_SECONDS, min(LOOK_SECONDS, upcoming - clock()))",
        new="    return max(0.0, min(LOOK_SECONDS, upcoming - clock()))",
        tests=["tests/integration/test_timer_service.py::test_it_sleeps_until_the_earliest_timer_within_bounds"],
    ),
    Control(
        describes="WINDOWS: every evaluation sets a date-filtered trigger's next wake",
        path="core/trigger_runs.py",
        old="    _schedule_windows(data_dir, mediator, views, made, declared, owners)\n",
        new="",
        tests=["tests/integration/test_trigger_windows.py::TestItSetsATimerForTheNextCrossing::test_made_now_it_wakes_when_the_first_record_leaves"],
    ),
    Control(
        describes="WINDOWS: a wake is never sooner than a minute",
        path="core/trigger_windows.py",
        old="    due = max(crossing.timestamp(), now.timestamp() + MIN_SPACING_SECONDS)",
        new="    due = crossing.timestamp()",
        tests=["tests/integration/test_trigger_windows.py::TestTheCrossing::test_never_sooner_than_a_minute"],
    ),
    Control(
        describes="WINDOWS: nothing left to cross clears the timer",
        path="core/trigger_windows.py",
        old="        timers.cancel(KIND, trigger.trigger_id)\n        return None",
        new="        return None",
        tests=["tests/integration/test_trigger_windows.py::TestItSetsATimerForTheNextCrossing::test_nothing_left_to_cross_means_no_timer"],
    ),
    Control(
        describes="WINDOWS: the timer's handler evaluates the trigger",
        path="api/trigger_checks.py",
        old="    fired = _run(app, only(firing.key))\n",
        new="    fired = 0\n",
        tests=["tests/integration/test_trigger_windows.py::TestItSetsATimerForTheNextCrossing::test_the_timer_firing_tells_them_and_sets_the_next"],
    ),
    Control(
        describes="WINDOWS: the server starting checks date-filtered triggers",
        path="api/trigger_checks.py",
        old="            or (dated and reads_the_clock(trigger, view))))",
        new="            or False))",
        tests=["tests/integration/test_trigger_windows.py::test_the_server_starting_checks_every_date_filtered_trigger"],
    ),
    Control(
        describes="INBOX: the signal goes to its owner's streams only",
        path="api/live_updates.py",
        old="        self._send(lambda owner: owner == user_id, (INBOX, None))",
        new="        self._send(lambda owner: True, (INBOX, None))",
        tests=["tests/integration/test_inbox_signal.py::test_nobody_else_is"],
    ),
    Control(
        describes="INBOX: writing a notification announces it",
        path="core/notifications.py",
        old="        for listener in list(_listeners):\n            try:\n                listener(user_id)",
        new="        for listener in []:\n            try:\n                listener(user_id)",
        tests=["tests/integration/test_inbox_signal.py::test_writing_a_notification_announces_the_recipient_only"],
    ),
    Control(
        describes="TIMERS: the old clock settings are refused at load",
        path="core/deployment_loader.py",
        old="    _no_trigger_clock(config)\n",
        new="",
        tests=["tests/unit/test_trigger_clock_gone.py::test_loading_a_deployment_refuses_it"],
    ),
    Control(
        describes="HOURS: hours on a date field are refused",
        path="core/filters.py",
        old='    if "hours" in units and declared_type == "date":',
        new="    if False:",
        tests=["tests/unit/test_relative_hours.py::TestValidation::test_hours_on_a_date_are_refused_by_name"],
    ),
    Control(
        describes="HOURS: days and hours together are refused",
        path="core/filters.py",
        old="    if len(units) > 1:",
        new="    if False:",
        tests=["tests/unit/test_relative_hours.py::TestValidation::test_days_and_hours_together_are_refused"],
    ),
    Control(
        describes="HOURS: a relative date resolves in the unit it counts",
        path="core/filters.py",
        old='RELATIVE_UNITS = {"days": timedelta(days=1), "hours": timedelta(hours=1)}',
        new='RELATIVE_UNITS = {"days": timedelta(days=1), "hours": timedelta(days=1)}',
        tests=["tests/integration/test_relative_dates_answer.py::test_in_the_last_n_hours"],
    ),
    Control(
        describes="HOURS: a trigger's timer reads the window in its own unit",
        path="core/trigger_windows.py",
        old="                crossing = earliest + span",
        new="                crossing = earliest + span * 24",
        tests=["tests/unit/test_relative_hours.py::TestOneHelperForEveryReader::test_a_trigger_wakes_when_a_record_turns_n_hours_old"],
    ),
    Control(
        describes="HOURS: the agent says hours",
        path="core/agent/set_context.py",
        old='        unit = "hours" if any(',
        new='        unit = "days" if any(',
        tests=["tests/unit/test_relative_hours.py::TestOneHelperForEveryReader::test_the_agent_says_hours"],
    ),
    Control(
        describes="LATENESS: a timer past its policy is missed, not run as if on time",
        path="api/timer_service.py",
        old="    if now - latest <= threshold:",
        new="    if True:",
        tests=["tests/integration/test_timer_service.py::TestHowLateIsTooLate::test_later_than_its_policy_is_missed_not_run_as_if_on_time"],
    ),
    Control(
        describes="LATENESS: under a minute late is never a miss",
        path="api/timer_service.py",
        old="    threshold = max(timer.late_after, ON_TIME_SECONDS)",
        new="    threshold = timer.late_after",
        tests=["tests/integration/test_timer_service.py::TestHowLateIsTooLate::test_under_a_minute_late_is_never_a_miss"],
    ),
    Control(
        describes="REPEAT: a repeating timer moves on rather than ending",
        path="api/timer_service.py",
        old=("    if timer.repeat is None:\n        return None\n    from core.timer_rules import next_occurrence\n"
             "\n    anchor = datetime.fromtimestamp(timer.occurrence_at, UTC)\n    after"),
        new=("    if True:\n        return None\n    from core.timer_rules import next_occurrence\n"
             "\n    anchor = datetime.fromtimestamp(timer.occurrence_at, UTC)\n    after"),
        tests=["tests/integration/test_timer_service.py::TestARepeatingTimer::test_moves_on_to_its_next_occurrence"],
    ),
    Control(
        describes="REPEAT: back from an outage, the latest occurrence still in time is delivered",
        path="api/timer_service.py",
        old=("    threshold = max(timer.late_after, ON_TIME_SECONDS)\n"
             "    latest = since[-1] if since else timer.occurrence_at"),
        new=("    threshold = max(timer.late_after, ON_TIME_SECONDS)\n"
             "    latest = timer.occurrence_at"),
        tests=["tests/integration/test_timer_service.py::TestARepeatingTimer::test_catches_up_at_most_once_delivering_the_latest_still_in_time"],
    ),
    Control(
        describes="REPEAT: a retry keeps its occurrence, so its key",
        path="core/timers.py",
        old='                "UPDATE timers SET due_at = ?, attempts = attempts + 1 "',
        new=('                "UPDATE timers SET due_at = ?, occurrence_at = due_at + 1, '
             'attempts = attempts + 1 "'),
        tests=["tests/integration/test_timer_service.py::TestARepeatingTimer::test_a_retry_is_the_same_occurrence"],
    ),
    Control(
        describes="REPEAT: a weekday rule keeps to the owner's clock",
        path="core/timer_rules.py",
        old="        candidate = datetime.combine(day, at, tzinfo=tz).astimezone(UTC)",
        new="        candidate = datetime.combine(day, at, tzinfo=UTC)",
        tests=["tests/unit/test_timer_rules.py::TestAWeekdayRule::test_stays_nine_on_the_owners_clock_across_the_spring_change"],
    ),
    Control(
        describes="ONCE: a notification with a seen key is not written twice",
        path="core/notifications.py",
        old='                    "INSERT OR IGNORE INTO notifications (notification_id, user_id, "',
        new='                    "INSERT INTO notifications (notification_id, user_id, "',
        tests=["tests/unit/test_reminders.py::TestWhenItFires::test_delivered_twice_it_is_one_notice"],
    ),
    Control(
        describes="REMINDERS: nobody else cancels yours",
        path="core/timers.py",
        old=('                "DELETE FROM timers WHERE kind = ? AND key = ? AND owner_user_id = ?",\n'
             '                (kind, key, owner_user_id))'),
        new='                "DELETE FROM timers WHERE kind = ? AND key = ?",\n                (kind, key))',
        tests=["tests/integration/test_reminder_routes.py::test_nobody_else_sees_or_cancels_it"],
    ),
    Control(
        describes="REMINDERS: a reminder that could not be written is retried",
        path="core/reminders.py",
        old="    if written is None:\n        raise RuntimeError",
        new="    if False:\n        raise RuntimeError",
        tests=["tests/unit/test_reminders.py::TestWhenItFires::test_a_notice_that_could_not_be_written_is_retried"],
    ),
    Control(
        describes="REMINDERS: a disabled owner is not reminded",
        path="core/reminders.py",
        old="    if owner is None or not user_is_active(owner):",
        new="    if owner is None:",
        tests=["tests/unit/test_reminders.py::TestWhenItFires::test_a_disabled_owner_is_not_reminded"],
    ),
    Control(
        describes="COMBINED: a change to any condition's view reaches the trigger",
        path="core/trigger_runs.py",
        old=("                if any(view is not None and include(trigger, view)\n"
             "                       for view in _views_of(trigger, views))]"),
        new=("                if (view := views.get(trigger.view_id)) is not None\n"
             "                and include(trigger, view)]"),
        tests=["tests/integration/test_combined_triggers.py::TestAllOrAny::test_all_fires_when_the_last_part_becomes_true"],
    ),
    Control(
        describes="COMBINED: all means all",
        path="core/trigger_states.py",
        old='        met = all(met_each) if trigger.combine == "all" else any(met_each)',
        new="        met = any(met_each)",
        tests=["tests/integration/test_combined_triggers.py::TestAllOrAny::test_all_fires_when_the_last_part_becomes_true"],
    ),
    Control(
        describes="COMBINED: it fires once while it stays true",
        path="core/trigger_states.py",
        old="        if not fired and stamp - since >= hold:",
        new="        if stamp - since >= hold:",
        tests=["tests/integration/test_combined_triggers.py::TestAllOrAny::test_it_fires_once_while_it_stays_true"],
    ),
    Control(
        describes="COMBINED: true when made is a baseline, not a firing",
        path="core/trigger_states.py",
        old=("                       State(met, stamp if met else None, met, digest))\n"
             "            if previous is None:"),
        new=("                       State(met, stamp if met else None, False, digest))\n"
             "            if previous is None:"),
        tests=["tests/integration/test_combined_triggers.py::TestAllOrAny::test_already_true_when_made_does_not_fire_for_it"],
    ),
    Control(
        describes="COMBINED: a hold restarts when the condition stops being true",
        path="core/trigger_states.py",
        old=("            states.put(trigger.trigger_id, user_id, State(False, None, False, digest))\n"
             "            continue"),
        new="            continue",
        tests=["tests/integration/test_combined_triggers.py::TestHeldForAWhile::test_true_again_after_a_gap_holds_from_the_new_start"],
    ),
    Control(
        describes="COMBINED: a held trigger sets its hold timer",
        path="core/trigger_runs.py",
        old="                schedule_hold(timers, states, trigger)",
        new="                pass",
        tests=["tests/integration/test_combined_triggers.py::TestHeldForAWhile::test_fires_when_the_hold_ends_not_before"],
    ),
    Control(
        describes="COMBINED: a scheduled trigger tells nobody between its checks",
        path="core/trigger_states.py",
        old="            if on_schedule is not None and met:",
        new="            if met:",
        tests=["tests/integration/test_combined_triggers.py::TestOnASchedule::test_a_change_between_checks_tells_nobody"],
    ),
    Control(
        describes="COMBINED: one scheduled notice per occurrence per person",
        path="core/trigger_states.py",
        old='                                     dedupe_key=f"{on_schedule}/{user_id}")',
        new="                                     )",
        tests=["tests/integration/test_combined_triggers.py::TestOnASchedule::test_each_check_while_true_tells_once"],
    ),
    Control(
        describes="COMBINED: a missed scheduled check is said",
        path="api/trigger_checks.py",
        old="    if firing.missed:\n        from datetime import UTC, datetime",
        new="    if False:\n        from datetime import UTC, datetime",
        tests=["tests/integration/test_combined_triggers.py::TestOnASchedule::test_a_missed_check_is_said"],
    ),
    Control(
        describes="COMBINED: deleting a trigger stops its timers",
        path="api/routes.py",
        old=("    disarm(_timer_store(request), TriggerStateStore(request.app.state.runtime_paths.data_dir),\n"
             "           trigger_id)\n    return {\"deleted\": True}"),
        new="    return {\"deleted\": True}",
        tests=["tests/integration/test_combined_triggers.py::TestOnASchedule::test_deleting_it_stops_its_check"],
    ),
    Control(
        describes="COMBINED ACTIONS: proposed only when the owner's state fired",
        path="core/count_condition.py",
        old="    if result.owner_fired and trigger.action_type and write_mediator is not None:",
        new="    if trigger.action_type and write_mediator is not None:",
        tests=["tests/unit/test_combined_trigger_actions.py::TestWhenItProposes::test_not_on_the_baseline"],
    ),
    Control(
        describes="COMBINED ACTIONS: on the chosen condition's objects",
        path="core/count_condition.py",
        old="        chosen = next(view for view in views if view.view_id == action_view_id(trigger))",
        new="        chosen = views[0]",
        tests=["tests/unit/test_combined_trigger_actions.py::TestWhenItProposes::test_on_the_chosen_conditions_objects"],
    ),
    Control(
        describes="COMBINED ACTIONS: a scheduled check that finds it true proposes",
        path="core/trigger_states.py",
        old=("                told += 1\n"
             "                owner_fired = owner_fired or user_id == owner.user_id\n            continue"),
        new="                told += 1\n            continue",
        tests=["tests/unit/test_combined_trigger_actions.py::TestWhenItProposes::test_at_each_scheduled_check_while_true_but_not_again_for_what_waits"],
    ),
    Control(
        describes="COMBINED ACTIONS: objects only from the trigger's own conditions",
        path="core/trigger_states.py",
        old="    if action_view is not None and action_view not in {",
        new="    if False and action_view not in {",
        tests=["tests/unit/test_combined_trigger_actions.py::TestWhatMayBeChosen::test_not_some_other_view_even_of_its_owner"],
    ),
    Control(
        describes="DECLARED: a combined config.yaml trigger is evaluated as a state",
        path="core/trigger_runs.py",
        old="    for trigger in declared:\n        if is_state_trigger(trigger):",
        new="    for trigger in declared:\n        if False:",
        tests=["tests/unit/test_declared_combined_triggers.py::TestItRuns::test_held_and_combined_it_proposes_on_the_named_conditions_objects"],
    ),
    Control(
        describes="DECLARED: objects_from names the condition whose objects the action takes",
        path="core/declared_triggers.py",
        old="                action_view_id = names[objects_from]",
        new="                action_view_id = None",
        tests=["tests/unit/test_declared_combined_triggers.py::TestItParses::test_conditions_combine_hold_and_where_the_action_takes_its_objects"],
    ),
    Control(
        describes="DECLARED: the action is checked against the condition it takes objects from",
        path="core/declared_triggers.py",
        old="                          if view.view_id == (action_view_id or own_view.view_id))",
        new="                          if view.view_id == own_view.view_id)",
        tests=["tests/unit/test_declared_combined_triggers.py::TestRefusedAtLoad::test_an_action_on_a_condition_of_the_wrong_type"],
    ),
    Control(
        describes="DECLARED: a schedule check finds a config.yaml trigger",
        path="api/trigger_checks.py",
        old="                  *app.state.generation.config.declared_triggers]",
        new="                  ]",
        tests=["tests/integration/test_combined_triggers.py::test_a_scheduled_config_yaml_trigger_is_checked_by_its_timer"],
    ),
    Control(
        describes="DECLARED: a reload sets config.yaml's schedules",
        path="api/reload.py",
        old=("                arm_declared(TimerStore(app.state.runtime_paths.data_dir),\n"
             "                             new.config.declared_triggers)"),
        new="                pass",
        tests=["tests/integration/test_combined_triggers.py::test_a_reload_sets_the_check_of_a_scheduled_config_yaml_trigger"],
    ),
    Control(
        describes="DECLARED: a schedule removed from config.yaml is cancelled",
        path="core/trigger_states.py",
        old='        if key.startswith("declared/") and key not in wanted:',
        new="        if False:",
        tests=["tests/unit/test_declared_combined_triggers.py::TestItsScheduleIsSet::test_set_left_alone_moved_and_cancelled_with_config_yaml"],
    ),
    Control(
        describes="DECLARED: an unchanged schedule is not moved by a reload",
        path="core/trigger_states.py",
        old="        if existing is None or existing.repeat != trigger.schedule:",
        new="        if True:",
        tests=["tests/unit/test_declared_combined_triggers.py::TestItsScheduleIsSet::test_set_left_alone_moved_and_cancelled_with_config_yaml"],
    ),
    Control(
        describes="COMBINED: gaining and losing are not combined",
        path="core/trigger_states.py",
        old="    if gained is not None or fell is not None:",
        new="    if False:",
        tests=["tests/integration/test_combined_triggers.py::TestRefusedWithTheReason::test_refused"],
    ),
    Control(
        describes="TRIGGERS: a saved change checks the triggers watching its types",
        path="api/routes.py",
        old="            checks.after_change({sub.object_type for sub in pending.sub_writes})",
        new="            pass",
        tests=["tests/integration/test_trigger_checks.py::TestWhenAChangeIsSaved::test_a_saved_change_fires_the_trigger_it_moved"],
    ),
    Control(
        describes="TRIGGERS: a new trigger is checked when it is made",
        path="api/routes.py",
        old="        checks.after_made(trigger_id)",
        new="        pass",
        tests=["tests/integration/test_trigger_checks.py::TestWhenATriggerIsMade::test_it_is_checked_at_once"],
    ),
    Control(
        describes="TRIGGERS: changes saved during a check become one more check",
        path="api/trigger_checks.py",
        old=("            if self._running:\n"
             "                # GATHERED for the run already going to take them.\n"
             "                return\n"),
        new="",
        tests=["tests/integration/test_trigger_checks.py::TestCoalescing::test_changes_during_a_check_become_one_more_check"],
    ),
    Control(
        describes="TRIGGERS: one evaluation at a time across processes",
        path="core/trigger_runs.py",
        old="        fcntl.flock(lock, fcntl.LOCK_EX)\n",
        new="",
        tests=["tests/integration/test_trigger_checks.py::TestOneAtATime::test_a_second_evaluation_waits_for_the_first"],
    ),
    Control(
        describes="FILTERS: a relative date is made absolute before storage sees it",
        path="core/filters.py",
        old='    if condition.operator != "relative_date":\n        return condition',
        new="    if True:\n        return condition",
        tests=["tests/integration/test_relative_dates_answer.py::test_in_the_last_n_days"],
    ),
    Control(
        describes="SEARCH: a saved change is found before the next sync",
        path="core/ontology/mediator.py",
        old="            entry for entry in [*self.write_log.get_all_pending_writes(), *applied]",
        new="            entry for entry in self.write_log.get_all_pending_writes()",
        tests=["tests/integration/test_search_sees_saved_changes.py::test_found_by_its_new_value_and_not_its_old"],
    ),
    Control(
        describes="INBOX: a merge counts only for someone who may write its type",
        path="api/routes.py",
        old="        if (authorize(current_user, roles, f\"write:{proposal.object_type}\")",
        new="        if (True",
        tests=["tests/integration/test_inbox_app.py::TestTheCounts::test_a_merge_counts_only_for_someone_who_may_decide_it"],
    ),
    Control(
        describes="INBOX: a merge whose side the caller cannot see is not counted",
        path="api/routes.py",
        old="                and _proposal_sides(request, current_user, proposal) is not None):",
        new="                and True):",
        tests=["tests/integration/test_inbox_app.py::TestTheCounts::test_a_merge_whose_side_they_cannot_see_is_not_counted"],
    ),
    Control(
        describes="PENDING-IN-CONTEXT: an object shows only writes the Inbox would show the caller",
        path="api/routes.py",
        old=("        return may_confirm(candidate) or candidate.user_id == current_user.user_id\n\n"
             "    store: PendingWriteStore = request.app.state.pending_writes\n    touching"),
        new="        return True\n\n    store: PendingWriteStore = request.app.state.pending_writes\n    touching",
        tests=["tests/integration/test_pending_in_context.py::test_someone_who_may_not_decide_it_and_did_not_propose_it_sees_nothing"],
    ),
    Control(
        describes="PENDING-IN-CONTEXT: an unreadable object answers as nothing waiting",
        path="api/routes.py",
        old="                if _may_read_object(generation.mediator, current_user, object_type, object_id)}",
        new="                if True}",
        tests=["tests/integration/test_pending_in_context.py::test_an_object_they_cannot_read_is_answered_as_nothing_waiting"],
    ),
    Control(
        describes="ASK-ABOUT-SET: a field the asker cannot read is refused",
        path="core/agent/set_context.py",
        old="        if condition.field not in fields:",
        new="        if False:",
        tests=["tests/unit/test_set_context.py::TestRefused::test_a_field_the_asker_cannot_read_reads_as_unknown"],
    ),
    Control(
        describes="NOTIFICATION-DOORS: an object the reader may no longer read is not linked",
        path="api/routes.py",
        old="        if _may_read_object(mediator, user, object_type, object_id):\n            doors.append",
        new="        if True:\n            doors.append",
        tests=["tests/integration/test_inbox_app.py::TestNotificationDoors::test_one_they_can_no_longer_read_is_not_named"],
    ),
    Control(
        describes="MODEL-503: an unreachable model is a 503 naming no host",
        path="api/app.py",
        old="    @app.exception_handler(LLMUnavailable)",
        new="    @app.exception_handler(KeyboardInterrupt)",
        tests=["tests/integration/test_asking_about_a_set.py::test_a_model_that_cannot_be_reached_is_a_503_that_names_no_host"],
    ),
    Control(
        describes="E4: ordering by a field the caller may not read is ignored",
        path="api/routes.py",
        old='    if field_def is None or field_def.get("readable") is False:',
        new="    if field_def is None:",
        tests=["tests/integration/test_a_field_they_may_not_read.py::"
               "test_sorting_by_it_is_ignored_and_reads_nothing_more"],
    ),
    Control(
        describes="CANVAS: security chains only for someone who may change roles",
        path="api/routes.py",
        old=('    if authorize(current_user, generation.config.roles, "manage:roles"):\n'
             '        layout["security_chains"]'),
        new='    if True:\n        layout["security_chains"]',
        tests=["tests/integration/test_the_ontology_canvas.py::TestTheSecurityLayer::test_anyone_else_gets_no_key_at_all_rather_than_an_empty_list"],
    ),
    Control(
        describes="CANVAS: a position for a type the caller cannot see is not kept",
        path="core/canvas_layout.py",
        old="        if type_name in visible:\n            positions[type_name]",
        new="        if True:\n            positions[type_name]",
        tests=["tests/integration/test_the_ontology_canvas.py::test_a_type_they_cannot_see_is_dropped_and_the_answer_says_what_was_kept"],
    ),
    Control(
        describes="CANVAS: a stored layout is cleaned again when it is read",
        path="api/routes.py",
        old="        layout = clean_layout(document, visible)\n",
        new="        layout = {**{'positions': {}, 'areas': []}, **document}\n",
        tests=["tests/integration/test_the_ontology_canvas.py::test_a_type_whose_grant_was_withdrawn_is_not_named_back"],
    ),
    Control(
        describes="READ-BACK: an answer's read-back and doors are built from real data only",
        path="api/routes.py",
        old=("        read_back=read_back(real_data, agent_schema),\n"
             "        doors=doors(real_data, agent_schema),"),
        new=("        read_back=read_back(result.gathered, agent_schema),\n"
             "        doors=doors(result.gathered, agent_schema),"),
        tests=["tests/integration/test_an_answer_comes_with_context.py::test_a_DENIED_read_is_never_read_back"],
    ),
    Control(
        describes="CONFIG-EDIT: only manage:deployment may change the deployment",
        path="api/routes.py",
        old='    if not authorize(current_user, _generation(request).config.roles, "manage:deployment"):\n'
            '        raise HTTPException(status_code=403, detail="Needs manage:deployment")',
        new="    if False:\n        pass",
        tests=["tests/integration/test_editing_config_from_the_ui.py::test_someone_who_manages_users_but_not_the_deployment_may_not"],
    ),
    Control(
        describes="CONFIG-EDIT: a file changed since it was read is not overwritten",
        path="api/routes.py",
        old=("    if digest(current) != body.digest:\n        raise HTTPException(status_code=409, detail=(\n"
             "            \"config.yaml has changed"),
        new=("    if False:\n        raise HTTPException(status_code=409, detail=(\n"
             "            \"config.yaml has changed"),
        tests=["tests/integration/test_editing_config_from_the_ui.py::test_a_change_since_it_was_read_is_refused_not_overwritten"],
    ),
    Control(
        describes="DEV_UI 13.7: an ontology changed since it was read is not overwritten",
        path="api/routes.py",
        old=("    if digest(current) != read_digest:\n        raise HTTPException(status_code=409, detail=(\n"
             "            f\"{ONTOLOGY_FILE} has changed"),
        new=("    if False:\n        raise HTTPException(status_code=409, detail=(\n"
             "            f\"{ONTOLOGY_FILE} has changed"),
        tests=["tests/integration/test_describing_the_ontology.py::test_a_change_since_it_was_read_is_refused_not_overwritten"],
    ),
    Control(
        describes="CONFIG-EDIT: a file that would not load never reaches the disk",
        path="api/routes.py",
        old="        _load_candidate(request, {name: proposed for name, (_, proposed) in files.items()})\n",
        new="        pass\n",
        tests=["tests/integration/test_editing_config_from_the_ui.py::test_a_file_that_would_not_load_never_reaches_the_disk",
               "tests/integration/test_describing_the_ontology.py::test_a_title_the_loader_refuses_never_reaches_the_disk"],
    ),
    Control(
        describes="CONFIG-EDIT: a failed reload puts the old file back",
        path="api/routes.py",
        old="            staged.write_text(files[filename][0])\n            os.replace(staged, path)\n",
        new="",
        tests=["tests/integration/test_editing_config_from_the_ui.py::test_a_reload_that_fails_puts_the_old_file_back"],
    ),
    Control(
        describes='ENRICH-VOTE: a tie for the heaviest answer is left empty',
        path='core/ontology/enriched_fields.py',
        old='    return first_seen[winners[0]] if len(winners) == 1 else None',
        new='    return first_seen[winners[0]]',
        tests=['tests/unit/test_enriched_fields.py::TestSeveralRuleSetsVote::test_a_tie_is_left_empty_rather_than_guessed',
               'tests/integration/test_enriched_fields_reach_gold.py::test_an_approved_vote_fills_the_field_and_its_review_shows_every_set'],
    ),
    Control(
        describes='ENRICH-VOTE: a set votes with its weight, not one each',
        path='core/ontology/enriched_fields.py',
        old='votes[key] = votes.get(key, 0.0) + member["weight"]',
        new='votes[key] = votes.get(key, 0.0) + 1.0',
        tests=['tests/unit/test_enriched_fields.py::TestSeveralRuleSetsVote::test_the_heavier_side_wins_and_lone_answers_stand'],
    ),
    Control(
        describes='ENRICH-VOTE: every member is checked as one rule set is',
        path='core/ontology/enriched_fields.py',
        old='rules = check_rules(member["rules"], enrichment)',
        new='rules = member["rules"]',
        tests=['tests/unit/test_enriched_fields.py::TestSeveralRuleSetsVote::test_every_member_is_checked_as_a_rule_set_is'],
    ),
    Control(
        describes='ENRICH-VOTE: a weight is bounded',
        path='core/ontology/enriched_fields.py',
        old='or not 0 < weight <= MAX_WEIGHT):',
        new='or not 0 < weight):',
        tests=['tests/unit/test_enriched_fields.py::TestSeveralRuleSetsVote::test_a_malformed_vote_is_refused'],
    ),
    Control(
        describes='ENRICH-VOTE: the vote is chosen only when strictly better on the examples',
        path='core/agent/enrichment_compiler.py',
        old='if _score(vote_on_train) > _score(best_on_train):',
        new='if _score(vote_on_train) >= _score(best_on_train):',
        tests=['tests/unit/test_enrichment_compiler.py::test_a_vote_no_better_than_the_best_single_set_is_not_chosen'],
    ),
    Control(
        describes='ENRICH-VOTE: a set no better than a coin has no vote',
        path='core/agent/enrichment_compiler.py',
        old='if result["covered"] and weight_of(result) > 0),',
        new='if result["covered"]),',
        tests=['tests/unit/test_enrichment_compiler.py::test_the_vote_is_of_sets_better_than_even_odds_heaviest_first'],
    ),
    Control(
        describes="ENRICH-VOTE: the shown score is the chosen recipe's, on rows neither saw",
        path='core/agent/enrichment_compiler.py',
        old='held_out = judge(chosen, test)',
        new='held_out = judge(best_rules, test)',
        tests=['tests/unit/test_enrichment_compiler.py::test_sets_that_each_know_one_answer_are_combined_when_that_is_better'],
    ),
    Control(
        describes='ENRICH-VOTE: the approver is shown every set',
        path='api/routes.py',
        old='"rule_sets": describe_recipe(recipe.rules)',
        new='"rule_sets": []',
        tests=['tests/integration/test_enriched_fields_reach_gold.py::test_an_approved_vote_fills_the_field_and_its_review_shows_every_set'],
    ),
    Control(
        describes='EXTRACT: a sign stays with its number',
        path='core/ontology/extraction_rules.py',
        old='_TOKEN = re.compile(r"(?:(?<!\\w)[-+](?=\\d))?\\w+(?:[-_/.,]\\w+)*|[^\\w\\s]", re.UNICODE)',
        new='_TOKEN = re.compile(r"\\w+(?:[-_/.,]\\w+)*|[^\\w\\s]", re.UNICODE)',
        tests=[
            'tests/unit/test_extraction_rules.py::TestShapes::test_each_shape_takes_its_kind_of_value_as_written',
        ],
    ),
    Control(
        describes='EXTRACT: punctuation between phrase and value is not counted',
        path='core/ontology/extraction_rules.py',
        old='        if not _IS_WORD.search(token):\n            # PUNCTUATION',
        new='        if False:\n            # PUNCTUATION',
        tests=[
            'tests/unit/test_extraction_rules.py::TestWhereTheValueIs::test_punctuation_between_is_skipped_and_words_are_counted',
        ],
    ),
    Control(
        describes='EXTRACT: a rule looks no further than `within` words',
        path='core/ontology/extraction_rules.py',
        old='while index < len(found) and looked < within:',
        new='while index < len(found) and looked < within + 5:',
        tests=[
            'tests/unit/test_extraction_rules.py::TestWhereTheValueIs::test_punctuation_between_is_skipped_and_words_are_counted',
        ],
    ),
    Control(
        describes="EXTRACT: a model's sample answer must be copied from the record",
        path='core/agent/enrichment_compiler.py',
        old='    if not any(_folded(value) in _folded(text) for text in record.values() if text):',
        new='    if False:',
        tests=[
            'tests/unit/test_enrichment_compiler.py::test_an_extracted_label_must_be_copied_from_the_record_and_be_its_type',
        ],
    ),
    Control(
        describes="EXTRACT: a model's sample answer must be of the field's type",
        path='core/agent/enrichment_compiler.py',
        old='    if typed(value, enrichment.extract, locale) is None:\n        return UNUSABLE',
        new='    if False:\n        return UNUSABLE',
        tests=[
            'tests/unit/test_enrichment_compiler.py::test_an_extracted_label_must_be_copied_from_the_record_and_be_its_type',
        ],
    ),
    Control(
        describes='EXTRACT: rules are scored on the value as gold will type it',
        path='core/agent/enrichment_compiler.py',
        old='            value = typed(value, extract, locale)',
        new='            pass',
        tests=[
            'tests/unit/test_enrichment_compiler.py::test_a_span_that_does_not_convert_is_not_an_answer',
        ],
    ),
    Control(
        describes="EXTRACT: a choices field's hash, and its approval, is unchanged",
        path='core/ontology/enriched_fields.py',
        old='    if enrichment.extract is not None:\n        # ONLY WHEN EXTRACTING',
        new='    if True:\n        # ONLY WHEN EXTRACTING',
        tests=[
            'tests/unit/test_enriched_fields.py::TestAValueTakenFromTheText::test_a_choices_fields_hash_and_so_its_approval_is_unchanged',
        ],
    ),
    Control(
        describes="EXTRACT: a rule takes only a shape its field's type can hold",
        path='core/ontology/enriched_fields.py',
        old='    if shape not in shapes:',
        new='    if shape not in SHAPES_FOR["string"]:',
        tests=[
            'tests/unit/test_enriched_fields.py::TestAValueTakenFromTheText::test_a_shape_that_cannot_become_the_fields_type_is_refused',
        ],
    ),
    Control(
        describes="EXTRACT: gold stores the value as the field's type",
        path='core/mirror/gold_arrow.py',
        old='            values = [typed(value, enrichment.extract, locale) for value in values]',
        new='            values = list(values)',
        tests=[
            'tests/unit/test_enriched_fields.py::TestGold::test_an_extracted_amount_is_typed_by_the_sources_locale',
            'tests/integration/test_enriched_fields_reach_gold.py::test_an_extracted_number_reaches_gold_typed_and_its_review_says_what_it_takes',
        ],
    ),
    Control(
        describes="EXTRACT: gold reads the text by the source's locale",
        path='core/mirror/enrichment.py',
        old='                fields[field_name][APPROVED_LOCALE] = locale',
        new='                fields[field_name][APPROVED_LOCALE] = None',
        tests=[
            'tests/unit/test_enriched_fields.py::TestGold::test_an_extracted_amount_is_typed_by_the_sources_locale',
        ],
    ),
    Control(
        describes='EXTRACT: votes agree on a value written differently',
        path='core/ontology/enriched_fields.py',
        old='            key = " ".join(value.casefold().split())',
        new='            key = value',
        tests=[
            'tests/unit/test_enriched_fields.py::TestAValueTakenFromTheText::test_sets_that_found_the_same_value_written_differently_agree',
        ],
    ),
    Control(
        describes='EXTRACT: the approver is told what kind of value is taken',
        path='api/routes.py',
        old='        "extracts": enrichment.extract,',
        new='        "extracts": None,',
        tests=[
            'tests/integration/test_enriched_fields_reach_gold.py::test_an_extracted_number_reaches_gold_typed_and_its_review_says_what_it_takes',
        ],
    ),
    Control(
        describes='MEANING: a classified field is never embedded',
        path='core/ontology/semantic_search.py',
        old='            if labels:\n                raise ValueError(f"{where}: {name!r} is classified',
        new='            if False:\n                raise ValueError(f"{where}: {name!r} is classified',
        tests=[
            'tests/unit/test_embeddings.py::TestTheDeclaration::test_one_that_could_not_be_embedded_safely_is_refused_at_load',
        ],
    ),
    Control(
        describes='MEANING: a declaration needs a model to embed with',
        path='core/ontology/semantic_search.py',
        old='        if not embedding_model:',
        new='        if False:',
        tests=[
            'tests/unit/test_embeddings.py::TestTheDeclaration::test_one_that_could_not_be_embedded_safely_is_refused_at_load',
        ],
    ),
    Control(
        describes='MEANING: ranking needs reading every field the text is made from',
        path='core/ontology/mediator.py',
        old='    return all((visible_fields.get(name) or {}).get("readable") is True for name in search.inputs)',
        new='    return True',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_without_reading_the_text_there_is_no_search_by_meaning',
        ],
    ),
    Control(
        describes='MEANING: knowing a field exists is not reading it',
        path='core/ontology/mediator.py',
        old='    return all((visible_fields.get(name) or {}).get("readable") is True for name in search.inputs)',
        new='    return all(name in visible_fields for name in search.inputs)',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_knowing_a_field_exists_is_not_reading_it',
        ],
    ),
    Control(
        describes='MEANING: a ranking keeps only rows this person may read',
        path='core/ontology/mediator.py',
        old='if check_access(self, user_record, self.roles, object_type, candidate, action, context):',
        new='if True:',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_a_search_finds_by_meaning_what_its_words_did_not',
            'tests/integration/test_search_by_meaning.py::test_similar_records_rank_by_the_objects_own_vector_without_calling_the_model',
        ],
    ),
    Control(
        describes='MEANING: a deleted record is never ranked',
        path='core/ontology/mediator.py',
        old='        candidates = self._without_deleted(object_type, list(object_ids))',
        new='        candidates = list(object_ids)',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_a_deleted_record_is_never_ranked',
        ],
    ),
    Control(
        describes='MEANING: word matches are not repeated as meaning matches',
        path='core/meaning_search.py',
        old='        ranked = [object_id for object_id in nearest(matrix, query) if object_id not in skip]',
        new='        ranked = list(nearest(matrix, query))',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_a_word_match_is_not_repeated_as_a_meaning_match',
        ],
    ),
    Control(
        describes='MEANING: a record is not its own similar record',
        path='core/meaning_search.py',
        old='        ranked = nearest(matrix, matrix.vectors[position], exclude=str(object_id))',
        new='        ranked = nearest(matrix, matrix.vectors[position], exclude=None)',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_similar_records_rank_by_the_objects_own_vector_without_calling_the_model',
        ],
    ),
    Control(
        describes='MEANING: no similar records for a record you cannot read',
        path='core/meaning_search.py',
        old='        if not mediator.readable_in_order(user_record, object_type, [object_id], 1,',
        new='        if False and not mediator.readable_in_order(user_record, object_type, [object_id], 1,',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_a_record_in_another_region_has_no_similar_records_for_you',
        ],
    ),
    Control(
        describes='MEANING: a stale vector goes before anything is embedded',
        path='core/embeddings.py',
        old='    report.removed = store.remove(object_type, stale)',
        new='    report.removed = 0',
        tests=[
            'tests/unit/test_embeddings.py::TestRefreshing::test_a_row_whose_text_changed_loses_its_old_vector_first',
        ],
    ),
    Control(
        describes='MEANING: vectors of two model versions are never compared',
        path='core/embeddings.py',
        old='"WHERE object_type = ? AND version = ? ORDER BY object_id",',
        new='"WHERE object_type = ? AND (version = ? OR 1) ORDER BY object_id",',
        tests=[
            'tests/unit/test_embeddings.py::TestRefreshing::test_a_new_model_version_embeds_everything_again',
        ],
    ),
    Control(
        describes='MEANING: the sync embeds within its budget',
        path='core/embeddings.py',
        old='        if clock() - started >= budget_seconds:',
        new='        if False:',
        tests=[
            'tests/unit/test_embeddings.py::TestRefreshing::test_the_budget_stops_it_and_the_next_run_carries_on',
        ],
    ),
    Control(
        describes='MEANING: blank text is not embedded',
        path='core/embeddings.py',
        old='        if text and text.strip():',
        new='        if text:',
        tests=[
            'tests/unit/test_embeddings.py::TestRefreshing::test_rows_gone_from_gold_and_rows_with_no_text_are_removed',
        ],
    ),
    Control(
        describes='MEANING: a failure to embed never fails the sync',
        path='scripts/run_sync.py',
        old="        except Exception as exc:  # noqa: BLE001 - never the sync's verdict",
        new="        except ZeroDivisionError as exc:  # noqa: BLE001 - never the sync's verdict",
        tests=[
            'tests/integration/test_search_by_meaning.py::test_a_failure_to_embed_never_fails_the_sync',
        ],
    ),
    Control(
        describes='MEANING: a type no longer declared loses its vectors',
        path='scripts/run_sync.py',
        old='    for gone in store.declared_types() - set(declared):',
        new='    for gone in set():',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_a_type_no_longer_declared_loses_its_vectors',
        ],
    ),
    Control(
        describes='MEANING: the embedder asks the generic endpoint on the server origin',
        path='adapters/embedding_adapter.py',
        old='        url = f"{self.origin}/v1/embeddings"',
        new='        url = f"{self.origin}/api/embed"',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_it_asks_the_generic_endpoint_on_the_chat_servers_origin',
        ],
    ),
    Control(
        describes='MEANING: a reply without one vector per text is refused',
        path='adapters/embedding_adapter.py',
        old='        if [int(entry["index"]) for entry in ordered] != list(range(len(texts))) or not all(',
        new='        if False and not all(',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_a_reply_without_one_vector_per_text_is_unavailable',
        ],
    ),
    Control(
        describes='MEANING: stored text and asked text get their task prefixes',
        path='adapters/embedding_adapter.py',
        old='        return self._embed([self.prefixes["query"] + text], timeout)[0]',
        new='        return self._embed([text], timeout)[0]',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_a_model_that_needs_task_prefixes_gets_them',
        ],
    ),
    Control(
        describes="MEANING: a model family's required prefixes are its default",
        path='adapters/embedding_adapter.py',
        old='        if model.startswith(family):',
        new='        if False:',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_a_model_that_needs_task_prefixes_gets_them',
        ],
    ),
    Control(
        describes='MEANING: vectors are put back in the order asked',
        path='adapters/embedding_adapter.py',
        old='            ordered = sorted(data, key=lambda entry: int(entry["index"]))',
        new='            ordered = list(data)',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_vectors_come_back_in_the_order_asked_whatever_order_they_arrive',
        ],
    ),
    Control(
        describes='MEANING: the version changes with the prefixes',
        path='adapters/embedding_adapter.py',
        old='        return f"{weights}{size}{prefixes}"',
        new='        return f"{weights}{size}"',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_its_version_names_the_weights_and_the_prefixes',
        ],
    ),
    Control(
        describes='MEANING: a provider with no server is told at load',
        path='core/deployment_loader.py',
        old='    if not url:\n        raise ValueError(f"llm.embedding_model is set, but provider',
        new='    if False:\n        raise ValueError(f"llm.embedding_model is set, but provider',
        tests=[
            'tests/unit/test_embeddings.py::TestTheSettings::test_a_provider_with_no_server_is_told_to_name_one',
        ],
    ),
    Control(
        describes='MEANING-AGENT: the step is offered only for types searchable by meaning',
        path='core/llm/step_schema.py',
        old='    if features.meaning_search and definition.get("searchable_by_meaning"):',
        new='    if features.meaning_search:',
        tests=[
            'tests/unit/test_agent_features.py::TestMeaningSearch::test_only_types_searchable_by_meaning_are_marked_and_offered',
        ],
    ),
    Control(
        describes='MEANING-AGENT: the prompt marks types only with the switch on',
        path='core/llm/agent_step_prompt.py',
        old='    if mark_meaning and definition.get("searchable_by_meaning"):',
        new='    if definition.get("searchable_by_meaning"):',
        tests=[
            'tests/unit/test_agent_features.py::TestMeaningSearch::test_only_types_searchable_by_meaning_are_marked_and_offered',
        ],
    ),
    Control(
        describes='MEANING-AGENT: a ranking that cannot answer says why',
        path='core/agent/agentic_loop.py',
        old='        if ranked is None or not ranked.available:',
        new='        if ranked is None:',
        tests=[
            'tests/unit/test_agent_features.py::TestMeaningSearch::test_when_it_cannot_answer_the_model_is_told_why_not_handed_an_empty_list',
        ],
    ),
    Control(
        describes='MEANING-AGENT: the step without an embedding model is refused at load',
        path='core/deployment_loader.py',
        old='    if config.agent_features.meaning_search and meaning is None and data_dir is not None:',
        new='    if False:',
        tests=[
            'tests/integration/test_search_by_meaning.py::test_the_agent_step_without_an_embedding_model_is_refused_at_load',
        ],
    ),
    Control(
        describes='MEANING-SIZE: a smaller size is asked of the server',
        path='adapters/embedding_adapter.py',
        old='            payload["dimensions"] = self.dimensions',
        new='            pass',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_a_smaller_size_is_asked_for_and_held_to',
        ],
    ),
    Control(
        describes='MEANING-SIZE: a vector of another size is refused, not cut',
        path='adapters/embedding_adapter.py',
        old='        if self.dimensions is not None and any(len(vector) != self.dimensions',
        new='        if False and any(len(vector) != self.dimensions',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_a_smaller_size_is_asked_for_and_held_to',
        ],
    ),
    Control(
        describes='MEANING-SIZE: the size is part of the version',
        path='adapters/embedding_adapter.py',
        old='        return f"{weights}{size}{prefixes}"',
        new='        return f"{weights}{prefixes}"',
        tests=[
            'tests/unit/test_embeddings.py::TestTheEmbedder::test_the_size_is_part_of_the_version',
        ],
    ),
    Control(
        describes='MEANING-SIZE: an impossible size is refused at load',
        path='core/deployment_loader.py',
        old='                                   or not 16 <= dimensions <= 8192):',
        new='                                   or not 0 <= dimensions):',
        tests=[
            'tests/unit/test_embeddings.py::TestTheSettings::test_a_bad_setting_is_refused_with_the_reason',
        ],
    ),
    Control(
        describes='PREDICT: a classified answer is never learned about',
        path='core/ontology/predicted_fields.py',
        old='            if field_classifications(answer):',
        new='            if False:',
        tests=[
            'tests/unit/test_predictions.py::TestTheDeclaration::test_a_prediction_that_could_not_be_learned_safely_is_refused',
        ],
    ),
    Control(
        describes='PREDICT: a classified input is never learned from',
        path='core/ontology/predicted_fields.py',
        old='        labels = field_classifications(source)\n        if labels:',
        new='        labels = field_classifications(source)\n        if False:',
        tests=[
            'tests/unit/test_predictions.py::TestTheDeclaration::test_a_prediction_that_could_not_be_learned_safely_is_refused',
        ],
    ),
    Control(
        describes='PREDICT: the answer is never an input',
        path='core/ontology/predicted_fields.py',
        old='        if name in (field_name, prediction.target):',
        new='        if name == field_name:',
        tests=[
            'tests/unit/test_predictions.py::TestTheDeclaration::test_a_prediction_that_could_not_be_learned_safely_is_refused',
        ],
    ),
    Control(
        describes='PREDICT: the id is never an input',
        path='core/ontology/predicted_fields.py',
        old='        if name == type_def.get("id_field"):',
        new='        if False:',
        tests=[
            'tests/unit/test_predictions.py::TestTheDeclaration::test_a_prediction_that_could_not_be_learned_safely_is_refused',
        ],
    ),
    Control(
        describes='PREDICT: reading a prediction needs reading its answer',
        path='core/ontology/derived_fields.py',
        old='    derived += [(type_name, field_name, (*prediction.inputs, prediction.target))',
        new='    derived += [(type_name, field_name, prediction.inputs)',
        tests=[
            'tests/unit/test_predictions.py::TestTheDeclaration::test_reading_a_prediction_needs_reading_the_answer_and_every_input',
        ],
    ),
    Control(
        describes='PREDICT: the model is judged on records it never learned from',
        path='core/predictions.py',
        old='    held_model = _model(prediction, encoding, seed).fit(encoding.matrix(train_rows), train_y)',
        new=('    held_model = _model(prediction, encoding, seed).fit(encoding.matrix(train_rows + test_rows),\n'
             '                                                        np.concatenate([train_y, test_y]))'),
        tests=[
            'tests/unit/test_predictions.py::TestLearning::test_noise_is_not_mistaken_for_a_pattern',
        ],
    ),
    Control(
        describes='PREDICT: skill is measured against the naive guess',
        path='core/predictions.py',
        old='    naive = _naive(prediction, train_y, len(test_y))',
        new='    naive = test_y',
        tests=[
            'tests/unit/test_predictions.py::TestLearning::test_a_real_pattern_is_learned_and_beats_the_naive_guess',
        ],
    ),
    Control(
        describes='PREDICT: a group too small to judge shows no score',
        path='core/predictions.py',
        old='        if len(indexes) < MIN_GROUP:',
        new='        if False:',
        tests=[
            'tests/unit/test_predictions.py::TestLearning::test_a_group_too_small_to_judge_shows_no_score',
        ],
    ),
    Control(
        describes='PREDICT: a score too good to be true is said',
        path='core/predictions.py',
        old='    if skill >= SUSPICIOUS_SKILL:',
        new='    if False:',
        tests=[
            'tests/unit/test_predictions.py::TestLearning::test_an_input_carrying_the_answer_is_said_to_be_too_good_to_be_true',
        ],
    ),
    Control(
        describes='PREDICT: blank text is a value of its own',
        path='core/predictions.py',
        old='                    code = codes.get(EMPTY)',
        new='                    code = None',
        tests=[
            'tests/unit/test_predictions.py::TestLearning::test_an_input_carrying_the_answer_is_said_to_be_too_good_to_be_true',
        ],
    ),
    Control(
        describes='PREDICT: a known answer is never overwritten by a guess',
        path='core/predictions.py',
        old='                   if _answer(self.prediction, row.get(self.prediction.target)) is None]',
        new='                   if True]',
        tests=[
            'tests/unit/test_predictions.py::TestPredicting::test_only_records_without_a_known_answer_are_predicted',
        ],
    ),
    Control(
        describes='PREDICT: the schema marks a prediction as predicted',
        path='core/ontology/mediator.py',
        old='                                 else prediction.describe()',
        new='                                 else None',
        tests=[
            'tests/unit/test_predictions.py::test_the_schema_marks_a_prediction_as_predicted',
        ],
    ),
    Control(
        describes="PREDICT: a prediction is computed, never read from a source",
        path="core/ontology/field_types.py",
        old='    return "derived" in field or "enrich" in field or "predict" in field',
        new='    return "derived" in field or "enrich" in field',
        tests=[
            "tests/unit/test_predictions.py::TestAComputedField::test_it_is_computed",
            "tests/unit/test_predictions.py::TestAComputedField::test_the_sync_never_asks_the_source_for_it",
            "tests/unit/test_predictions.py::TestAComputedField::test_meaning_is_never_embedded_from_it",
        ],
    ),
    Control(
        describes='PREDICT: no better than the naive guess is never approved',
        path='core/predictions.py',
        old='    if not isinstance(skill, (int, float)) or skill <= 0:',
        new='    if not isinstance(skill, (int, float)):',
        tests=[
            'tests/unit/test_prediction_proposals.py::TestWhatMayBeApproved::test_no_better_than_guessing_may_not_be',
        ],
    ),
    Control(
        describes='PREDICT: an approval always sees the score by group',
        path='core/predictions.py',
        old='    if not evaluation.get("groups"):',
        new='    if False:',
        tests=[
            'tests/unit/test_prediction_proposals.py::TestWhatMayBeApproved::test_without_a_breakdown_by_group_it_may_not_be',
        ],
    ),
    Control(
        describes='PREDICT: the decide route refuses what may not be approved',
        path='api/routes.py',
        old='    if body.approve and shown["refusal"]:',
        new='    if False:',
        tests=[
            'tests/integration/test_predicted_fields.py::TestReviewing::test_no_better_than_guessing_is_refused_but_may_be_rejected',
        ],
    ),
    Control(
        describes='PREDICT: a proposal is seen and decided only in its own compartment',
        path='api/routes.py',
        old='    if proposal.compartment is not None and proposal.compartment != current_user.security_value:',
        new='    if False:',
        tests=[
            'tests/integration/test_predicted_fields.py::TestReviewing::test_seen_only_in_its_own_compartment',
            'tests/integration/test_predicted_fields.py::TestReviewing::test_another_compartments_proposal_cannot_be_decided',
        ],
    ),
    Control(
        describes='PREDICT: reviewing a prediction needs managing the deployment',
        path='api/routes.py',
        old=('    if not authorize(current_user, roles, "manage:deployment"):\n'
             '        return None\n'
             '    if proposal.compartment'),
        new='    if False:\n        return None\n    if proposal.compartment',
        tests=[
            'tests/integration/test_predicted_fields.py::TestReviewing::test_not_seen_without_managing_the_deployment',
        ],
    ),
    Control(
        describes='PREDICT: reviewing a prediction needs reading every input',
        path='api/routes.py',
        old='    for name in (proposal.field_name, prediction.target, *prediction.inputs,',
        new='    for name in (proposal.field_name, prediction.target,',
        tests=[
            'tests/integration/test_predicted_fields.py::TestReviewing::test_not_seen_without_reading_every_input',
        ],
    ),
    Control(
        describes='PREDICT: one approval per compartment, superseding only its own',
        path='core/prediction_proposals.py',
        old='                    "AND field_name = ? AND declaration_hash = ? AND compartment = ? "',
        new='                    "AND field_name = ? AND declaration_hash = ? AND ? IS NOT NULL "',
        tests=[
            'tests/unit/test_prediction_proposals.py::TestTheStore::test_one_approval_per_compartment_and_a_new_one_supersedes',
        ],
    ),
    Control(
        describes='PREDICT: only an approval for the current question is trained',
        path='core/prediction_proposals.py',
        old=('                    "field_name = ? AND declaration_hash = ? AND status = \'approved\' "\n'
             '                    "ORDER BY decided_at DESC",'),
        new=('                    "field_name = ? AND ? IS NOT NULL AND status = \'approved\' "\n'
             '                    "ORDER BY decided_at DESC",'),
        tests=[
            'tests/unit/test_prediction_proposals.py::TestTheStore::test_only_an_approved_proposal_for_the_current_question_is_trained',
        ],
    ),
    Control(
        describes='PREDICT: a classified field is never a group',
        path='core/ontology/predicted_fields.py',
        old='    if field_classifications(field):\n        raise ValueError(f"{where}: {group_by!r} is classified',
        new='    if False:\n        raise ValueError(f"{where}: {group_by!r} is classified',
        tests=[
            'tests/unit/test_prediction_proposals.py::TestTheGroupField::test_a_field_that_cannot_group_fairly_is_refused',
        ],
    ),
    Control(
        describes="PREDICT: a model fills only its own compartment's records",
        path='core/mirror/gold_arrow.py',
        old='                  if compartment == approval["compartment"]]',
        new='                  if True]',
        tests=[
            'tests/unit/test_predictions.py::TestFillingGold::test_only_an_approved_compartment_is_filled_and_only_where_unknown',
            'tests/unit/test_predictions.py::TestFillingGold::test_a_compartment_learns_only_from_its_own_records',
            'tests/integration/test_predicted_fields.py::TestFilling::test_another_compartment_stays_empty_until_its_own_approval',
        ],
    ),
    Control(
        describes="PREDICT: through a link, the linked record's compartment decides",
        path='core/mirror/gold_arrow.py',
        old='        compartments = [None if row.get(link) is None else by_id.get(str(row[link]))',
        new='        compartments = [None if row.get(link) is None else next(iter(by_id.values()))',
        tests=[
            'tests/unit/test_predictions.py::TestFillingGold::test_through_a_link_the_linked_records_compartment_decides',
        ],
    ),
    Control(
        describes='PREDICT: the carried security value decides first, as reads do',
        path='core/mirror/prediction_fill.py',
        old='    return carried if carried is not None else row.get(security_field)',
        new='    return row.get(security_field)',
        tests=[
            'tests/unit/test_predictions.py::TestFillingGold::test_only_an_approved_compartment_is_filled_and_only_where_unknown',
        ],
    ),
    Control(
        describes='PREDICT: a retrained model must still earn its approval',
        path='core/predictions.py',
        old='    return skill > 0 and skill >= approved_skill - RETRAIN_TOLERANCE',
        new='    return skill > 0',
        tests=[
            'tests/unit/test_predictions.py::TestRetraining::test_a_retrained_model_must_still_earn_its_approval',
            'tests/unit/test_predictions.py::TestFillingGold::test_measuring_worse_than_approved_fills_nothing',
            'tests/integration/test_predicted_fields.py::TestFilling::test_a_model_that_measures_worse_than_approved_fills_nothing',
        ],
    ),
    Control(
        describes='PREDICT: a retrained model no better than guessing fills nothing',
        path='core/predictions.py',
        old='    return skill > 0 and skill >= approved_skill - RETRAIN_TOLERANCE',
        new='    return skill >= approved_skill - RETRAIN_TOLERANCE',
        tests=[
            'tests/unit/test_predictions.py::TestRetraining::test_a_retrained_model_must_still_earn_its_approval',
        ],
    ),
    Control(
        describes='PREDICT: a type with an approved prediction is never streamed',
        path='core/mirror/gold.py',
        old='    if isinstance(silver_rows, pa.RecordBatchReader) and type_def.get(COMPARTMENTS) is not None:',
        new='    if False:',
        tests=[
            'tests/unit/test_gold_streaming.py::test_a_type_with_an_approved_prediction_is_never_streamed',
        ],
    ),
    Control(
        describes='PREDICT: an answer resting on a prediction says so',
        path='core/llm/inferred_values.py',
        old='            if prediction is not None:\n                found[(object_type, field_name)] = InferredField(',
        new='            if False:\n                found[(object_type, field_name)] = InferredField(',
        tests=[
            'tests/unit/test_predictions.py::test_an_answer_resting_on_a_prediction_says_so',
        ],
    ),
    Control(
        describes='PREDICT: approvals ride on the type, so approving one rebuilds gold',
        path='scripts/run_sync.py',
        old=('        type_def = with_approved_predictions(lambda: sync._catalog, config.schema or {},\n'
             '                                             object_type, type_def, predictions)'),
        new='        pass',
        tests=[
            'tests/integration/test_predicted_fields.py::TestFilling::test_empty_until_approved_then_filled_only_where_unknown',
        ],
    ),
    Control(
        describes='PERIOD: a week starts on Monday',
        path='core/periods.py',
        old='        return day - datetime.timedelta(days=day.weekday())',
        new='        return day',
        tests=[
            'tests/unit/test_totals_by_period.py::TestThePeriods::test_each_value_falls_in_the_period_it_starts',
        ],
    ),
    Control(
        describes='PERIOD: an instant falls in its UTC day',
        path='core/periods.py',
        old='            value = value.astimezone(datetime.UTC)',
        new='            pass',
        tests=[
            'tests/unit/test_totals_by_period.py::TestThePeriods::test_each_value_falls_in_the_period_it_starts',
        ],
    ),
    Control(
        describes='PERIOD: an empty period is zero for a count or a sum',
        path='core/periods.py',
        old='    return {start: totals.get(start, 0) for start in periods_between(starts[0], starts[-1], period)}',
        new='    return dict(totals)',
        tests=[
            'tests/unit/test_totals_by_period.py::TestThePeriods::test_an_empty_period_is_zero_for_a_count_or_a_sum_and_absent_otherwise',
            'tests/unit/test_totals_by_period.py::TestThroughTheMediator::test_counted_by_week_with_the_empty_week_as_zero',
            'tests/integration/test_totals_by_period_api.py::test_summed_by_week',
        ],
    ),
    Control(
        describes='PERIOD: an average of nothing is not zero',
        path='core/periods.py',
        old='    if aggregate not in ZERO_WHEN_EMPTY:',
        new='    if False:',
        tests=[
            'tests/unit/test_totals_by_period.py::TestThePeriods::test_an_empty_period_is_zero_for_a_count_or_a_sum_and_absent_otherwise',
        ],
    ),
    Control(
        describes='PERIOD: too many periods are refused',
        path='core/periods.py',
        old='        if len(out) > MAX_PERIODS:',
        new='        if False:',
        tests=[
            'tests/unit/test_totals_by_period.py::TestThePeriods::test_too_many_periods_is_refused_with_the_longer_one_to_ask_for',
        ],
    ),
    Control(
        describes='PERIOD: only a date is grouped by period',
        path='core/ontology/mediator.py',
        old='            if group_by is None or declared not in TEMPORAL:',
        new='            if group_by is None:',
        tests=[
            'tests/unit/test_totals_by_period.py::TestThroughTheMediator::test_a_period_needs_a_date_and_a_known_period',
            'tests/integration/test_totals_by_period_api.py::test_a_period_on_text_is_a_400_that_says_why',
        ],
    ),
    Control(
        describes='FORECAST: the period still running is never fitted',
        path='core/forecasts.py',
        old='    every = periods_between(starts[0], current, period)[:-1]',
        new='    every = periods_between(starts[0], current, period)',
        tests=[
            'tests/unit/test_forecasts.py::TestTheSeries::test_carried_on_to_today_with_zeros_and_the_running_period_apart',
            'tests/integration/test_forecast_api.py::test_weekly_counts_are_forecast_and_tested',
        ],
    ),
    Control(
        describes='FORECAST: a series is carried on to today with zeros',
        path='core/forecasts.py',
        old='    every = periods_between(starts[0], current, period)[:-1]',
        new='    every = periods_between(starts[0], starts[-1], period)[:-1]',
        tests=[
            'tests/unit/test_forecasts.py::TestTheSeries::test_carried_on_to_today_with_zeros_and_the_running_period_apart',
        ],
    ),
    Control(
        describes='FORECAST: one no better than the naive forecast is not drawn',
        path='core/forecasts.py',
        old='    if typical >= naive - tolerance and naive > tolerance:',
        new='    if False:',
        tests=[
            'tests/unit/test_forecasts.py::TestForecasting::test_a_forecast_no_better_than_the_naive_one_is_not_drawn',
        ],
    ),
    Control(
        describes='FORECAST: a perfectly steady series is still drawn',
        path='core/forecasts.py',
        old='    if typical >= naive - tolerance and naive > tolerance:',
        new='    if typical >= naive - tolerance:',
        tests=[
            'tests/unit/test_forecasts.py::TestForecasting::test_a_steady_series_is_drawn_though_the_naive_one_is_as_good',
        ],
    ),
    Control(
        describes='FORECAST: a count never goes below zero',
        path='core/forecasts.py',
        old='            mean, low, high = max(mean, 0.0), max(low, 0.0), max(high, 0.0)',
        new='            pass',
        tests=[
            'tests/unit/test_forecasts.py::TestForecasting::test_a_count_never_goes_below_zero',
        ],
    ),
    Control(
        describes='FORECAST: a season needs two full ones in every test',
        path='core/forecasts.py',
        old='    return season if count - ORIGINS * HORIZON[period] >= 2 * season else None',
        new='    return season',
        tests=[
            'tests/unit/test_forecasts.py::TestForecasting::test_no_season_without_two_full_ones',
            'tests/unit/test_forecasts.py::TestForecasting::test_a_season_only_when_every_test_sees_two_full_ones',
        ],
    ),
    Control(
        describes='FORECAST: the form is the one AICc chooses',
        path='core/forecasts.py',
        old='            if math.isfinite(aicc) and aicc < best_aicc:',
        new='            if best is None:',
        tests=[
            'tests/integration/test_forecast_api.py::test_weekly_counts_are_forecast_and_tested',
        ],
    ),
    Control(
        describes='FORECAST: too little history is refused',
        path='core/forecasts.py',
        old='    if n < MIN_PERIODS:',
        new='    if False:',
        tests=[
            'tests/unit/test_forecasts.py::TestForecasting::test_too_little_history_is_refused_and_said',
        ],
    ),
    Control(
        describes='FORECAST: a cut-off set is not forecast',
        path='api/routes.py',
        old='    if search_outcome.scan_truncated:\n        # A SHORT TOTAL IS NOT A TREND',
        new='    if False:\n        # A SHORT TOTAL IS NOT A TREND',
        tests=[
            'tests/integration/test_forecast_api.py::test_a_cut_off_set_is_not_forecast',
        ],
    ),
    Control(
        describes='FORECAST: only a count or a sum',
        path='api/routes.py',
        old='    if body.aggregate not in ("count", "sum"):',
        new='    if False:',
        tests=[
            'tests/integration/test_forecast_api.py::test_only_a_count_or_a_sum',
        ],
    ),
    Control(
        describes='PROJECTED: it follows the forecast line, not the top of its range',
        path='core/projected_condition.py',
        old='                     if point["value"] > trigger.projected_above), None)',
        new='                     if point["high"] > trigger.projected_above), None)',
        tests=[
            'tests/unit/test_projected_condition.py::TestWhatItReads::test_the_forecast_line_not_the_top_of_its_range',
        ],
    ),
    Control(
        describes='PROJECTED: told once on becoming projected, not while it stays so',
        path='core/projected_condition.py',
        old='        if current and not previous and not changed:',
        new='        if current and not changed:',
        tests=[
            'tests/unit/test_projected_condition.py::TestWhenItIsTold::test_first_it_is_watching_then_told_once_on_becoming_projected',
        ],
    ),
    Control(
        describes='PROJECTED: a changed configuration is a new baseline',
        path='core/projected_condition.py',
        old=('        changed = previous_digest is not None and config_digest is not None \\\n'
             '            and previous_digest != config_digest'),
        new='        changed = False',
        tests=[
            'tests/unit/test_projected_condition.py::TestWhenItIsTold::test_a_changed_configuration_is_a_new_baseline',
        ],
    ),
    Control(
        describes='PROJECTED: each recipient is projected from their own totals',
        path='core/projected_condition.py',
        old='            projection = projection_for(mediator, view, trigger, person, today)',
        new='            projection = projection_for(mediator, view, trigger, owner, today)',
        tests=[
            'tests/unit/test_projected_condition.py::TestAsEachPerson::test_each_recipient_is_projected_from_their_own_totals',
        ],
    ),
    Control(
        describes='PROJECTED: a cut-off set is not trusted',
        path='core/projected_condition.py',
        old='    if outcome.scan_truncated:\n        return {"state": "untrusted",',
        new='    if False:\n        return {"state": "untrusted",',
        tests=[
            'tests/unit/test_projected_condition.py::TestWhatItReads::test_a_cut_off_set_is_not_trusted',
        ],
    ),
    Control(
        describes='PROJECTED: it stands alone',
        path='core/projected_condition.py',
        old='    if named:\n        return (f"A projected condition stands alone',
        new='    if False:\n        return (f"A projected condition stands alone',
        tests=[
            'tests/unit/test_projected_condition.py::TestTheDeclaration::test_one_that_could_not_be_checked_is_refused',
            'tests/integration/test_forecast_api.py::TestAProjectedTrigger::test_one_that_could_not_be_checked_is_refused',
        ],
    ),
    Control(
        describes='PROJECTED: only a date field',
        path='core/projected_condition.py',
        old='    if declared.get("data_type") not in TEMPORAL:',
        new='    if False:',
        tests=[
            'tests/unit/test_projected_condition.py::TestTheDeclaration::test_one_that_could_not_be_checked_is_refused',
            'tests/integration/test_forecast_api.py::TestAProjectedTrigger::test_one_that_could_not_be_checked_is_refused',
        ],
    ),
    Control(
        describes='PROJECTED: a projected trigger is evaluated as a projection',
        path='core/count_condition.py',
        old='        if is_projected(trigger):',
        new='        if False:',
        tests=[
            'tests/integration/test_forecast_api.py::TestAProjectedTrigger::test_made_checked_at_once_and_listed',
        ],
    ),
    Control(
        describes='UNUSUAL: a number is judged against records of its own kind',
        path='core/unusual.py',
        old='            kind = tuple((name, row.get(name)) for name in within)',
        new='            kind = ()',
        tests=[
            'tests/unit/test_unusual.py::TestFinding::test_a_value_ordinary_for_the_table_but_wrong_for_its_kind_is_found',
        ],
    ),
    Control(
        describes='UNUSUAL: the published cut-off, not a looser one',
        path='core/unusual.py',
        old='                if abs(score) > THRESHOLD:',
        new='                if abs(score) > 1.0:',
        tests=[
            'tests/unit/test_unusual.py::TestFinding::test_clean_records_raise_nothing',
        ],
    ),
    Control(
        describes='UNUSUAL: a kind too small to judge is not judged',
        path='core/unusual.py',
        old='            if len(members) < MIN_GROUP:',
        new='            if False:',
        tests=[
            'tests/unit/test_unusual.py::TestFinding::test_a_kind_too_small_to_judge_is_not_judged',
        ],
    ),
    Control(
        describes='UNUSUAL: at most a capped number, the furthest first',
        path='core/unusual.py',
        old='    return flags[:MAX_FLAGS], len(flags)',
        new='    return flags, len(flags)',
        tests=[
            'tests/unit/test_unusual.py::TestFinding::test_the_furthest_first_and_at_most_a_capped_number',
        ],
    ),
    Control(
        describes='UNUSUAL: each compartment is judged on its own',
        path='core/mirror/unusual_scan.py',
        old='        by_compartment.setdefault(compartment, []).append(row)',
        new='        by_compartment.setdefault(None, []).append(row)',
        tests=[
            'tests/integration/test_unusual_records.py::test_found_at_the_sync_and_judged_within_each_compartment',
        ],
    ),
    Control(
        describes='UNUSUAL: a classified field is never checked',
        path='core/ontology/unusual_checks.py',
        old='    labels = field_classifications(field)\n    if labels:',
        new='    labels = field_classifications(field)\n    if False:',
        tests=[
            'tests/unit/test_unusual.py::TestTheDeclaration::test_one_that_could_not_be_made_is_refused',
        ],
    ),
    Control(
        describes='UNUSUAL: only a number may be unusual',
        path='core/ontology/unusual_checks.py',
        old='            if (fields[name].get("data_type") or "string") not in NUMERIC:',
        new='            if False:',
        tests=[
            'tests/unit/test_unusual.py::TestTheDeclaration::test_one_that_could_not_be_made_is_refused',
        ],
    ),
    Control(
        describes="UNUSUAL: a type's flags are replaced whole",
        path='core/unusual_flags.py',
        old='            conn.execute("DELETE FROM unusual_flags WHERE object_type = ?", (object_type,))\n',
        new='',
        tests=[
            'tests/unit/test_unusual.py::TestTheStore::test_no_longer_unusual_is_no_longer_flagged',
        ],
    ),
    Control(
        describes="UNUSUAL: 'expected' holds for the value judged, not a changed one",
        path='core/unusual_flags.py',
        old='               "d.record_id = f.record_id AND d.field = f.field AND d.value = f.value")',
        new='               "d.record_id = f.record_id AND d.field = f.field")',
        tests=[
            'tests/unit/test_unusual.py::TestTheStore::test_replaced_whole_and_expected_is_remembered_by_the_value',
        ],
    ),
    Control(
        describes='UNUSUAL: looked for only when gold changed',
        path='scripts/run_sync.py',
        old='            print(f"unchanged gold.{object_type}: built from the same inputs as its "',
        new=('            scan_unusual(sync._catalog, config.schema or {}, object_type, unusual)\n'
             '            print(f"unchanged gold.{object_type}: built from the same inputs as its "'),
        tests=[
            'tests/integration/test_unusual_records.py::test_unchanged_gold_keeps_its_flags_and_is_not_scanned_again',
        ],
    ),
    Control(
        describes='UNUSUAL: the marker needs read on every field it was compared within',
        path='api/routes.py',
        old='        authorize(current_user, roles, f"read:{flag.object_type}.{name}") for name in names)',
        new='        authorize(current_user, roles, f"read:{flag.object_type}.{name}") for name in names[:1])',
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheMarker::'
             'test_not_without_reading_every_field_it_was_compared_within'),
        ],
    ),
    Control(
        describes='UNUSUAL: a flag is shown only in the compartment it was judged in',
        path='api/routes.py',
        old='    if flag.compartment is not None and flag.compartment != current_user.security_value:',
        new='    if False:',
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheMarker::'
             'test_a_flag_from_another_compartment_is_not_shown_on_a_readable_record'),
        ],
    ),
    Control(
        describes='UNUSUAL: a value marked expected is not marked for anyone',
        path='api/routes.py',
        old='        if flag.decision == "expected" or not _may_see_flag(generation, current_user, flag):',
        new='        if not _may_see_flag(generation, current_user, flag):',
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheMarker::'
             'test_expected_clears_it_for_everyone_until_the_value_changes'),
        ],
    ),
    Control(
        describes="UNUSUAL: the record's own read check answers for it",
        path='api/routes.py',
        old=('    return {"unusual": {record_id: flags for record_id, flags in found.items()\n'
             '                        if _may_read_object('),
        new=('    return {"unusual": {record_id: flags for record_id, flags in found.items()\n'
             '                        if True or _may_read_object('),
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheMarker::'
             'test_a_record_the_reader_cannot_see_is_not_answered'),
        ],
    ),
    Control(
        describes='UNUSUAL: a flag for a number no longer declared is not shown',
        path='api/routes.py',
        old='    if declared is None or flag.field not in declared[0]:',
        new='    if declared is None:',
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheMarker::'
             'test_a_flag_the_declaration_no_longer_makes_is_not_shown'),
        ],
    ),
    Control(
        describes='UNUSUAL: a flag compared within other fields than declared is not shown',
        path='api/routes.py',
        old='    if [field for field, _ in flag.kind] != list(declared[1]):',
        new='    if False:',
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheMarker::'
             'test_a_flag_the_declaration_no_longer_makes_is_not_shown'),
        ],
    ),
    Control(
        describes='UNUSUAL: deciding needs write on the type',
        path='api/routes.py',
        old='            and authorize(current_user, generation.config.roles, f"write:{flag.object_type}"))',
        new='            )',
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheQueue::'
             'test_not_without_write_on_the_type'),
        ],
    ),
    Control(
        describes='UNUSUAL: a reviewer needs everything a reader of the flag needs',
        path='api/routes.py',
        old=('    return (_may_see_flag(generation, current_user, flag)\n'
             '            and authorize('),
        new=('    return (True\n'
             '            and authorize('),
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheQueue::'
             'test_not_without_read_on_every_field_compared_within'),
        ],
    ),
    Control(
        describes='UNUSUAL: the queue lists only records the reviewer may read',
        path='api/routes.py',
        old=('            if _may_review_flag(generation, current_user, flag)\n'
             '            and _may_read_object('),
        new=('            if _may_review_flag(generation, current_user, flag)\n'
             '            and True or _may_read_object('),
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheQueue::'
             'test_a_record_the_reviewer_cannot_see_is_neither_listed_nor_decided'),
        ],
    ),
    Control(
        describes='UNUSUAL: a decision only on a record the reviewer may read',
        path='api/routes.py',
        old=('            or not _may_read_object(generation.mediator, current_user, flag.object_type,\n'
             '                                    flag.record_id)):'),
        new='            or False):',
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheQueue::'
             'test_a_record_the_reviewer_cannot_see_is_neither_listed_nor_decided'),
        ],
    ),
    Control(
        describes='UNUSUAL: the Inbox counts only what waits on a decision',
        path='api/routes.py',
        old='    unusual = sum(1 for flag in _reviewable_flags(request, current_user) if flag.decision is None)',
        new='    unusual = sum(1 for flag in _reviewable_flags(request, current_user))',
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheQueue::'
             'test_worth_a_look_keeps_the_marker_and_leaves_the_count'),
        ],
    ),
    Control(
        describes='UNUSUAL: every decision is audited',
        path='api/routes.py',
        old=('    generation.mediator.audit_log.log_unusual_decision(\n'),
        new=('    (lambda *a: None)(\n'),
        tests=[
            ('tests/integration/test_unusual_records.py::TestTheQueue::'
             'test_expected_clears_the_marker_for_everyone_and_is_audited'),
        ],
    ),
    Control(
        describes="TIMING: Ollama's reading time is its prompt evaluation",
        path='adapters/ollama_adapter.py',
        old='                      reading_seconds=_seconds(body.get("prompt_eval_duration")),',
        new='                      reading_seconds=None,',
        tests=[
            ('tests/unit/test_where_a_questions_time_goes.py::'
             'TestOllama::test_reading_writing_loading_and_reuse_from_its_nanoseconds'),
        ],
    ),
    Control(
        describes="TIMING: Ollama's reuse is its cached prompt count",
        path='adapters/ollama_adapter.py',
        old='                      cached_input_tokens=body.get("prompt_eval_cached_count"),',
        new='                      cached_input_tokens=None,',
        tests=[
            ('tests/unit/test_where_a_questions_time_goes.py::'
             'TestOllama::test_reading_writing_loading_and_reuse_from_its_nanoseconds'),
        ],
    ),
    Control(
        describes="TIMING: llama-server's own timings are read",
        path='adapters/vllm_adapter.py',
        old='                      writing_seconds=_milliseconds(timings.get("predicted_ms")),',
        new='                      writing_seconds=None,',
        tests=[
            'tests/unit/test_where_a_questions_time_goes.py::TestOpenAIStyle::test_llama_servers_own_timings',
        ],
    ),
    Control(
        describes='TIMING: a step call is recorded as a step',
        path='core/llm/agent_step_prompt.py',
        old='                usage=usage.for_part("step") if usage is not None else None, cancel=cancel,',
        new='                usage=usage, cancel=cancel,',
        tests=[
            ('tests/unit/test_where_a_questions_time_goes.py::'
             'TestEachCallSaysWhatItIsFor::test_a_step_a_plan_and_an_answer'),
        ],
    ),
    Control(
        describes='TIMING: the answer call is recorded as the answer',
        path='core/llm/synthesis_prompt.py',
        old='                usage=usage.for_part("answer") if usage is not None else None,',
        new='                usage=usage,',
        tests=[
            ('tests/unit/test_where_a_questions_time_goes.py::'
             'TestEachCallSaysWhatItIsFor::test_a_step_a_plan_and_an_answer'),
        ],
    ),
    Control(
        describes="TIMING: a part's calls are recorded in the whole",
        path='core/request_context.py',
        old=('        root = self._parent or self\n'
             '        return TokenUsage(_parent=root, _part=part)'),
        new='        return TokenUsage(_part=part)',
        tests=[
            'tests/unit/test_where_a_questions_time_goes.py::TestTheTally::test_a_part_records_into_the_whole',
        ],
    ),
    Control(
        describes='TIMING: the bench writes and times the answer too',
        path='scripts/llm_bench.py',
        old='                            if answer else None)',
        new='                            if False else None)',
        tests=[
            'tests/unit/test_llm_bench.py::test_a_trial_is_a_whole_question_answer_included',
        ],
    ),
    Control(
        describes='TIMING: another model is set on the adapter beneath every wrapper',
        path='scripts/llm_bench.py',
        old=('    while hasattr(adapter, "_wrapped"):\n'
             '        adapter = adapter._wrapped\n'
             '    if not hasattr(adapter, "model"):'),
        new=('    if hasattr(adapter, "_wrapped"):\n'
             '        adapter = adapter._wrapped\n'
             '    if not hasattr(adapter, "model"):'),
        tests=[
            'tests/unit/test_llm_bench.py::test_another_model_through_every_wrapper',
        ],
    ),
    Control(
        describes='TIMING: reuse is measured only over calls that reported it',
        path='scripts/compare_models.py',
        old='            if record.input_tokens and record.cached_input_tokens is not None:',
        new='            if record.input_tokens:',
        tests=[
            'tests/unit/test_compare_models.py::test_each_model_is_run_and_the_faster_one_shows_it',
        ],
    ),
    Control(
        describes='PROGRESS: nothing is shown once the asker has changed',
        path='api/routes.py',
        old=('    def steps(self, gathered: list[dict]) -> None:\n'
             '        """From the loop\'s thread, between hops."""\n'
             '        if self._still_them is None or not self._still_them():\n'
             '            return'),
        new=('    def steps(self, gathered: list[dict]) -> None:\n'
             '        """From the loop\'s thread, between hops."""\n'
             '        if self._still_them is None:\n'
             '            return'),
        tests=[
            ('tests/integration/test_a_question_shows_its_steps.py::'
             'test_nothing_is_shown_once_the_asker_has_changed'),
        ],
    ),
    Control(
        describes="PROGRESS: a step is shown in the answer's own read-back, refusals stripped",
        path='api/routes.py',
        old='        return read_back(AgentLoop.filter_real_data(gathered), self._schema)',
        new='        return read_back(gathered, self._schema)',
        tests=[
            ('tests/integration/test_a_question_shows_its_steps.py::'
             'test_a_refused_read_is_not_shown'),
        ],
    ),
    Control(
        describes='PROGRESS: only a client asking for the stream gets it',
        path='api/routes.py',
        old='    if "application/x-ndjson" in request.headers.get("accept", ""):',
        new='    if True:',
        tests=[
            ('tests/integration/test_a_question_shows_its_steps.py::'
             'test_a_plain_request_is_answered_exactly_as_before'),
        ],
    ),
    Control(
        describes="PROGRESS: the stream ends with the question's own status and body",
        path='api/routes.py',
        old='            return {"type": "done", "status": e.status_code, "body": {"detail": e.detail}}',
        new='            return {"type": "done", "status": 200, "body": {"detail": e.detail}}',
        tests=[
            ('tests/integration/test_a_question_shows_its_steps.py::'
             'test_nothing_is_shown_once_the_asker_has_changed'),
        ],
    ),
    Control(
        describes='PROGRESS: the loop hands on a copy of what it gathered',
        path='core/agent/agentic_loop.py',
        old='                    progress(list(gathered))',
        new='                    progress(gathered)',
        tests=[
            ('tests/unit/test_the_loop_reports_its_progress.py::'
             'test_what_it_is_given_is_a_copy'),
        ],
    ),
    Control(
        describes='PROGRESS: a failing progress hook never stops the question',
        path='core/agent/agentic_loop.py',
        old='                except Exception:  # noqa: BLE001 - showing progress must never stop a question',
        new='                except ZeroDivisionError:',
        tests=[
            ('tests/unit/test_the_loop_reports_its_progress.py::'
             'test_a_failing_hook_does_not_stop_the_question'),
        ],
    ),
    Control(
        describes='PROGRESS: a person leaving ends the question through its own cancel events',
        path='api/routes.py',
        old=('                progress.left()\n'),
        new=('                task.cancel()\n'),
        tests=[
            ('tests/integration/test_a_question_shows_its_steps.py::'
             'test_leaving_partway_ends_the_question_its_own_way'),
        ],
    ),
    Control(
        describes='PROGRESS: an event watched after leaving is set at once',
        path='api/routes.py',
        old=('        self._cancels.append(cancel)\n'
             '        if self._left:\n'
             '            cancel.set()'),
        new='        self._cancels.append(cancel)',
        tests=[
            ('tests/integration/test_a_question_shows_its_steps.py::'
             'test_an_event_watched_after_leaving_is_set_at_once'),
        ],
    ),
    Control(
        describes='ANSWER: Ollama caps an answer where a limit is set',
        path='adapters/ollama_adapter.py',
        old='        if not json_mode and "num_predict" not in options and self.prose_num_predict:',
        new='        if False:',
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'TestOllama::test_an_answer_is_capped_where_a_limit_is_set'),
        ],
    ),
    Control(
        describes='ANSWER: Ollama reports stopping at the limit',
        path='adapters/ollama_adapter.py',
        old='                      stopped_at_limit=(body.get("done_reason") == "length"',
        new='                      stopped_at_limit=(False',
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'TestOllama::test_stopping_at_the_limit_is_reported'),
        ],
    ),
    Control(
        describes='ANSWER: an OpenAI-style answer is given max_tokens',
        path='adapters/vllm_adapter.py',
        old=('        if not json_mode and self.prose_max_tokens:\n'
             '            payload["max_tokens"] = self.prose_max_tokens'),
        new=('        if False:\n'
             '            payload["max_tokens"] = self.prose_max_tokens'),
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'TestOpenAIStyle::test_max_tokens_and_finish_reason'),
        ],
    ),
    Control(
        describes="ANSWER: only the answer's client is given the limit",
        path='core/deployment_loader.py',
        old='            prose_max_tokens=config.agent_features.answer_max_tokens),',
        new='            prose_max_tokens=None),',
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'test_only_the_answers_client_is_given_the_limit'),
        ],
    ),
    Control(
        describes='ANSWER: a cut answer says it was cut',
        path='core/llm/synthesis_prompt.py',
        old='    cut = CUT_SHORT_NOTE if written is not None and written.stopped_at_limit else ""',
        new='    cut = ""',
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'TestTheAnswer::test_a_cut_answer_says_so'),
        ],
    ),
    Control(
        describes='ANSWER: brief is asked for only when switched on',
        path='core/llm/synthesis_prompt.py',
        old=('    if brief:\n'
             '        system_prompt += _BRIEF_NOTE'),
        new='    system_prompt += _BRIEF_NOTE',
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'TestTheAnswer::test_brief_is_asked_for_only_when_switched_on'),
        ],
    ),
    Control(
        describes='ANSWER: a citation tag is not taken for a stated value',
        path='core/agent/evaluation.py',
        old='    said = _CITATION.sub("", answer).lower()',
        new='    said = answer.lower()',
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'TestTheAnswerIsGraded::test_a_citation_tag_is_not_a_value'),
        ],
    ),
    Control(
        describes='ANSWER: brief stays off if an answer stops stating its facts',
        path='scripts/feature_bench.py',
        old=('    if lost:\n'
             '        return "OFF", f"answers stopped stating their facts'),
        new=('    if False:\n'
             '        return "OFF", f"answers stopped stating their facts'),
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'TestTheBriefVerdict::test_off_when_an_answer_stops_stating_its_facts'),
        ],
    ),
    Control(
        describes="ANSWER: the bench's answer is written as the switch says",
        path='scripts/llm_bench.py',
        old='        brief=generation.loop.features.brief_answers)',
        new='        brief=False)',
        tests=[
            ('tests/unit/test_feature_bench.py::'
             'test_the_whole_session_runs_and_decides'),
        ],
    ),
    Control(
        describes='ANSWER: a limit that guards nothing is refused',
        path='core/llm/agent_features.py',
        old='                              or not MIN_ANSWER_TOKENS <= limit <= MAX_ANSWER_TOKENS):',
        new='                              or False):',
        tests=[
            ('tests/unit/test_shorter_answers.py::'
             'TestTheSettings::test_a_limit_that_guards_nothing_is_refused'),
        ],
    ),
    Control(
        describes="SOURCES: a column's time zone is part of its reported type",
        path='adapters/sqlalchemy_adapter.py',
        old='    if getattr(column_type, "timezone", False) and "TIME ZONE" not in text.upper():',
        new='    if False:',
        tests=[
            ('tests/unit/test_source_type_drift.py::'
             'TestCapturingWhatTheSourceSaid::test_postgresql_can'),
        ],
    ),
    Control(
        describes='SOURCES: corrected source types are kept under their own key',
        path='core/mirror/iceberg_sync.py',
        old='SOURCE_TYPES_PROPERTY = "elysium.source_column_types.v2"',
        new='SOURCE_TYPES_PROPERTY = "elysium.source_column_types"',
        tests=[
            ('tests/unit/test_source_type_drift.py::'
             'test_the_corrected_types_have_their_own_key'),
        ],
    ),
    Control(
        describes='SOURCES: MariaDB has a query time limit',
        path='adapters/sqlalchemy_adapter.py',
        old='            cursor.execute(self._time_limit_sql(self._timeout_seconds))',
        new='            cursor.execute("SELECT 1")',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'TestMariaDB::test_a_query_past_its_time_limit_is_stopped'),
        ],
    ),
    Control(
        describes='SOURCES: a MariaDB session refuses to write',
        path='adapters/sqlalchemy_adapter.py',
        old='            cursor.execute("SET SESSION TRANSACTION READ ONLY")',
        new='            cursor.execute("SELECT 1")',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'TestMariaDB::test_the_session_refuses_to_write'),
        ],
    ),
    Control(
        describes='SOURCES: a PostgreSQL session refuses to write',
        path='adapters/sqlalchemy_adapter.py',
        old='                   f"-c default_transaction_read_only=on"),',
        new='                   f""),',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'TestPostgreSQL::test_the_session_refuses_to_write'),
        ],
    ),
    Control(
        describes='SOURCES: MySQL-family connections are recycled before the server drops them',
        path='adapters/sqlalchemy_adapter.py',
        old='            **({"pool_recycle": MYSQL_POOL_RECYCLE_SECONDS} if self._mysql_family else {}),',
        new='            **({}),',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'TestMariaDB::test_pooled_connections_are_recycled_before_the_server_drops_them'),
        ],
    ),
    Control(
        describes='SOURCES: an absorbed column travels on the sync result',
        path='core/mirror/iceberg_sync.py',
        old='            absorbed_drift = verdict.detail',
        new='            absorbed_drift = None',
        tests=[
            ('tests/unit/test_a_source_changes_and_what_a_reader_sees.py::'
             'TestAnAbsorbedColumnIsRecorded::test_the_result_carries_the_explanation'),
        ],
    ),
    Control(
        describes='SOURCES: an absorbed column is recorded on the attempt',
        path='scripts/run_sync.py',
        old='                               getattr(result, "absorbed_drift", None),',
        new='                               None,',
        tests=[
            ('tests/unit/test_a_source_changes_and_what_a_reader_sees.py::'
             'TestAnAbsorbedColumnIsRecorded::test_the_attempt_records_it_beside_its_outcome'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: the declaration becomes its block at load',
        path='core/ontology/unrestricted.py',
        old='            type_def["security"] = {DECLARED: True}',
        new='            pass',
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'TestDeclaringIt::test_it_validates'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: nothing may sit beside it',
        path='core/ontology/object_type_validation.py',
        old='        if dict(security) != {"unrestricted": True}:',
        new='        if False:',
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'TestDeclaringIt::test_nothing_may_sit_beside_it'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: a security chain may not end at an unrestricted type',
        path='core/ontology/object_type_validation.py',
        old='        if origin is not None:',
        new='        if False:',
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'TestDeclaringIt::test_a_chain_may_not_end_at_it'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: its label is the lowest, never None',
        path='core/ontology/mediator.py',
        old=('        if is_unrestricted(type_schema):\n'
             '            return UNRESTRICTED'),
        new=('        if False:\n'
             '            return UNRESTRICTED'),
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'TestReading::test_its_label_is_the_lowest_never_none'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: a person with no compartment still sees it',
        path='core/intermediate_layer/access_control.py',
        old='    unrestricted = bool(has_no_row_check and has_no_row_check(object_type))',
        new='    unrestricted = False',
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'TestReading::test_even_someone_with_no_compartment_at_all'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: its values may be written anywhere',
        path='core/ontology/write_mediator.py',
        old=('        if read_label is UNRESTRICTED:\n'
             '            continue'),
        new=('        if False:\n'
             '            continue'),
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'TestWritingIsNotAWayOut::test_its_values_may_go_anywhere'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: a new record of it is labelled, so writing restricted values into it is refused',
        path='core/ontology/write_mediator.py',
        old=('        if is_unrestricted(declared):\n'
             '            return UNRESTRICTED'),
        new=('        if False:\n'
             '            return UNRESTRICTED'),
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'TestWritingIsNotAWayOut::test_a_new_record_of_it_is_labelled'),
        ],
    ),
    Control(
        describes="UNRESTRICTED: writing to it is within everyone's reach",
        path='core/ontology/write_mediator.py',
        old='            if current is None or current is UNRESTRICTED or current == proposer.security_value:',
        new='            if current is None or current == proposer.security_value:',
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'TestWritingIsNotAWayOut::test_writing_to_it_is_within_everyones_reach'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: review stores record it as shared',
        path='core/ontology/unrestricted.py',
        old='    return None if value is UNRESTRICTED else value',
        new='    return value',
        tests=[
            ('tests/unit/test_unrestricted_types.py::'
             'test_review_stores_record_it_as_shared'),
        ],
    ),
    Control(
        describes='UNRESTRICTED: who-can-see says so',
        path='core/ontology/who_can_see.py',
        old='        if is_unrestricted(schema.get(current)):',
        new='        if False:',
        tests=[
            ('tests/integration/test_unrestricted_end_to_end.py::'
             'test_who_can_see_says_unrestricted'),
        ],
    ),
    Control(
        describes='SOURCES: an account that bypasses row-level security is not warned',
        path='adapters/sqlalchemy_adapter.py',
        old='        if row is None or not row["relrowsecurity"] or row["exempt"]:',
        new='        if row is None or not row["relrowsecurity"]:',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'TestRowsHiddenFromTheSync::test_an_account_that_bypasses_it_is_not_warned'),
        ],
    ),
    Control(
        describes="SOURCES: a table's owner is exempt from row-level security unless forced",
        path='adapters/sqlalchemy_adapter.py',
        old='        if row["owns"] and not row["relforcerowsecurity"]:',
        new='        if False:',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'TestRowsHiddenFromTheSync::test_the_owner_is_exempt_unless_forced'),
        ],
    ),
    Control(
        describes='SOURCES: rows hidden from the sync travel on its result',
        path='core/mirror/iceberg_sync.py',
        old='        hidden_rows = _rows_hidden(adapter, table_name)',
        new='        hidden_rows = None',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'test_a_sync_carries_the_warning_onto_its_result'),
        ],
    ),
    Control(
        describes='SOURCES: rows hidden from the sync are recorded on the attempt',
        path='scripts/run_sync.py',
        old='                               getattr(result, "hidden_rows", None),',
        new='                               None,',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'test_a_sync_carries_the_warning_onto_its_result'),
        ],
    ),
    Control(
        describes='SOURCES: a refused empty read names row-level security as the likely cause',
        path='core/mirror/iceberg_sync.py',
        old='self._refuse_suspected_partial_read(silo_name, table_name, row_count, hidden_rows)',
        new='self._refuse_suspected_partial_read(silo_name, table_name, row_count, None)',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'test_a_refused_empty_read_names_the_likely_cause_first'),
        ],
    ),
    Control(
        describes='CSV: a latest-shaped table reads only the newest file',
        path='adapters/csv_folder_adapter.py',
        old='        return files[-1:] if self._spec(table_name)["shape"] == "latest" else files',
        new='        return files',
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestTheTwoShapes::test_latest_reads_only_the_newest_file'),
        ],
    ),
    Control(
        describes='CSV: in a combined table the newer file wins',
        path='adapters/csv_folder_adapter.py',
        old='            newest.update(this_file)',
        new='            newest.update({k: v for k, v in this_file.items() if k not in newest})',
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestTheTwoShapes::test_combined_reads_them_all_and_the_newer_file_wins'),
        ],
    ),
    Control(
        describes='CSV: files are ordered by when they were written',
        path='adapters/csv_folder_adapter.py',
        old='            chosen.append((entry.stat().st_mtime_ns, name, Path(entry.path)))',
        new='            chosen.append((0, name, Path(entry.path)))',
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestTheTwoShapes::test_newest_is_by_when_it_was_written_not_its_name'),
        ],
    ),
    Control(
        describes="CSV: a duplicate within one file reaches the sync's guard",
        path='adapters/csv_folder_adapter.py',
        old='                    this_file.setdefault(key, []).append(row)',
        new='                    this_file[key] = [row]',
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestTheTwoShapes::test_a_duplicate_within_one_file_is_left_for_the_syncs_guard'),
        ],
    ),
    Control(
        describes='CSV: a broken line stops the table, naming the file and line',
        path='adapters/csv_folder_adapter.py',
        old='                if len(record) != len(header):',
        new='                if False:',
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestAFileThatCannotBeRead::test_a_broken_line_stops_the_table_naming_the_file_and_line'),
        ],
    ),
    Control(
        describes='CSV: half-written and lock files are not read',
        path='adapters/csv_folder_adapter.py',
        old='                    or name.lower().endswith(TEMPORARY)',
        new='                    or False',
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestWhatIsNotRead::test_half_written_hidden_and_lock_files'),
        ],
    ),
    Control(
        describes="CSV: one listing of a table's files per sync",
        path='adapters/csv_folder_adapter.py',
        old=('        if self._pinned is not None:\n'
             '            self._pinned[table_name] = files'),
        new=('        if False:\n'
             '            self._pinned[table_name] = files'),
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestWhatIsNotRead::test_a_file_arriving_mid_sync_waits_for_the_next'),
        ],
    ),
    Control(
        describes="CSV: Excel's sep= line names the delimiter",
        path='adapters/csv_folder_adapter.py',
        old='        if first.rstrip("\\r").lower().startswith("sep=") and len(first.rstrip("\\r")) == 5:',
        new='        if False:',
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestFormatsAsTheyArrive::test_excel_on_windows'),
        ],
    ),
    Control(
        describes='CSV: the declared null values read as empty',
        path='adapters/csv_folder_adapter.py',
        old='                rows.append((line, {name: (None if value in self.null_values else value)',
        new='                rows.append((line, {name: value',
        tests=[
            ('tests/unit/test_csv_folder_adapter.py::'
             'TestFormatsAsTheyArrive::test_empty_means_null_and_others_can_be_named'),
        ],
    ),
    Control(
        describes='REST: server errors and 429 are retried',
        path='adapters/rest_adapter.py',
        old='                if response.status_code not in RETRIED:',
        new='                if True:',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFailures::test_server_errors_are_retried_with_growing_waits'),
        ],
    ),
    Control(
        describes='REST: a Retry-After the API sends wins over the default wait',
        path='adapters/rest_adapter.py',
        old='            delay = wait if wait is not None else 2.0 ** attempt',
        new='            delay = 2.0 ** attempt',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFailures::test_retry_after_as_a_date_wins'),
        ],
    ),
    Control(
        describes='REST: any other client error stops at once',
        path='adapters/rest_adapter.py',
        old='RETRIED = frozenset({429, 500, 502, 503, 504})',
        new='RETRIED = frozenset({404, 429, 500, 502, 503, 504})',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFailures::test_a_client_error_is_not_retried'),
        ],
    ),
    Control(
        describes='REST: a repeated page token is refused',
        path='adapters/rest_adapter.py',
        old='                if token in seen_tokens:',
        new='                if False:',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestPaging::test_a_repeated_page_token_is_refused_not_followed_forever'),
        ],
    ),
    Control(
        describes='REST: numbers are read as exact decimals',
        path='adapters/rest_adapter.py',
        old='                body = json.loads(response.text, parse_float=Decimal)',
        new='                body = json.loads(response.text, parse_float=float)',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestPaging::test_numbers_stay_exact'),
        ],
    ),
    Control(
        describes='REST: the credential never appears in an error',
        path='adapters/rest_adapter.py',
        old='            body = body.replace(secret, "***")',
        new='            pass',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFailures::test_the_credential_never_appears_in_an_error'),
        ],
    ),
    Control(
        describes='REST: one read of a table per sync',
        path='adapters/rest_adapter.py',
        old=('        if self._pinned is not None:\n'
             '            self._pinned[table_name] = records'),
        new=('        if False:\n'
             '            self._pinned[table_name] = records'),
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestOneReadPerSync::test_columns_and_rows_come_from_one_read'),
        ],
    ),
    Control(
        describes='REST: a bearer token is sent',
        path='adapters/rest_adapter.py',
        old='            return {"Authorization": f"Bearer {auth[\'token\']}"}, {}, None',
        new='            return {}, {}, None',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestTheSimulatorsApi::test_every_page_is_read_once'),
        ],
    ),
    Control(
        describes='SECRETS: a ${VAR} inside a frozen nested block is filled in, and plaintext there refused',
        path='core/secret_references.py',
        old='    if isinstance(value, Mapping):',
        new='    if isinstance(value, dict):',
        tests=[
            ('tests/unit/test_secret_references.py::'
             'TestNestedFrozenBlocks::test_a_reference_inside_a_frozen_nested_block_is_filled'),
            ('tests/unit/test_secret_references.py::'
             'TestNestedFrozenBlocks::test_a_plaintext_credential_there_is_refused'),
        ],
    ),
    Control(
        describes='SOURCES: a MariaDB copy longer than the time limit is not cut off',
        path='adapters/sqlalchemy_adapter.py',
        old='        conn.exec_driver_sql(self._time_limit_sql(0))',
        new='        conn.exec_driver_sql(self._time_limit_sql(self._timeout_seconds))',
        tests=[
            ('tests/unit/test_server_databases_read_safely.py::'
             'TestMariaDB::test_a_copy_longer_than_the_limit_finishes_and_the_limit_returns'),
        ],
    ),
    Control(
        describes='REST: a token echoed alone in an error is masked',
        path='adapters/rest_adapter.py',
        old='        self._secrets = [str(auth[key]) for key in ("token", "api_key", "password",\n'
            '                                                    "client_secret")',
        new='        self._secrets = [str(auth[key]) for key in ()',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFoundInReview::test_a_bearer_token_echoed_alone_is_masked'),
        ],
    ),
    Control(
        describes='REST: the login is never sent to another host',
        path='adapters/rest_adapter.py',
        old='        if _origin(url) != self._origin:',
        new='        if False:',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFoundInReview::test_a_next_page_on_another_host_is_not_sent_the_login'),
        ],
    ),
    Control(
        describes='REST: a page served twice is refused',
        path='adapters/rest_adapter.py',
        old='                if signature in seen_tokens:',
        new='                if False:',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFoundInReview::test_an_api_ignoring_the_page_parameter_is_refused_quickly'),
        ],
    ),
    Control(
        describes='REST: only an empty page ends page or offset paging',
        path='adapters/rest_adapter.py',
        old='                    params[name] = int(params[name]) + len(page)',
        new=('                    params[name] = int(params[name]) + len(page)\n'
             '                    if paging.get("page_size") and len(page) < int(paging["page_size"]):\n'
             '                        break'),
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFoundInReview::test_a_server_capping_the_page_size_is_still_read_to_the_end'),
        ],
    ),
    Control(
        describes='REST: the health check is one attempt',
        path='adapters/rest_adapter.py',
        old='        self._get(urljoin(self.base_url, spec["path"]), dict(spec["params"]), retries=0)',
        new='        self._get(urljoin(self.base_url, spec["path"]), dict(spec["params"]))',
        tests=[
            ('tests/unit/test_rest_adapter.py::'
             'TestFoundInReview::test_the_health_check_does_not_wait_out_retries'),
        ],
    ),
    Control(
        describes="SIM: an export's header follows a live rename",
        path="sim/simulator/event.py",
        old="    header = [now for now in (world.lineage.column(silo_name, table_name, name)\n"
            "                              for name in columns) if now is not None]",
        new="    header = list(columns)",
        tests=["sim/tests/test_control.py::"
               "test_a_live_rename_is_followed_by_the_business_and_its_exports"],
    ),
    Control(
        describes="SIM: live drift goes through the world, so the business follows it",
        path="sim/simulator/control.py",
        old="    world.apply_change(silo_name, change)\n",
        new="    world.schemas[silo_name] = change.apply(world.silo(silo_name), "
            "world.database(silo_name), world.schema(silo_name), world.clock.now())\n",
        tests=["sim/tests/test_control.py::"
               "test_a_live_rename_is_followed_by_the_business_and_its_exports"],
    ),
    Control(
        describes="SIM: a resume keeps the record of renames",
        path="sim/simulator/resume.py",
        old="    world.lineage = Lineage.from_json(saved.lineage)\n",
        new="",
        tests=["sim/tests/test_resume.py::"
               "test_a_renamed_column_is_still_followed_after_a_resume"],
    ),
    Control(
        describes="SIM: a PostgreSQL outage ends the reader's open sessions",
        path="sim/simulator/outages.py",
        old="SELECT count(pg_terminate_backend(pid))",
        new="SELECT count(pid)",
        tests=["sim/tests/test_control.py::"
               "test_a_postgresql_outage_ends_open_sessions_and_refuses_new_ones"],
    ),
    Control(
        describes="SIM: a paused world does not tick",
        path="sim/simulator/cli.py",
        old="                time.sleep(CONTROL_POLL_SECONDS)\n                continue",
        new="                time.sleep(CONTROL_POLL_SECONDS)",
        tests=["sim/tests/test_control.py::test_a_paused_world_does_not_tick"],
    ),
    Control(
        describes="SIM: control.json is readable by its owner only",
        path="sim/simulator/control.py",
        old="os.O_TRUNC, 0o600)",
        new="os.O_TRUNC, 0o644)",
        tests=["sim/tests/test_control.py::"
               "test_the_control_file_is_the_owners_alone_and_not_a_connection"],
    ),
    Control(
        describes="SIM: a new table under an old pack name is not the pack's",
        path="sim/simulator/lineage.py",
        old="        return None if (silo, current) in self._tables else current",
        new="        return current",
        tests=["sim/tests/test_lineage.py::"
               "test_a_new_table_wearing_an_old_name_is_not_the_packs"],
    ),
    Control(
        describes="SIM: a new column under an old pack name is not the pack's",
        path="sim/simulator/lineage.py",
        old="        return None if (silo, table, current) in self._columns else current",
        new="        return current",
        tests=["sim/tests/test_lineage.py::"
               "test_a_new_column_wearing_an_old_name_is_not_the_packs"],
    ),
    Control(
        describes="SIM: a control command the caller gave up on is not carried out",
        path="sim/simulator/control.py",
        old="            if not future.set_running_or_notify_cancel():\n"
            "                continue        # withdrawn by a caller that stopped waiting\n",
        new="",
        tests=["sim/tests/test_control_queue.py::"
               "test_a_command_the_caller_gave_up_on_is_not_carried_out"],
    ),
    Control(
        describes="SIM: a fresh world records its replicas' schemas",
        path="sim/simulator/runner.py",
        old="        schemas=dict(schemas),",
        new="        schemas=dict(pack.schemas),",
        tests=["sim/tests/test_replicas.py::test_a_world_with_a_replica_resumes"],
    ),
    Control(
        describes="FORECAST: the first period, nearly always a part one, is not fitted",
        path="core/forecasts.py",
        old="        return self.starts[1:], self.values[1:]",
        new="        return self.starts, self.values",
        tests=["tests/unit/test_forecasts.py::TestTheSeries::"
               "test_the_first_period_is_shown_but_not_fitted"],
    ),
    Control(
        describes="SIM: an expired REST token is refused and says so",
        path="sim/simulator/silos/rest.py",
        old="        if now >= expires:",
        new="        if False:",
        tests=["sim/tests/test_rest_silo.py::"
               "test_a_token_works_until_it_expires_and_then_says_so"],
    ),
    Control(
        describes="SIM: a REST fault_rate really fails requests",
        path="sim/simulator/silos/rest.py",
        old="            if self._random.random() >= self.fault_rate:\n"
            "                return None",
        new="            return None",
        tests=["sim/tests/test_rest_silo.py::test_every_request_can_fail_with_a_server_error"],
    ),
    Control(
        describes="SIM: If-Modified-Since filters records",
        path="sim/simulator/silos/rest.py",
        old="                records = silo._modified_since(records, since)",
        new="                pass",
        tests=["sim/tests/test_rest_silo.py::test_if_modified_since_returns_only_what_changed"],
    ),
    Control(
        describes="SIM: a non-atomic file is seen half-written",
        path="sim/simulator/silos/filedrop.py",
        old="            self.place(filename, payload[: max(1, len(payload) // 2)], atomic=False)",
        new="            self.place(filename, payload, atomic=False)",
        tests=["sim/tests/test_filedrop_silo.py::"
               "test_a_non_atomic_file_is_half_written_until_the_next_tick"],
    ),
    Control(
        describes="SIM: Excel drops leading zeros",
        path="sim/simulator/silos/filedrop.py",
        old='        shown = format(Decimal(text).normalize(), "f")',
        new="        shown = text",
        tests=["sim/tests/test_filedrop_silo.py::"
               "test_excel_conversions_apply_to_every_cell_but_the_header"],
    ),
    Control(
        describes="SIM: the runner gives sources their between-ticks turn",
        path="sim/simulator/runner.py",
        old="        silo.between_ticks(world.clock.now())",
        new="        pass",
        tests=["sim/tests/test_publishing.py::"
               "test_a_packs_file_options_reach_the_share_and_late_files_follow_the_clock"],
    ),
    Control(
        describes="SIM: without default privileges a later table refuses the reader",
        path="sim/simulator/silos/reader.py",
        old='          if getattr(silo, "reader_default_privileges", True) else []),',
        new="          if True else []),",
        tests=["sim/tests/test_database_realism.py::"
               "test_a_table_added_later_is_refused_without_default_privileges"],
    ),
    Control(
        describes="SIM: row security with no policy hides every row",
        path="sim/simulator/silos/reader.py",
        old="    if tables:\n        _run(silo, database, [f'ALTER TABLE",
        new="    if False:\n        _run(silo, database, [f'ALTER TABLE",
        tests=["sim/tests/test_database_realism.py::"
               "test_row_security_with_no_policy_shows_the_reader_nothing_and_says_nothing"],
    ),
    Control(
        describes="SIM: MariaDB consumer limits arrive through init_connect",
        path="sim/simulator/silos/mariadb.py",
        old="                *self._init_connect(),\n",
        new="",
        tests=["sim/tests/test_database_realism.py::"
               "test_the_reader_is_disconnected_when_idle_and_the_business_is_not"],
    ),
    Control(
        describes="SIM: zero dates are written where configured",
        path="sim/simulator/relational.py",
        old='    if value is None and getattr(silo, "zero_dates", False):',
        new="    if False:",
        tests=["sim/tests/test_database_realism.py::"
               "test_the_business_writes_zero_dates_where_it_has_none"],
    ),
    Control(
        describes="LOAD: with no write_targets, only writable silos get a writer",
        path="core/deployment_loader.py",
        old='                    if silo.get("adapter") in _WRITE_ADAPTER_REGISTRY}',
        new="}",
        tests=["tests/unit/test_external_writes_are_opt_in.py::TestWhichSilosGetAWriteAdapter::"
               "test_absent_leaves_out_what_cannot_be_written"],
    ),
    Control(
        describes="REST: an OAuth token the server ended is renewed once",
        path="adapters/rest_adapter.py",
        old="                if response.status_code == 401 and self._oauth is not None and not renewed:",
        new="                if False:",
        tests=["tests/unit/test_rest_adapter.py::TestTokensThatExpire::"
               "test_a_token_the_server_ended_is_renewed_once_and_the_read_goes_on"],
    ),
    Control(
        describes="CSV: a zipped file is opened",
        path="adapters/csv_folder_adapter.py",
        old='        if name.endswith(".zip"):\n            try:',
        new="        if False:\n            try:",
        tests=["tests/unit/test_csv_folder_adapter.py::TestCompressedFiles::"
               "test_a_zipped_export_from_the_simulator_is_read"],
    ),
    Control(
        describes="SYNC: an empty read with rows hidden from the account is refused",
        path="core/mirror/iceberg_sync.py",
        old='        if getattr(hidden_rows, "every_row", False) and row_count == 0:',
        new="        if False:",
        tests=["tests/unit/test_server_databases_read_safely.py::TestAnEmptyReadWithRowsHidden::"
               "test_a_first_sync_that_reads_nothing_is_refused_and_says_why"],
    ),
    Control(
        describes="TYPES: a declared silo's zero dates are read as empty",
        path="core/ontology/field_types.py",
        old="    if zero_dates and data_type in _TEMPORAL and is_zero_date(value):",
        new="    if False:",
        tests=["tests/unit/test_numbers_and_dates_as_sources_write_them.py::TestZeroDates::"
               "test_through_a_real_sync_and_the_refusal_says_how"],
    ),
    Control(
        describes="SIM: a replica withholds what its source withholds",
        path="sim/simulator/runner.py",
        old="            origin = pack.silo(silo_name).replicates or silo_name",
        new="            origin = silo_name",
        tests=["sim/tests/test_replicas.py::test_a_replica_withholds_what_its_source_withholds"],
    ),
    Control(
        describes="LIVE: the harness names a value Elysium serves wrongly",
        path="scripts/live_world.py",
        old="             for column in truth[key] if served[key].get(column) != truth[key][column]]",
        new="             for column in truth[key] if False]",
        tests=["tests/unit/test_live_world.py::TestHowItJudges::"
               "test_a_missing_an_extra_and_a_wrong_row_are_each_named"],
    ),
    Control(
        describes="DRIFT: a suspected rename holds the table",
        path="core/mirror/drift_policy.py",
        old='        if appeared and on_suspected_rename != "serve_empty":',
        new="        if False:",
        tests=["tests/unit/test_a_source_changes_and_what_a_reader_sees.py::TestARenamedColumn::"
               "test_a_rename_holds_the_table_at_its_last_good_copy"],
    ),
    Control(
        describes="CSV: a file ending part-way through a line is refused",
        path="adapters/csv_folder_adapter.py",
        old='        if bare and not text.endswith(("\\n", "\\r")) and not self.allow_unterminated:',
        new="        if False:",
        tests=["tests/unit/test_csv_folder_adapter.py::TestAFileEndingPartWayThroughALine::"
               "test_it_is_refused_naming_the_file"],
    ),
    Control(
        describes="SYNC: a table gone from the source is named as gone",
        path="core/mirror/iceberg_sync.py",
        old="        if tables is None or table_name in tables:\n            return",
        new="        if True:\n            return",
        tests=["tests/unit/test_a_missing_source_table.py::TestOnSQLite::"
               "test_a_dropped_table_is_named_as_gone"],
    ),
    Control(
        describes="SIM: a type change keeps NOT NULL unless it says otherwise",
        path="sim/simulator/spec/migrations.py",
        old='    if "nullable" not in definition and existing is not None:',
        new="    if False:",
        tests=["sim/tests/test_migrations.py::"
               "test_a_type_change_keeps_not_null_unless_it_says_otherwise"],
    ),
    Control(
        describes="SYNC: a lagging standby's copy is dated from its last replayed change",
        path="core/mirror/iceberg_sync.py",
        old="            read_started = behind.as_of\n",
        new="",
        tests=["tests/unit/test_a_lagging_standby.py::"
               "test_a_lagging_standby_dates_the_copy_from_its_last_change"],
    ),
    Control(
        describes="SIM: a streaming replica's replay can be paused",
        path="sim/simulator/silos/postgres.py",
        old='            conn.execute("SELECT pg_wal_replay_pause()" if paused',
        new='            conn.execute("SELECT 1" if paused',
        tests=["sim/tests/test_replicas.py::"
               "test_paused_replay_is_lag_and_resumed_replay_catches_up"],
    ),
    Control(
        describes="OVERLAY: Elysium's writes are laid over each type from that type's own data time",
        path="core/ontology/mediator.py",
        old="        return self.mirror_synced_at_by_type.get(object_type, self.mirror_synced_at)",
        new="        return self.mirror_synced_at",
        tests=["tests/unit/test_the_overlay_runs_per_type.py::TestTheOverlayRunsFromEachTypesData::"
               "test_a_type_read_after_the_write_serves_its_own_data"],
    ),
    Control(
        describes="ENRICH: a classified field is never an input to a model",
        path="core/ontology/enriched_fields.py",
        old="        if labels:\n            raise ValueError(",
        new="        if False:\n            raise ValueError(",
        tests=["tests/unit/test_enriched_fields.py::TestTheDeclaration::test_a_classified_input_is_refused_never_sent"],
    ),
    Control(
        describes="ENRICH: only an APPROVED recipe reaches gold",
        path="core/enrichment_recipes.py",
        old="\"field_name = ? AND declaration_hash = ? AND status = 'approved' \"",
        new="\"field_name = ? AND declaration_hash = ? AND status != 'rejected' \"",
        tests=["tests/integration/test_enriched_fields_reach_gold.py::test_empty_until_approved_then_filled_and_searchable",
               "tests/unit/test_enriched_fields.py::TestTheStore::test_only_an_approved_recipe_for_the_current_question_reaches_gold"],
    ),
    Control(
        describes="ENRICH: an approval lapses when the question changes",
        path="core/enrichment_recipes.py",
        old="\"field_name = ? AND declaration_hash = ? AND status = 'approved' \"",
        new="\"field_name = ? AND (declaration_hash = ? OR 1) AND status = 'approved' \"",
        tests=["tests/unit/test_enriched_fields.py::TestTheStore::test_only_an_approved_recipe_for_the_current_question_reaches_gold"],
    ),
    Control(
        describes="ENRICH: reading an inference needs reading its inputs",
        path="core/ontology/derived_fields.py",
        old="    derived += [(type_name, field_name, enrichment.inputs)",
        new="    derived += [(type_name, field_name, ())",
        tests=["tests/unit/test_enriched_fields.py::test_reading_an_inference_needs_reading_what_it_was_inferred_from"],
    ),
    Control(
        describes="ENRICH-REVIEW: a recipe from another compartment is not shown",
        path="api/routes.py",
        old="            and recipe.provenance[\"compartment\"] != current_user.security_value:",
        new="            and False:",
        tests=["tests/integration/test_enriched_fields_reach_gold.py::TestReviewingARecipe::test_another_compartments_recipe_is_not_shown_or_decidable"],
    ),
    Control(
        describes="ENRICH-REVIEW: only manage:deployment reviews a recipe",
        path="api/routes.py",
        old=("    if not authorize(current_user, roles, \"manage:deployment\"):\n"
             "        return None\n    if \"compartment\""),
        new="    if False:\n        return None\n    if \"compartment\"",
        tests=["tests/integration/test_enriched_fields_reach_gold.py::TestReviewingARecipe::test_without_manage_deployment_it_is_not_there"],
    ),
    Control(
        describes="ENRICH-REVIEW: rules for a changed question cannot be approved",
        path="api/routes.py",
        old="    if not shown[\"current\"]:\n        raise HTTPException(status_code=409",
        new="    if False:\n        raise HTTPException(status_code=409",
        tests=["tests/integration/test_enriched_fields_reach_gold.py::TestReviewingARecipe::test_rules_for_a_question_nobody_asks_any_more_cannot_be_approved"],
    ),
    Control(
        describes="LOOP: an invented step is corrected, not nudged as a finish",
        path="core/agent/agentic_loop.py",
        old='            if step["step"] == "finish" and step.get("unrecognised"):',
        new='            if False:',
        tests=["tests/unit/test_stop_reason_is_named.py::"
               "test_an_invented_count_is_answered_with_the_step_it_meant"],
    ),
]


#: Where a break's original text is parked while the break is applied.
#: The `finally` that restores it cannot help if the process is KILLED
#: -- which happened: a run inside a command that hit its time limit
#: was killed mid-control, and left a break in the working tree.
#:
#: It was found because a later run reported "the break matches 0
#: times", and it could as easily have been found by somebody
#: wondering why their withheld table was suddenly readable.
IN_PROGRESS = ROOT / ".controls-in-progress.json"


def restore_anything_left_behind() -> list[str]:
    """Put back a break from a run that was killed rather than finished."""
    if not IN_PROGRESS.exists():
        return []
    try:
        parked = json.loads(IN_PROGRESS.read_text())
    except (OSError, ValueError):
        # Unreadable is worse than absent: something is in the tree and
        # this cannot say what. Better to shout than to carry on.
        raise SystemExit(
            f"{IN_PROGRESS} is unreadable, and it means a break may still be "
            f"applied. Check `git status` before running anything."
        ) from None
    restored = []
    for path, original in parked.items():
        (ROOT / path).write_text(original)
        restored.append(path)
    IN_PROGRESS.unlink()
    return restored


def apply(control: Control) -> str:
    """Break the code, returning what was there before."""
    path = ROOT / control.path
    original = path.read_text()
    occurrences = original.count(control.old)
    if occurrences != 1:
        raise SystemExit(
            f"{control.path}: the break for {control.describes!r} matches "
            f"{occurrences} times, not once. A break that matches nothing runs "
            f"the UNMODIFIED code and passes, which is the failure this whole "
            f"script exists to catch."
        )
    # Parked BEFORE the break goes in, so a kill between the two leaves
    # the file untouched rather than broken with no record of it.
    IN_PROGRESS.write_text(json.dumps({control.path: original}))
    path.write_text(original.replace(control.old, control.new))
    return original


def run(control: Control) -> tuple[bool, str]:
    """Run the control's tests, expecting them to fail."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *control.tests, "-q", "--no-header", "-x"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return result.returncode != 0, (result.stdout or result.stderr).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check that the negative controls actually fire.")
    parser.add_argument("--only", help="run controls whose description contains this")
    arguments = parser.parse_args(argv)

    left = restore_anything_left_behind()
    for path in left:
        print(f"  restored {path}, left broken by a run that was killed")

    controls = [c for c in CONTROLS
                if not arguments.only or arguments.only.lower() in c.describes.lower()]
    if not controls:
        print(f"no control matches {arguments.only!r}", file=sys.stderr)
        return 1

    silent = []
    for control in controls:
        original = apply(control)
        try:
            fired, output = run(control)
        finally:
            # Restored whatever happened, including on Ctrl-C. A broken
            # file left behind would look like a bug in the code rather
            # than in this script.
            (ROOT / control.path).write_text(original)
            IN_PROGRESS.unlink(missing_ok=True)
        if fired:
            print(f"  fires   {control.describes}")
        else:
            silent.append(control)
            print(f"  SILENT  {control.describes}")
            print(f"          broke {control.path} and the tests still passed")
            print(f"          {output.splitlines()[-1] if output else ''}")

    print()
    if silent:
        print(f"{len(silent)} control(s) did not fire. Either the break is not the "
              f"break it claims, or the tests do not check what they appear to -- "
              f"and it is usually the second.")
        return 1
    print(f"All {len(controls)} controls fire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
