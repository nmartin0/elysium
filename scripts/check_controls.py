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
