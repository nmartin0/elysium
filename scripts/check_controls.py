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
        old="    if not any(entities.values()) and world.pack.persistence:",
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
        old="        if self.window is not None:\n"
            "            statement += self.window.clause(dialect, dialect.placeholder)\n"
            "            parameters = (self.window.earliest(context.now),)\n"
            "        rows = fetch_all(source, world.database(self.source_silo), "
            "statement, parameters)\n"
            "        name = str(self.filename.value(context))",
        new="        rows = fetch_all(source, world.database(self.source_silo), statement)\n"
            "        name = str(self.filename.value(context))",
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
            '                     f"SELECT {selected} FROM {dialect.quote(table_name)}")',
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
        old="            entered = row[2] if where.entered_column is not None else None",
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
        old="        appeared = tuple(sorted(set(present) - set(columns)))",
        new="        appeared = ()",
        tests=["tests/unit/test_a_source_changes_and_what_a_reader_sees.py::TestARenamedColumn::test_and_the_operator_is_told_the_remedy_that_does_not_LOSE_A_FIELD"],
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
        old=("        if not previous or len(rows) >= previous "
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
        describes="R13: a sync drops erased rows on the way in",
        path="core/mirror/iceberg_sync.py",
        old="        if suppression is not None:\n            from core.mirror.erasure import suppress_rows",
        new="        if False:\n            from core.mirror.erasure import suppress_rows",
        tests=["tests/unit/test_erasure.py::TestErasing::test_while_the_source_still_returns_them_every_sync_drops_them"],
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
        old="    if not config.label_enforcement:\n        return config.roles",
        new="    if True:\n        return config.roles",
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
        old="        values.append(str(value).casefold() if field_name in rule.casefold else str(value))",
        new="        values.append(str(value))",
        tests=["tests/unit/test_identity_resolution.py::TestADeclaredCasefold::"
               "test_declared_the_two_spellings_are_one_entity"],
    ),
    Control(
        describes="F-09: no security value is captured as None, not an empty string",
        path="core/memory/guard.py",
        old="                            None if security_value is None else str(security_value))",
        new="                            str(security_value or \"\"))",
        tests=["tests/unit/test_memory_guard.py::"
               "test_an_object_with_no_security_value_is_captured_as_none_not_empty"],
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
        old="             if any(isinstance(row.get(column), str) for row in raw_rows)}",
        new="             if True}",
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
