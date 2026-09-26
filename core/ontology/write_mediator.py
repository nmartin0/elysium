"""
write_mediator.py  (the write path -- generic, org-agnostic)

Takes a pre-resolved UserRecord, not a raw user_id -- same reduction as
DataMediator: WriteMediator no longer holds users/security_attribute at
all, only roles (still shared, static config, unaffected by this
change).

Two stages: propose_action() checks RBAC+MAC, validates parameters,
evaluates submission criteria, and resolves the action's own declared
mutations into a snapshot of the fields about to change;
confirm_and_execute() re-verifies that snapshot ATOMICALLY at write
time (per-object lock + adapter.write_fields()'s conditional SQL),
preventing lost updates. PendingWrite is frozen -- nothing about a
proposed write can change between human approval and execution.

NAMED ACTIONS -- matches Palantir Foundry's own action-type model
directly (verified against their docs, not assumed): a proposal names
a NAMED, independently-governed operation (execute:{action_name}, one
grant per action), not a generic CRUD verb with free-form field input.
See propose_action()'s own docstring for the full mechanism.

This file used to hold a SECOND, parallel proposal path (propose_write()
-- free-form write:{type}.{field}/create:{type} grants, the ORIGINAL
model before named actions existed) during this project's own
build-and-prove-in-isolation migration phase. That path has since been
fully migrated and removed -- see git history on the
action-types-redesign branch for the migration pass itself. Every real
schema now declares action_types; there is no remaining fallback.

Used by: core/agent/agentic_loop.py's AgentLoop (write_mediator +
         confirm_write callback, both None if writes are disabled)
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from core.intermediate_layer.access_control import check_access
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import UserRecord, authorize
from core.ontology.interface import ExternalReadAdapter, ExternalWriteAdapter
from core.ontology.mediator import DataMediator
from core.ontology.schema import get_column_for_field
from core.ontology.submission_criteria import evaluate_submission_criteria
from core.ontology.write_log import WriteLogWriter

if TYPE_CHECKING:
    # A real, TYPE_CHECKING-only intersection type -- never a runtime
    # class, never instantiated -- for the one, real, recurring need in
    # this file: several private helpers below (_read_group_fields,
    # _write_fields_with_limiter, _create_object_with_limiter) are only
    # ever called with an adapter obtained via self._adapter_mediator
    # (this class's own internal, write-capable DataMediator -- see
    # this class's own __init__ docstring), which in real, concrete
    # practice always holds an adapter that is BOTH read- and write-
    # capable (adapters/sqlite_adapter.py's own SQLiteWriteAdapter
    # genuinely extends both ExternalReadAdapter and
    # ExternalWriteAdapter). Neither ExternalReadAdapter nor
    # ExternalWriteAdapter alone has both method sets; this says so
    # explicitly, at the one real place it's needed, rather than
    # scattering an unexplained cast() at every individual call site.
    class _ReadWriteAdapter(ExternalReadAdapter, ExternalWriteAdapter):
        pass


def _fields_to_columns(resolved_type_config: dict, values_by_field: dict) -> dict:
    # Standalone, not a method -- needs no WriteMediator state, and is
    # called once per storage GROUP (see _group_changes_by_storage()),
    # each with its own resolved_type_config.
    return {
        get_column_for_field(resolved_type_config, field_name): value
        for field_name, value in values_by_field.items()
    }


# What put a write forward. A closed set, as Literal rather than Enum
# to match SubWrite.operation directly below -- this codebase has no
# Enum anywhere, and a second convention for the same job would be one
# to remember.
#
# "human": a person submitted it directly, through POST
#          /actions/{action_type_name}.
# "agent": the LLM chose it mid-query, through AgentLoop's own
#          propose_action step. The person named in user_id still
#          supplied every permission used -- see UI_ROADMAP.md's
#          approvals record on why the agent is an envelope and never
#          a principal -- but they did not pick this action.
# WHO ASKED FOR A WRITE.
#
# NOT A DETAIL: `origin` reaches the audit trail and the approval
# criteria, so it is how somebody reviewing a queue tells a proposal a
# COLLEAGUE made from one a MODEL made from one NOBODY made.
#
# "automation" IS A THIRD THING, not a kind of agent. An agent is a
# model reasoning on somebody's behalf, in a conversation they are
# having. An automation is a condition that fired while everybody was
# asleep, and the difference matters most to whoever has to decide
# whether to approve it.
Origin = Literal["human", "agent", "automation"]


@dataclass(frozen=True)
class SubWrite:
    # One object's own share of a (possibly multi-object) proposed
    # write -- see PendingWrite's own docstring immediately below for
    # why this is a separate dataclass, nested inside a tuple, rather
    # than PendingWrite itself still holding one flat object_type/
    # object_id/changes triple directly the way it used to.
    #
    # object_id is ALWAYS the real, concrete id here, for BOTH "update"
    # and "create" -- unlike this dataclass's own predecessor
    # (PendingWrite.object_id), which used to stay None for "create"
    # specifically, forcing every consumer (see the old
    # _apply_create_via_log()) to separately re-derive the real id from
    # changes[id_field] each time it was needed. propose_action()
    # already knows the real id at construction time either way (the
    # object_id it was called with for "update"; changes[id_field],
    # already validated present, for "create") -- resolving it once,
    # here, removes that whole re-derivation dance, and gives every
    # future consumer (locking, duplicate-object validation, the
    # write_log_batches JSON) a real id to work with directly, with no
    # special-casing by operation kind.
    object_type: str
    object_id: Any
    operation: Literal["update", "create", "delete"]
    changes: dict
    expected_current_values: dict = field(default_factory=dict)  # for update lost-update checks


@dataclass(frozen=True)
class PendingWrite:
    # sub_writes is ALWAYS at least one entry, even for what looks like
    # an ordinary single-object action -- there is deliberately no
    # separate "single-object" representation living alongside a
    # "multi-object" one. propose_action(), core/ontology/
    # action_types.py's own schema-load validation, AND confirm_and_
    # execute()'s own apply logic all fully support more than one:
    # every write goes through _apply_batch(), one sub_write or many,
    # with no special case for either. (This comment used to say the
    # apply side "still only ever applies sub_writes[0]" -- true when
    # written, stale since the batch work landed. See this file's own
    # AI-notes and write_log.py's MULTI-OBJECT BATCHES section.)
    #
    # action_type_name is the action's own real, raw name (e.g.
    # "TransferFunds") -- distinct from description, which is a
    # human-formatted string that HAPPENS to embed this name but isn't
    # meant to be parsed back apart by anything. Added specifically so
    # confirm_and_execute()'s own audit logging (log_pre()'s action_id)
    # has a real identifier for the ACTION itself to use, the same way
    # propose_action()'s own earliest RBAC-denial log_access() call
    # already does -- neither needs, or should ever need, to fall back
    # to guessing at a single object_type the way the pre-sub_writes
    # design used to.
    sub_writes: tuple[SubWrite, ...]
    user_id: str
    description: str
    action_type_name: str
    # PROVENANCE. Who proposed this, when, and through what.
    #
    # user_id alone is not provenance: both paths that reach
    # propose_action() -- a person filling in ActionForm via POST
    # /actions/{name}, and the agent choosing an action mid-query --
    # set it to the same person, so the two were previously
    # indistinguishable in the record. An approvals inbox has to be
    # able to say "Alice submitted this" versus "the agent proposed
    # this while answering Alice's question", and a reviewer weighs
    # those differently.
    #
    # origin is REQUIRED, with no default, deliberately. A default
    # would be a guess written into the audit trail, and the safe
    # guess does not exist: defaulting to "human" understates agent
    # involvement, and defaulting to "agent" libels a person. Omitting
    # it raises TypeError instead -- the same reasoning
    # core/request_context.py gives for threading its own context
    # explicitly, that "will not start" beats quietly attributing work
    # to the wrong actor.
    #
    # TWO VALUES, not three. Whether a human then CONFIRMED an agent
    # proposal, or auto_execute skipped that step, is a fact about the
    # DECISION rather than the proposal, and belongs to whatever
    # records the decision -- see UI_ROADMAP.md's approvals design
    # record, step 3. Origin answers only "what put this forward".
    #
    # proposed_at is here rather than read back from
    # PendingWriteStore's own expires_at (which is proposed_at + TTL,
    # recoverable only by knowing the TTL) because an auto_execute
    # write never enters that store at all, and would otherwise carry
    # no timestamp anywhere.
    origin: Origin
    proposed_at: datetime
    # WHICH CONFIGURATION AUTHORIZED THIS -- see HOT_RELOAD_PLAN.md.
    #
    # A pending write is the first thing in Elysium that OUTLIVES the
    # request that made it. Everything else is decided and finished
    # inside one call, so the configuration in force could never have
    # changed underneath it. This one waits for a human.
    #
    # Once configuration can be reloaded while running, a write can be
    # proposed under one set of grants and approved under another. That
    # is not hypothetical for an approvals inbox, where the wait is the
    # entire point. Recording the generation is what makes the question
    # answerable at all; deciding what to DO about a mismatch is a
    # later step of that plan, and deliberately not this one.
    #
    # Required, no default, for the same reason origin above is: a
    # default would be a guess written into an audit trail.
    proposed_under_generation: int

    # WHAT A CONFIRM-TIME CRITERION NEEDS, and neither is reconstructible
    # later. The parameters are the action's own inputs, which a
    # `parameter.<name>` reference resolves against; the proposer is the
    # full record, which `proposer.<attribute>` resolves against.
    #
    # THE PROPOSER IS STORED AS A RECORD, not just the user_id already
    # on this class, because a criterion may compare against any
    # attribute -- their MAC value, their role. Re-resolving it at
    # confirm time from the directory would read the CURRENT record,
    # and a four-eyes rule must compare against who proposed it, not
    # against whoever holds that username now.
    parameters: dict
    proposer: UserRecord


def _describe_action(action_type_name: str, action_def: dict, parameters: dict) -> str:
    """A sentence a reviewer can read, not a repr of a dict.

    This was `f"{name}(parameters={parameters})"`, which was fine as a
    log line and became the primary text of an inbox row the moment
    /writes/awaiting existed. Seen in a real queue it reads
    `RecategorizeTransaction(parameters={'transaction_id': 1,
    'new_category': 'travel'})` -- Python punctuation a reviewer has to
    parse before they can think about the decision.

    BUILT FROM WHAT THE DEPLOYMENT ALREADY AUTHORED, not from a new
    field nobody has filled in. Action types carry a `description`
    written for humans, and parameters carry `display_name`. Both
    existed and neither was used here, so a schema that already reads
    well produces a row that already reads well.

    LOSES NOTHING THE OLD FORM CARRIED. Every parameter name and value
    still appears; only the punctuation changes. That matters because
    this string reaches the audit log -- as log_pre's query_text, and
    as the text on an expiry entry -- and a prettier description that
    dropped a parameter would be a quieter audit trail bought with
    readability.
    """
    sentence = (action_def or {}).get("description") or action_type_name
    declared = (action_def or {}).get("parameters") or {}

    parts = []
    for name, value in parameters.items():
        # The authored label where there is one. Falling back to the
        # raw name keeps an un-labelled parameter visible rather than
        # dropping it -- see the docstring on losing nothing.
        label = (declared.get(name) or {}).get("display_name") or name
        parts.append(f"{label}: {value}")

    if not parts:
        return sentence
    return f"{sentence} ({', '.join(parts)})"


# THE MOST OBJECTS ONE ACTION MAY WRITE.
#
# Matches Foundry, which makes actions "unavailable if the number of
# selected objects exceeds 1000" -- and the reasoning is the same. An
# atomic batch has no natural ceiling, so without one a bulk write of
# fifty thousand would hold a lock for minutes, produce an audit entry
# nobody can read, and hand a reviewer a diff they cannot meaningfully
# approve.
#
# A deployment that genuinely needs more is describing a data pipeline
# rather than a user action, and should be pointed at one.
MAX_BULK_OBJECTS = 1000


class NotAutomatable(ValueError):
    """A trigger tried to propose an action that refuses automation.

    ITS OWN TYPE, and NOT a PermissionError: nobody's grants are
    wrong. The action itself says it must be started by a person, and
    a permission error would send somebody auditing roles that are
    perfectly correct.
    """


class ConstraintViolation(ValueError):
    """A value a field's declared constraints refuse.

    ITS OWN TYPE, and NOT a PermissionError: nobody's grants are wrong.
    The value is, and the message names the field, the rule and the
    value so the person proposing it can choose another.
    """


class CrossCompartmentWrite(ValueError):
    """An action would move data between security compartments.

    ITS OWN TYPE because it is not an authorization failure. Every
    individual check PASSED -- the caller may read the source and may
    write the target. What is refused is the COMBINATION, which no
    per-object check can see.
    """


def _compartment_crossings(read_labels: dict, write_labels: dict) -> list[tuple]:
    """Where an action would write data into a different compartment.

    THE BELL-LAPADULA \\*-PROPERTY, in the form Elysium needs. The
    model's rule is that a subject may not write to a label that does
    not DOMINATE what it read; dominance for compartments is set
    containment.

    ELYSIUM'S LABELS ARE SINGLE COMPARTMENTS today, so containment
    reduces to equality -- and that is the check. It generalises
    without rewriting when a label becomes a set: replace `!=` with
    "not a superset".

    COMPARTMENTS, NOT LEVELS, and the two are separate for a reason.
    Foundry keeps markings (compartments, conjunctive) apart from
    Classification-based Access Controls (levels, hierarchical) and
    says "classifications can not be used together with markings...
    on the same mandatory control property". CBAC is off by default
    there. A level hierarchy is a chain of nested compartment sets
    anyway, so deferring levels costs no expressiveness.

    RETURNS THE CROSSINGS rather than a boolean, because a refusal
    that cannot say WHICH object went where is one nobody can act on.
    """
    crossings = []
    for (read_type, read_id), read_label in read_labels.items():
        if read_label is None:
            # AN UNLABELLED SOURCE CANNOT LEAK A COMPARTMENT it does
            # not have. This is not a silent pass: an object with no
            # security value is one the ontology declared as needing
            # none.
            continue
        for (write_type, write_id), write_label in write_labels.items():
            if write_label is not None and write_label != read_label:
                crossings.append(
                    (read_type, read_id, read_label,
                     write_type, write_id, write_label),
                )
    return crossings


class WriteMediator:
    def __init__(
        self, mediator: DataMediator, write_adapters: dict[str, ExternalWriteAdapter], roles: dict,
        action_types: dict, generation: int,
        source_schema: dict | None = None, source_silo_for_type: dict | None = None,
    ):
        # action_types is required, not optional -- a WriteMediator's
        # only real capability is propose_action(), which is useless
        # without declared actions. Verified directly: EVERY real
        # construction site already passes it explicitly; nothing
        # depends on a None-shaped default. Keeping optionality alive
        # after migration is actually complete is compat cruft, not a
        # real capability -- removed rather than left as unused,
        # confusing dead weight.
        self.mediator = mediator
        self.roles = roles
        self.action_types = action_types
        # Taken from the SAME DeploymentConfig the mediator's audit log
        # was built from, so a pending write and the audit entries
        # describing it can never name different generations. Passing
        # it separately to each was the alternative and is exactly how
        # two sources of one truth start to disagree.
        self.generation = generation
        # write_adapters -- a real, SEPARATE, independent set of
        # adapters, never mediator's own (see this class's own
        # AI-notes for the full story: Phase 0 of the read-only mirror
        # initiative, a real, found prerequisite -- WriteMediator used
        # to borrow SIX of DataMediator's own private methods
        # (_resolve_shared_storage, _write_limiter_for_silo,
        # _locks_for_objects, _type_schema, _read_field_with_log_check,
        # _security_allowed) by reaching directly into
        # self.mediator, meaning this class had no adapter
        # identity of its own at all. Once DataMediator's own adapters
        # move to a genuinely read-only credential, that borrowing
        # would have silently broken every real write in the system.
        #
        # A real, SEPARATE, internal DataMediator instance is built
        # here specifically to REUSE those six methods' own, already-
        # correct, already-tested implementations -- not a second,
        # parallel reimplementation of the same logic, matching this
        # project's own DRY discipline. schema/silo_for_type/roles are
        # read-only, ontology-describing dicts, not live connections --
        # confirmed directly safe to keep sharing from `mediator`
        # itself, unlike the adapters themselves. write_log/audit_log
        # ALSO stay the SAME, shared instances mediator itself holds
        # -- deliberately, confirmed directly as still correct to
        # share (both are genuinely cross-cutting infrastructure, not
        # a silo-specific connection/adapter at all; see this class's
        # own write_log/audit_log properties immediately below, which
        # keep reading from `mediator` directly, unchanged).
        # cast(): write_adapters is dict[str, ExternalWriteAdapter] --
        # DataMediator's own __init__ statically expects dict[str,
        # ExternalReadAdapter], since that's genuinely all a normal,
        # real, read-only DataMediator ever needs. This specific
        # DataMediator instance is never that normal case, though --
        # it is WriteMediator's own internal, private helper (never
        # returned, never handed to any other caller), built
        # specifically to reuse DataMediator's own six already-
        # correct methods against write_adapters instead of
        # duplicating them -- so the real, concrete adapters it holds
        # genuinely are ExternalWriteAdapter instances throughout (in
        # practice, adapters/sqlite_adapter.py's own SQLiteWriteAdapter,
        # which -- see that class's own docstring -- also genuinely
        # implements ExternalReadAdapter's own contract too, via real
        # inheritance from SQLiteReadAdapter). The cast is safe
        # specifically because this instance's own adapters are never
        # read through this constructor's own, narrower, static type.
        # THE SOURCE SCHEMA, NOT THE READ MEDIATOR'S (GOLD-8). Reads
        # come from gold, whose storage block says `gold.<Type>`; a
        # WRITE goes to the customer's database (decision D3), so it
        # needs the schema that describes THAT. Inheriting the read
        # mediator's schema made every write look for an adapter called
        # "gold" -- caught by six action tests the moment reads moved.
        self._adapter_mediator = DataMediator(
            source_schema or mediator.source_schema,
            cast("dict[str, ExternalReadAdapter]", write_adapters),
            source_silo_for_type or mediator.source_silo_for_type, roles,
            write_log=mediator.write_log, audit_log=mediator.audit_log,
        )
        # write_log is NOT taken as a separate parameter and stored
        # independently -- see this class's own write_log property.
        # WriteMediator has no legitimate reason to use a DIFFERENT
        # write_log than the DataMediator it wraps reads from; reading
        # the SAME shared instance from mediator makes that
        # structurally true rather than something enforced by a
        # runtime "do these two values match" check (which used to
        # exist here, and no longer needs to -- there's only ever one
        # value to begin with now).
        if mediator.write_log is None:
            raise ValueError(
                "WriteMediator requires its DataMediator to be constructed with a "
                "write_log -- confirm_and_execute() depends on it entirely for both "
                "'update' and 'create'."
            )
        # A real, SEPARATE, write-capable WriteLogWriter, derived from
        # the reader's OWN db_path -- deliberately not taken as its own
        # constructor parameter. Deriving it this way makes it
        # structurally impossible for the two to point at different
        # physical databases (the exact "two values that could
        # accidentally drift apart" problem this class's own write_log
        # property was originally written to avoid), while still giving
        # this class the genuinely write-capable instance it needs --
        # see that property's own docstring.
        self._write_log_writer = WriteLogWriter(mediator.write_log.db_path)

    @property
    def write_log(self) -> WriteLogWriter:
        # A real, SEPARATE WriteLogWriter -- no longer the same
        # instance self.mediator holds. A necessary change, matching
        # the same real precedent write_adapters already set in this
        # same class: DataMediator's own write_log is now a genuinely
        # read-only WriteLogReader (structurally incapable of the
        # log_pending_*/mark_* writes every method below depends on),
        # so borrowing it would break every real write. Both still
        # point at the SAME physical database file, so there is still
        # exactly one real write log per deployment -- only the
        # capability differs, which is the entire point of the split.
        return self._write_log_writer

    @property
    def audit_log(self) -> AuditLog:
        # Always the SAME instance self.mediator itself holds -- never
        # a separately-stored copy, matching this class's own
        # write_log property immediately above, for the identical
        # reason. No type-narrowing assert needed here, unlike that
        # one -- mediator.audit_log is never Optional in the first
        # place (see DataMediator's own docstring on why).
        return self.mediator.audit_log

    def _group_changes_by_storage(self, object_type: str, changes: dict) -> list[tuple]:
        # Resolves EACH field individually (a list of exactly one field
        # name each), reusing DataMediator._resolve_shared_storage()
        # directly rather than duplicating its own internal per-field
        # storage-resolution logic -- then groups fields that resolved
        # to the SAME storage back together, so fields sharing one
        # storage still go through ONE write_fields() call (real
        # SQL-level atomicity + efficiency for the common, single-
        # storage case), while fields on DIFFERENT storages become
        # separate groups instead of the outright rejection a single,
        # whole-dict _resolve_shared_storage() call would otherwise
        # raise for spanning more than one storage.
        #
        # Grouped by id(resolved_type_config["storage"]) -- that dict
        # is the SAME object instance every time for the same storage
        # name (type_schema, and therefore its "storage"/
        # "additional_storage" entries, is loaded once and never
        # rebuilt -- see DataMediator._resolve_shared_storage()), so
        # comparing by identity is exact. Deliberately NOT id(adapter)
        # alone -- two different storage names could theoretically
        # share the same underlying silo/adapter while still needing
        # different resolved_type_config (a different table), which
        # grouping by adapter identity alone would incorrectly merge.
        groups: dict[int, tuple] = {}
        for field_name in changes:
            # cast(): this method's own adapter always genuinely comes
            # from self._adapter_mediator, this class's own internal,
            # write-capable helper -- see this class's own __init__
            # docstring, and the module-level _ReadWriteAdapter type's
            # own comment, for why the real, concrete object here is
            # always both read- and write-capable even though
            # _resolve_shared_storage()'s own STATIC return type
            # (inherited, unchanged, from DataMediator) only ever
            # promises ExternalReadAdapter.
            adapter, resolved_type_config = self._adapter_mediator._resolve_shared_storage(object_type, [field_name])
            adapter = cast("_ReadWriteAdapter", adapter)
            key = id(resolved_type_config["storage"])
            if key not in groups:
                groups[key] = (adapter, resolved_type_config, {})
            groups[key][2][field_name] = changes[field_name]
        return list(groups.values())

    def _read_group_fields(self, object_type: str, object_id: Any, adapter: "_ReadWriteAdapter",
                            resolved_type_config: dict, field_names) -> dict:
        # THE single home for "read the current, live value of each
        # field in one already-resolved storage group, straight from
        # the adapter" -- was duplicated three times before this
        # refactor (propose_action()'s own pre-write snapshot,
        # _resume_one_update_entry()'s initial read, and that SAME
        # method's own post-race re-read), identical logic every time.
        # Direct adapter reads, not DataMediator._read_field_with_log_check()
        # -- every caller here is deliberately reading the REAL,
        # physical backend state to compare against, not the log's own
        # masked value; using the log-aware read would be self-
        # defeating for exactly what these callers need to know.
        return {
            field_name: adapter.get_raw_field(
                object_type, object_id, get_column_for_field(resolved_type_config, field_name), resolved_type_config,
            )
            for field_name in field_names
        }

    def _write_fields_with_limiter(self, object_type: str, object_id: Any, adapter: "_ReadWriteAdapter",
                                    resolved_type_config: dict, new_values: dict, expected_values: dict) -> bool:
        # THE single home for "resolve THIS group's own silo's
        # concurrency limiter, then call write_fields() under it" --
        # was duplicated at both places an update group's write is
        # actually attempted (the fresh-apply path in
        # _apply_one_update(), and the resume path in
        # _resume_one_update_entry()), identical shape at each.
        #
        # Resolving per-GROUP's own silo here, not once per pending
        # write from object_type alone, closed a real bug caught by
        # directly tracing this exact call chain, not just reasoned
        # about: object_type alone ALWAYS resolves to the PRIMARY
        # silo's limiter (that lookup no longer exists at all --
        # removed once this fix left it with zero remaining callers).
        # A group writing to a DIFFERENT storage (any MDO
        # additional_storage) would silently borrow the PRIMARY silo's
        # concurrency limiter instead of its own -- wrong capacity
        # accounting in both directions: under-protecting the real
        # target silo if it has a stricter limit, and needlessly
        # contending for the primary silo's slots for a write that
        # never touches it at all.
        write_limiter = self._adapter_mediator._write_limiter_for_silo(resolved_type_config["storage"]["silo"])
        with write_limiter.limit():
            return adapter.write_fields(
                object_type, object_id,
                _fields_to_columns(resolved_type_config, new_values),
                _fields_to_columns(resolved_type_config, expected_values),
                resolved_type_config,
            )

    def _create_object_with_limiter(self, object_type: str, adapter: "_ReadWriteAdapter",
                                     resolved_type_config: dict, values: dict) -> None:
        # THE create-side counterpart to _write_fields_with_limiter()
        # above -- was likewise duplicated at both places a create
        # group's row is actually inserted (_apply_one_create()'s
        # fresh-apply path, and _resume_one_create_entry()'s resume
        # path), identical shape at each.
        write_limiter = self._adapter_mediator._write_limiter_for_silo(resolved_type_config["storage"]["silo"])
        with write_limiter.limit():
            adapter.create_object(object_type, _fields_to_columns(resolved_type_config, values), resolved_type_config)

    def resume_pending_writes(self) -> dict:
        # Called ONCE, at deployment startup (see api/app.py / scripts/
        # run_deployment.py), before serving any real traffic -- the
        # "resume-on-startup" half of crash recovery write_log.py's own
        # module docstring names as this mechanism's next planned piece
        # of work. Scans EVERY still-INCOMPLETE batch (write_log.
        # get_pending_batches()) -- ALWAYS batches now, one sub_write
        # or many, since confirm_and_execute() always goes through
        # _apply_batch() (see that method's own docstring) -- and
        # walks each one's own sub_writes, resolving each via
        # _resume_one_batch() below.
        #
        # Naturally idempotent, safe to call more than once -- every
        # judgment is re-derived fresh from live backend state each
        # time; nothing here depends on a "have I already processed
        # this" flag anywhere. Deliberately STARTUP-TIME only, not a
        # continuously-running background process -- see write_log.py's
        # own module docstring for why periodic/continuous resume stays
        # a further, separately-scoped enhancement, not solved here.
        summary = {"resumed": 0, "already_applied": 0, "ambiguous": 0}
        for batch in self.write_log.get_pending_batches():
            object_refs = [(sw["object_type"], sw["object_id"]) for sw in batch["sub_writes"]]
            with self._adapter_mediator._locks_for_objects(object_refs):
                outcome = self._resume_one_batch(batch)
            # INVARIANT: every resume method returns one of exactly
            # three outcome names. There are five separate return sites
            # across three methods, all producing bare strings with
            # nothing enforcing the vocabulary -- a typo or a new
            # fourth outcome would otherwise surface as a bare KeyError
            # during crash recovery at startup, which is both the worst
            # moment and the least informative message. Naming the
            # offending value makes it immediately obvious what went
            # wrong.
            assert outcome in summary, (
                f"resume returned unknown outcome {outcome!r} -- "
                f"expected one of {sorted(summary)}"
            )
            summary[outcome] += 1
        return summary

    def _resume_one_batch(self, batch: dict) -> str:
        # Walks ONE incomplete batch's own sub_writes, each in one of
        # three states, determined via write_log.get_sub_write_entry():
        #   - No row exists yet -- the process crashed before even
        #     STARTING this sub_write. Applied fresh now, via the SAME
        #     _apply_one_update()/_apply_one_create() _apply_batch()
        #     itself calls -- resuming from nothing is, correctly,
        #     indistinguishable from a fresh apply that simply hadn't
        #     happened yet when the crash occurred.
        #   - Row exists, status='applied' -- already done; nothing to
        #     do.
        #   - Row exists, status='pending' -- genuinely crashed MID-
        #     apply on THIS specific sub_write. Handed off to the
        #     EXISTING, completely unchanged _resume_one_entry() --
        #     its own three-way per-storage-group classification
        #     (already applied / safe to apply / genuinely ambiguous)
        #     needs no knowledge of batches at all; a sub_write's own
        #     write_log row looks identical whether it's standalone or
        #     batch-owned.
        #
        # Returns "resumed" (at least one sub_write was freshly
        # applied or resumed here), "already_applied" (every sub_write
        # was already done), or "ambiguous" (at least one sub_write
        # left genuinely unresolved) -- the SAME three-way aggregation
        # _resume_one_update_entry() already uses one level down, for
        # storage GROUPS within one sub_write; this is the identical
        # principle one level up, for sub_writes within one batch. The
        # WHOLE batch stays 'pending' if even one sub_write is
        # ambiguous, so a caller reading OTHER, genuinely-resolved
        # objects in the SAME batch still sees correct, live data.
        any_applied_here = False
        any_ambiguous = False

        for sub_write_def in batch["sub_writes"]:
            object_type = sub_write_def["object_type"]
            object_id = sub_write_def["object_id"]
            existing_entry = self.write_log.get_sub_write_entry(batch["id"], object_type, object_id)

            if existing_entry is None:
                sub_write = SubWrite(
                    object_type, object_id, sub_write_def["operation"],
                    sub_write_def["changes"], sub_write_def["expected_current_values"],
                )
                # EXHAUSTIVE, AND RAISING ON THE UNKNOWN (001's F-27). This
                # was two-way -- update, else create -- written when there
                # were two operations. A DELETE then fell into create: the
                # delete was lost, recovery reported success, and the log
                # gained a 'create' nobody asked for, because a delete's
                # empty changes passed through create without raising.
                if sub_write.operation == "update":
                    self._apply_one_update(sub_write, batch["id"], batch["user_id"], batch["description"])
                elif sub_write.operation == "delete":
                    self._apply_one_delete(sub_write, batch["id"], batch["user_id"], batch["description"])
                elif sub_write.operation == "create":
                    self._apply_one_create(sub_write, batch["id"], batch["user_id"], batch["description"])
                else:
                    raise ValueError(
                        f"unknown operation {sub_write.operation!r} resuming batch {batch['id']}"
                    )
                any_applied_here = True
                continue

            if existing_entry["status"] == "applied":
                continue

            outcome = self._resume_one_entry(existing_entry)
            if outcome == "resumed":
                any_applied_here = True
            elif outcome == "ambiguous":
                any_ambiguous = True

        if any_ambiguous:
            return "ambiguous"
        self.write_log.mark_batch_applied(batch["id"])
        return "resumed" if any_applied_here else "already_applied"

    def _resume_one_entry(self, entry: dict) -> str:
        # Dispatches on operation -- an UPDATE entry's resume logic is
        # genuinely different from a CREATE entry's (three possible
        # outcomes per group vs two; see each method's own docstring
        # for why). resume_pending_writes() itself stays completely
        # unaware of the distinction, same per-object-locked call
        # either way.
        #
        # EXHAUSTIVE (001's F-27): this was two-way, so a DELETE fell into
        # the update branch, iterated zero storage groups, and was marked
        # applied without its index row ever being written.
        if entry["operation"] == "create":
            return self._resume_one_create_entry(entry)
        if entry["operation"] == "delete":
            return self._resume_one_delete_entry(entry)
        if entry["operation"] == "update":
            return self._resume_one_update_entry(entry)
        raise ValueError(f"unknown operation {entry['operation']!r} resuming entry {entry['id']}")

    def _resume_one_delete_entry(self, entry: dict) -> str:
        """Finishes a delete whose log entry exists but is still pending.

        IDEMPOTENT: the index row may or may not have been written before
        the crash; it is written if missing, then the entry is marked.

        AND NEVER REORDERED. If a create or update for the object was
        applied AFTER this delete was logged, the later operation already
        decides the object's state; recording the delete now would undo
        it. The entry is marked applied without touching the index, which
        leaves the log's order -- the authority -- intact.
        """
        object_type, object_id = entry["object_type"], entry["object_id"]
        if not self.write_log.superseded(object_type, object_id, entry["id"]) \
                and not self.write_log.is_deleted(object_type, object_id):
            self.write_log.record_delete(object_type, object_id, entry["id"])
        self.write_log.mark_applied(entry["id"])
        return "resumed"

    def _resume_one_update_entry(self, entry: dict) -> str:
        # Returns "resumed" (at least one group was freshly applied
        # here), "already_applied" (every group already matched the
        # intended new values -- nothing to apply), or "ambiguous" (at
        # least one group left genuinely unresolved).
        #
        # Per storage group, classifies live backend state into exactly
        # one of three outcomes, comparing the WHOLE group's fields
        # together (matching how they were WRITTEN together, in one
        # atomic SQL statement -- a partial match within one group
        # would mean something outside this system's own write path
        # touched it, not an ordinary crash):
        #   - matches the INTENDED new values -> already applied before
        #     the crash; nothing to do.
        #   - matches the ORIGINAL expected (pre-write) values -> never
        #     applied; safe to apply now, exactly as confirm_and_execute()
        #     would have.
        #   - matches NEITHER -> genuinely ambiguous. Something else
        #     touched this field between the crash and now (or the
        #     write's own precondition was already stale before the
        #     crash even happened). NEVER guessed at by overwriting
        #     either way -- logged via log_write_resume_ambiguous() for
        #     a human to resolve; this group's fields keep reporting the
        #     log's own intended value through get_field() (the same
        #     safe, degraded state as before recovery ran -- not worse).
        #
        # An entry is marked 'applied' only when EVERY group resolves
        # cleanly -- if even one group is ambiguous, the WHOLE entry
        # stays 'pending', so a caller reading OTHER, genuinely-resolved
        # fields on the SAME object still sees correct, live data (each
        # group is judged independently); only the specific ambiguous
        # field's own group keeps deferring to the log.
        object_type = entry["object_type"]
        object_id = entry["object_id"]
        groups = self._group_changes_by_storage(object_type, entry["changes"])
        any_applied_here = False
        any_ambiguous = False

        for adapter, resolved_type_config, group_changes in groups:
            group_expected = {
                field_name: entry["expected_current_values"][field_name]
                for field_name in group_changes
            }
            current_values = self._read_group_fields(object_type, object_id, adapter, resolved_type_config,
                                                       group_changes)

            if current_values == group_changes:
                continue  # already applied before the crash

            if current_values == group_expected:
                success = self._write_fields_with_limiter(
                    object_type, object_id, adapter, resolved_type_config, group_changes, group_expected,
                )
                if success:
                    any_applied_here = True
                    continue
                # A genuine race between our read just above and this
                # write -- something changed the row in between, outside
                # this per-object-locked sequence entirely (extremely
                # unlikely, but not impossible -- e.g. a direct write
                # against the backend from outside this system). Re-read
                # fresh rather than log the now-stale snapshot that made
                # us attempt the write in the first place.
                current_values = self._read_group_fields(object_type, object_id, adapter, resolved_type_config,
                                                           group_changes)
                if current_values == group_changes:
                    continue  # someone else applied it in the race window -- fine

            # Ambiguous: neither matched, from the start or after the
            # race-triggered re-read above. Log per-field, not per-group
            # -- a group can span several fields, and only some of them
            # may actually be the ones that don't match either value.
            any_ambiguous = True
            for field_name in group_changes:
                if current_values[field_name] not in (group_changes[field_name], group_expected[field_name]):
                    self.audit_log.log_write_resume_ambiguous(
                        entry["id"], object_type, object_id, field_name,
                        current_values[field_name], group_expected[field_name], group_changes[field_name],
                    )

        if any_ambiguous:
            return "ambiguous"
        self.write_log.mark_applied(entry["id"])
        return "resumed" if any_applied_here else "already_applied"

    def _resume_one_create_entry(self, entry: dict) -> str:
        # THE create-side counterpart to _resume_one_update_entry() --
        # genuinely SIMPLER: a storage group for a create has only TWO
        # possible states, not three -- the row either already exists
        # (already applied before the crash) or it doesn't (never
        # applied, safe to create now). There's no "ambiguous" case the
        # way update has: update's ambiguous case exists because a
        # field could hold some THIRD, pre-existing value neither the
        # old nor new state expected -- but a create has no "before"
        # state at all to be knocked off course like that. A genuine
        # collision (a row already existing under this id, from
        # entirely outside this system's own write path) surfaces as a
        # real INSERT constraint violation instead -- correctly failing
        # loud rather than silently guessing, matching the SPIRIT of
        # update's own ambiguous case (never overwrite blindly), just
        # enforced by the database itself here rather than by this
        # code's own comparison logic.
        #
        # Checks the type's own id_field specifically to decide "does
        # this row exist yet" -- not the full field set the way update
        # compares -- since a primary key is never legitimately NULL
        # for a real, existing row, regardless of what its OTHER
        # fields happen to be. Reading the full set back and comparing
        # it to entry["changes"] would have a genuine, if narrow, edge
        # case: a create whose group fields are ALL intentionally NULL
        # would look identical whether or not the row actually exists
        # yet. Checking the id specifically has no such ambiguity.
        object_type = entry["object_type"]
        object_id = entry["object_id"]
        id_field = self._adapter_mediator._type_schema(object_type)["id_field"]
        groups = self._group_changes_by_storage(object_type, entry["changes"])
        any_applied_here = False

        for adapter, resolved_type_config, group_changes in groups:
            id_column = get_column_for_field(resolved_type_config, id_field)
            existing_id = adapter.get_raw_field(object_type, object_id, id_column, resolved_type_config)
            if existing_id is not None:
                continue  # row already exists in this storage -- already applied

            group_with_id = {**group_changes, id_field: entry["changes"][id_field]}
            self._create_object_with_limiter(object_type, adapter, resolved_type_config, group_with_id)
            any_applied_here = True

        self.write_log.mark_applied(entry["id"])
        return "resumed" if any_applied_here else "already_applied"

    def visible_action_types(self, user_record: UserRecord) -> dict:
        # Mirrors DataMediator.visible_schema() exactly, for the SAME
        # reason: the model must never be shown an action it isn't
        # actually authorized to invoke. Filters self.action_types down
        # to exactly the ones this user holds an execute: grant for --
        # used by core/llm/agent_step_prompt.py to build the model-
        # facing action vocabulary, and by core/agent/agentic_loop.py's
        # run(), which computes this ONCE per request, same as
        # visible_schema() itself. Also the backend for GET /me/
        # visible-action-types (api/routes.py), Stage 3's own UI-facing
        # action discovery.
        #
        # discover:action_types -- a real, deliberate DEPARTURE from
        # this project's own earlier, more conservative default,
        # decided explicitly with the user after directly researching
        # Palantir's own real, documented behavior: by default, every
        # user with Ontology access sees every action type's own
        # title/description/rules, whether or not they can actually
        # execute it (verified directly against Palantir's real docs,
        # not assumed). A role holding this ONE, single, blanket grant
        # -- matching manage:users' own "not per-resource" shape, not
        # a new per-action-type discover:{name} vocabulary, since the
        # real use case (general orientation, understanding the full
        # business-process catalog) is a role-level decision, not an
        # action-by-action one -- sees the WHOLE catalog here,
        # regardless of which specific actions it can execute.
        #
        # execute: alone remains, unconditionally, the ONLY thing that
        # can ever actually authorize INVOKING an action --
        # propose_action() below enforces that itself, completely
        # unaffected by this method or this grant. A role could hold
        # discover:action_types and zero execute: grants at all, and
        # would correctly see every action's own shape here while
        # being unable to invoke a single one of them -- discovery and
        # execution are two genuinely separate axes, same as
        # Palantir's own real model keeps them.
        if authorize(user_record, self.roles, "discover:action_types"):
            return dict(self.action_types)
        return {
            action_name: action_def
            for action_name, action_def in self.action_types.items()
            if authorize(user_record, self.roles, f"execute:{action_name}")
        }

    def _read_current_state_for_criteria(self, object_type: str, object_id: Any,
                                          criteria: list[dict]) -> dict:
        # Fetches ONLY the fields "current_state" criteria actually
        # need -- read INDIVIDUALLY, one field at a time, rather than
        # batched through _resolve_shared_storage() the way `changes`
        # is. Deliberate: a criterion's own field may live in a
        # DIFFERENT storage than whatever's being written (e.g. a rule
        # about "status" while this write only touches "amount"), and
        # batching would incorrectly trigger the "cannot combine
        # fields from multiple storages" guard for two field sets that
        # were never meant to be resolved together in the first place.
        #
        # Uses DataMediator._read_field_with_log_check() -- the SAME
        # shared "check the write log first, else the real adapter"
        # merge get_field() and search_object() already use. Closes a
        # real, previously-stated gap: this used to read straight from
        # the adapter, meaning submission_criteria evaluation during a
        # NEW propose_action() call could evaluate against stale state
        # if the object already had a pending, unapplied edit from a
        # prior action (see write_log.py's own module docstring, which
        # used to name this exact limitation). Not mediator.get_field()
        # directly, though -- still a mechanical, internal check the
        # system makes on its own authority, not something gated by
        # the acting user's own field-level read grants.
        needed_fields = {c["field"] for c in criteria if c["check"] == "current_state"}
        current_state = {}
        for field_name in needed_fields:
            adapter, resolved_type_config = self._adapter_mediator._resolve_shared_storage(object_type, [field_name])
            current_state[field_name] = self._adapter_mediator._read_field_with_log_check(
                object_type, object_id, field_name, adapter, resolved_type_config
            )
        return current_state

    def _resolve_mutation_value(self, value_spec, parameters: dict, user_record: UserRecord):
        # A mutation's "value" is one of three kinds:
        #   - a LITERAL, used as-is
        #   - "parameter.<name>", a reference to one of the action's own
        #     declared parameters, resolved here at proposal time
        #   - "user.security_value", the ACTING user's own MAC value,
        #     substituted automatically -- NEVER model-supplied. This is
        #     the only safe way for a "create" action to set an object's
        #     security field: a literal would hardcode one tenant's
        #     value for every user; a parameter.<name> reference would
        #     let the model (or a hallucinated/injected value) choose
        #     ANY security value, including one that doesn't belong to
        #     the user actually authorized to perform this action.
        #     Discovered as a REAL, necessary gap while testing a
        #     "create" action end to end -- not a hypothetical: the
        #     INSERT itself failed (a real NOT NULL constraint on the
        #     security column) the moment a create action's mutations
        #     had no way to populate it safely at all.
        # Deliberately a small, fixed set of string-prefix conventions,
        # not a general expression language -- same reasoning as
        # submission_criteria's own fixed operator set (see that
        # module's docstring): a small, safe, easily-validated surface
        # rather than something that needs its own evaluator.
        if isinstance(value_spec, str) and value_spec.startswith("parameter."):
            param_name = value_spec[len("parameter."):]
            if param_name not in parameters:
                # Should be unreachable -- required-ness is validated
                # before mutations are ever resolved -- but a mutation
                # referencing a parameter that was never DECLARED at
                # all (a schema-authoring mistake, not a caller
                # mistake) would reach here. Fail loudly, not silently
                # substitute None.
                raise ValueError(f"Mutation references undeclared or missing parameter: {param_name!r}")
            return parameters[param_name]
        if value_spec == "user.security_value":
            return user_record.security_value
        return value_spec

    def _authorize_sub_write(self, user_record: UserRecord, object_type: str, object_id: Any,
                             operation: str, execute_action_id: str, rbac_allowed: bool) -> None:
        """MAC for one sub_write, audited, raising on refusal.

        A CREATE has no existing row for MAC to consult, so it passes
        on MAC grounds and is gated by RBAC alone -- the execute: grant
        is the whole check. Update and delete consult the object's
        security value the same way a read would.

        Extracted from propose_action() so its loop reads as its four
        concerns -- resolve, authorize, check criteria, build -- rather
        than as one 65-line body with cyclomatic complexity 26.
        """
        if operation == "create":
            # NO ROW TO CONSULT, so MAC cannot be evaluated and the
            # execute: grant is the whole check. check_access() has no
            # way to express that -- it would read a security value
            # from an object that does not exist yet and deny -- so
            # this branch stays as it was. Inventing a skip-MAC
            # parameter to route it through would weaken the chokepoint
            # in order to tidy a docstring, which is the wrong trade.
            self.audit_log.log_access(
                user_record.user_id, object_type, object_id, execute_action_id,
                mac_allowed=True, rbac_allowed=rbac_allowed,
            )
            return

        # THROUGH THE CHOKEPOINT (004-8). This computed MAC inline and
        # logged it by hand -- the same two gates check_access() makes,
        # minus one thing only it does: on a MAC denial it asks whether
        # the object's security value could be resolved AT ALL, and
        # records log_security_resolution_failed() when it could not.
        # That distinguishes an orphaned MDO record -- a data-integrity
        # signal -- from an ordinary mismatch. It is called from
        # exactly ONE place in core/, inside check_access(), so a path
        # that does not go through there cannot emit it. The same
        # broken object therefore produced that signal on a READ and
        # silence on a WRITE.
        #
        # THE SHAPE IS ALREADY USED TWO FUNCTIONS AWAY: approver
        # eligibility (_eligible_sub_write_indexes) branches to
        # authorize() for a create and check_access() otherwise, and
        # says reuse "means eligibility here cannot drift from
        # eligibility anywhere else". This is that, applied to the
        # proposer.
        #
        # RBAC IS RE-DECIDED HERE AND THAT IS DELIBERATE. It was
        # already settled upstream at propose_action() and is always
        # True by now; rbac_allowed is still passed in so the create
        # branch above can log it accurately. One dict lookup buys a
        # single place that decides, which is the point.
        if not check_access(
            self._adapter_mediator, user_record, self.roles,
            object_type, object_id, execute_action_id,
        ):
            raise PermissionError(f"{user_record.user_id!r} cannot modify this {object_type}")

    def _expected_current_values_for(self, operation: str, object_type: str, object_id: Any,
                                     changes: dict, action_type_name: str) -> dict:
        """What the row must still look like for this write to apply.

        Three operations, three answers. A DELETE expects nothing -- it
        goes through regardless of current values. An UPDATE reads
        every field it will change, so the lost-update check can
        confirm nobody moved it in between. A CREATE expects nothing
        either, but validates that its mutations set the id field and
        that the id agrees with the sub_write's own resolved object_id.
        """
        if operation == "delete":
            return {}
        if operation == "update":
            expected: dict = {}
            for adapter, resolved_type_config, group_changes in self._group_changes_by_storage(
                object_type, changes
            ):
                expected.update(
                    self._read_group_fields(object_type, object_id, adapter, resolved_type_config,
                                            group_changes)
                )
            return expected

        # create
        self._group_changes_by_storage(object_type, changes)
        id_field = self._adapter_mediator._type_schema(object_type)["id_field"]
        if id_field not in changes:
            raise ValueError(
                f"Create for {object_type!r} requires an explicit {id_field!r} value "
                f"in its own mutations -- auto-generated ids aren't supported"
            )
        if changes[id_field] != object_id:
            raise ValueError(
                f"Action {action_type_name!r}: sub_write's object_id resolved to "
                f"{object_id!r}, but its own mutations set {id_field!r} to "
                f"{changes[id_field]!r} -- these must match."
            )
        return {}

    def _drop_values_the_pipeline_produced(self, user_record: UserRecord, object_type: str,
                                            object_id: Any, changes: dict,
                                            source_values: dict, action_type_name: str) -> dict:
        """Removes fields whose "new" value is what the caller was SHOWN.

        THE FEEDBACK LOOP (R50), and it is the write-path half of
        CONCERN-3. Silver standardises on the way in -- NFC, trim,
        collapse whitespace (patch 337) -- so a source row holding
        `"  Ada   Okafor "` is SERVED as `"Ada Okafor"`. A form
        prefilled from the served value, saved by somebody who edited a
        DIFFERENT field, proposes `name = "Ada Okafor"`, and the write
        path puts that into the customer's own row. A transformation
        nobody chose, attributed to somebody who never typed it, and
        the original is gone.

        NOTHING PREVIOUSLY NOTICED. _expected_current_values_for()
        reads through _adapter_mediator, which is bound to the SOURCE,
        so the lost-update check compares source against source and
        passes. The proposed value was never compared against what the
        caller was shown.

        THE TEST IS "DIFFERENT FROM THE SOURCE, IDENTICAL TO THE
        SERVED VALUE". A field equal to the source is not an echo --
        it is a no-op, harmless, and left alone. A field equal to
        neither is a real edit and is kept.

        WHAT THIS COSTS SOMEBODY WHO MEANT IT: a caller who genuinely
        wants to set the source to the standardised form cannot, and
        that case is INDISTINGUISHABLE from the echo -- the bytes are
        identical. Preserving the customer's own data is the
        conservative reading of an ambiguity we cannot resolve, and
        the alternative silently destroys it. Stated here rather than
        discovered.

        DROPPED, NOT REFUSED. Refusing the whole action would block a
        legitimate edit to a neighbouring field, which is the common
        case -- the echo arrives alongside a real change, not instead
        of one.

        FAILS TO TODAY'S BEHAVIOUR, NOT OPEN. get_field() returns None
        for a field the caller may not read, and None is also a real
        value, so an unreadable field cannot be compared and is kept.
        That is the pre-R50 behaviour for that field and no weaker:
        this guard protects the customer's DATA, it is not an
        authorization gate, and MAC and RBAC already ran above.
        """
        kept = {}
        for field_name, proposed in changes.items():
            if field_name not in source_values or proposed == source_values[field_name]:
                kept[field_name] = proposed
                continue
            # What a caller reading this object would have been shown:
            # published gold, through the read mediator, with their own
            # grants applied.
            served = self.mediator.get_field(user_record, object_type, object_id, field_name)
            if served is not None and proposed == served:
                self.audit_log.log_echoed_value_not_written(
                    user_record.user_id, object_type, object_id, field_name
                )
                continue
            kept[field_name] = proposed

        if not kept:
            raise ValueError(
                f"Action {action_type_name!r} on {object_type} {object_id!r} would change "
                f"nothing: every value proposed is the one already shown to the caller. "
                f"The source holds a different form of it, which this refuses to overwrite."
            )
        return kept

    def _refuse_cross_compartment(self, user_record, action_type_name: str,
                                  action_def: dict, parameters: dict,
                                  sub_writes: list) -> None:
        """Refuses an action that would carry data across compartments.

        THE GAP THIS CLOSES. Every MAC check in this codebase compares
        an object to the USER; nothing compared two OBJECTS. So an
        analyst cleared for two compartments could read one and write
        the other, and every individual check passed.

        THE BELL-LAPADULA \\*-PROPERTY is the name for what was
        missing -- "no write down" -- and it is about the FLOW rather
        than about either end of it.

        THE READ SET IS THE OBJECT-REFERENCE PARAMETERS. Those are the
        objects the action was handed, and Foundry's model is the
        same: "an existing object whose primary key is derived from
        object reference parameters". An action can only carry what it
        was given.

        REFUSED AT PROPOSAL, not at execution. A write that cannot
        legally happen should not sit in an approval queue looking
        like a decision somebody could make.
        """
        read_labels = {}
        for name, definition in (action_def.get("parameters") or {}).items():
            if definition.get("type") not in (
                "object_reference", "object_reference_list",
            ):
                continue
            referenced = parameters.get(name)
            if referenced is None:
                continue
            object_type = definition.get("object_type")
            for object_id in (
                referenced if isinstance(referenced, list) else [referenced]
            ):
                read_labels[(object_type, object_id)] = (
                    self._adapter_mediator._get_security_value(
                        object_type, object_id,
                    )
                )

        write_labels = {
            (sub.object_type, sub.object_id):
                self._adapter_mediator._get_security_value(
                    sub.object_type, sub.object_id,
                )
            for sub in sub_writes
            if sub.operation != "create"
        }

        crossings = _compartment_crossings(read_labels, write_labels)
        if not crossings:
            return

        read_type, read_id, read_label, write_type, write_id, write_label = (
            crossings[0]
        )
        # LOGGED AS AN ACCESS DECISION, using the method that exists.
        # A first version called `log_write_refused` behind a hasattr
        # guard -- the method does not exist, and the guard was hiding
        # that rather than handling it.
        self.audit_log.log_access(
            user_record.user_id, write_type, write_id,
            # `execute:` BECAUSE THAT IS THE GRANT THIS ACTION NEEDED,
            # and the vocabulary check requires every verb the code
            # asks for to be one a deployment can actually write. A
            # first version used `refused:` and a test caught it: "a
            # deployment cannot write them, so those checks can never
            # pass". mac_allowed=False records WHY it was refused.
            f"execute:{action_type_name}", False, True,
        )
        raise CrossCompartmentWrite(
            f"This action would read {read_type} {read_id} (in "
            f"{read_label}) and write {write_type} {write_id} (in "
            f"{write_label}). Data may not cross a security compartment, "
            f"even when you can see both sides. Nothing has been written."
        )

    def propose_action(self, user_record: UserRecord, action_type_name: str, parameters: dict,
                       origin: Origin) -> PendingWrite:
        # Matches Palantir Foundry's own action-type model directly
        # (verified against their docs, not assumed): a NAMED,
        # independently-governed operation, not a generic CRUD verb.
        # The object(s) being acted on are always just PARAMETERS too
        # -- "an existing object whose primary key is derived from
        # object reference parameters," Palantir's own words -- never
        # a separate, out-of-band argument the way object_id used to
        # be here. See SubWrite's and core/ontology/action_types.py's
        # own docstrings for the full reasoning behind that change.
        #
        # RBAC is ACTION-level, deliberately NOT a field-grant hybrid --
        # one "execute:{action_type_name}" grant, not one write:{type}.
        # {field} grant per field the action's mutations happen to
        # touch, AS LONG AS every sub_write targets the SAME object
        # type. This is CLOSER to Palantir's real model and easier for
        # whoever is actually configuring roles to reason about ("this
        # role may perform this named business operation," not "this
        # role may touch these raw columns") -- but it means a role's
        # true field-level reach is now defined by whatever an action's
        # mutations happen to declare, not by an independent, per-field
        # decision. Editing an action's mutations later is therefore a
        # REAL grant-equivalent decision, not routine schema
        # maintenance -- every role already holding execute: on that
        # action silently gains whatever new mutation was added. Once
        # sub_writes spans more than one DISTINCT object type, that
        # risk stops being bounded to "new fields on the same type" --
        # see the cross-type RBAC check further below for how this is
        # actually contained.
        action_def = self.action_types.get(action_type_name)
        if action_def is None:
            raise ValueError(f"Unknown action_type: {action_type_name!r}")

        # AN ACTION MAY REFUSE TO BE STARTED BY A CONDITION.
        #
        # A DIFFERENT QUESTION FROM auto_execute: that one asks whether
        # a proposal needs confirming, this asks whether a trigger may
        # propose it AT ALL. An action can be both -- safe without
        # confirmation when a person asked, and never to be started by
        # something firing at 3am.
        #
        # REFUSED AT PROPOSAL, so it never reaches a queue looking
        # like a decision somebody could make.
        if origin == "automation" and action_def.get("automatable") is False:
            raise NotAutomatable(
                f"{action_type_name!r} declares automatable: false, so a "
                f"trigger may not propose it. A person can still run it."
            )

        execute_action_id = f"execute:{action_type_name}"
        rbac_allowed = authorize(user_record, self.roles, execute_action_id)
        if not rbac_allowed:
            # Logged ONCE here, with mac_allowed=None -- MAC never ran,
            # short-circuited before a real database query. Uses
            # action_type_name itself, not any object_type -- this
            # check is about whether the user may invoke this ACTION
            # at all, before WHICH object(s) it touches is even known;
            # every action, single- or multi-object, shares this same
            # first gate, and there is no single object_type to report
            # here regardless.
            self.audit_log.log_access(
                user_record.user_id, action_type_name, None, execute_action_id,
                mac_allowed=None, rbac_allowed=False,
            )
            raise PermissionError(f"{user_record.user_id!r} is not authorized for: {execute_action_id!r}")

        # Parameter validation -- MOVED before per-sub_write MAC below
        # (was after, back when object_id was a directly-supplied,
        # separate argument known independent of parameters). Every
        # sub_write's own identity now comes FROM parameters, so
        # parameters must be validated before any sub_write's object_id
        # can even be resolved, let alone MAC-checked. REQUIRED
        # parameters must be present; UNDECLARED ones are rejected
        # outright, not silently ignored -- "explicit and safe,"
        # matching this project's own consistent discipline.
        declared_params = action_def.get("parameters", {})
        for param_name, param_spec in declared_params.items():
            if param_spec.get("required") and param_name not in parameters:
                raise ValueError(f"Missing required parameter {param_name!r} for action {action_type_name!r}")
        unknown_params = set(parameters) - set(declared_params)
        if unknown_params:
            raise ValueError(
                f"Unknown parameter(s) for action {action_type_name!r}: {sorted(unknown_params)}"
            )

        sub_write_defs = action_def["sub_writes"]

        # Cross-type RBAC -- the OPTION B decision. execute: alone is
        # sufficient only when every sub_write targets the SAME object
        # type (unchanged from before sub_writes existed at all). The
        # moment sub_writes spans two or more DISTINCT types, every one
        # of those types additionally needs its own write:<Type>.
        # {field} grant, for each field that type's own mutations
        # touch -- checked here, before anything is resolved or
        # logged, same fail-closed timing as the execute: check above.
        # Deliberately no exemption for any "first" or "primary" type
        # -- sub_writes has no inherent ordering that could principled
        # single one out, and a role trusted with execute: on a
        # cross-type action has no more inherent reason to be trusted
        # with EVERY type it touches than with any one of them.
        affected_types = {sw["object_type"] for sw in sub_write_defs}
        if len(affected_types) > 1:
            for sw_def in sub_write_defs:
                for mutation in sw_def["mutations"]:
                    write_action_id = f"write:{sw_def['object_type']}.{mutation['set']['property']}"
                    if not authorize(user_record, self.roles, write_action_id):
                        raise PermissionError(
                            f"{user_record.user_id!r} is not authorized for: {write_action_id!r} "
                            f"(required because {action_type_name!r} touches more than one object type)"
                        )

        # Resolve, MAC-check, and validate EACH sub_write independently.
        resolved_sub_writes = []
        seen_object_refs: set[tuple[str, str]] = set()
        for sw_def in sub_write_defs:
            object_type = sw_def["object_type"]
            operation = sw_def["operation"]

            # The object's own identity, resolved FIRST, via the SAME
            # _resolve_mutation_value() vocabulary every mutation value
            # already uses -- see this method's own top-level comment
            # for why object_id is just an ordinary parameter now, not
            # a special case.
            resolved = self._resolve_mutation_value(sw_def["object_id"], parameters, user_record)

            # A LIST EXPANDS INTO ONE SUB-WRITE PER OBJECT. This is
            # the whole of "bulk": an action whose object_id comes
            # from an object_reference_list parameter touches every
            # object named, and each one goes through the SAME
            # per-object checks below -- authorization, submission
            # criteria, the duplicate guard. Nothing is skipped
            # because there are many.
            #
            # Foundry draws the line in the same place: a "bulk
            # action type" is one "using an object reference list
            # parameter", so it is a property of the ACTION rather
            # than a mode the UI switches into.
            #
            # STILL ONE ATOMIC BATCH. Forty objects means forty
            # writes that all succeed or all fail, which is what
            # makes a bulk action safe to approve as a unit -- a
            # half-applied bulk edit is the state nobody can
            # reason about.
            object_ids = resolved if isinstance(resolved, list) else [resolved]

            # A CEILING, because an atomic batch has no natural one.
            #
            # Forty objects all succeeding or all failing is the point.
            # Fifty thousand is the same promise made about a write
            # that will hold a lock for minutes, produce an audit entry
            # nobody can read, and present a reviewer with a diff they
            # cannot meaningfully approve. The atomicity that makes a
            # bulk action safe at small sizes is what makes it
            # dangerous at large ones.
            #
            # Foundry stops at the same number: actions "are
            # unavailable if the number of selected objects exceeds
            # 1000". Refused at PROPOSE time rather than at confirm, so
            # nobody assembles a selection they will not be allowed to
            # act on.
            if len(object_ids) > MAX_BULK_OBJECTS:
                raise ValueError(
                    f"Action {action_type_name!r} names {len(object_ids)} objects, and at most "
                    f"{MAX_BULK_OBJECTS} may be written in one action. Narrow the selection, or "
                    f"split it across several proposals."
                )

            for object_id in object_ids:

                # The FULL duplicate check, against REAL resolved ids --
                # the complement to core/ontology/action_types.py's own,
                # WEAKER, load-time-only structural check. Two DIFFERENT
                # object_id expressions (e.g. parameter.from_id and
                # parameter.to_id) could still resolve to the SAME real id
                # once real parameters arrive -- the schema-load check can
                # never catch that; only this, with real values in hand,
                # can.
                object_ref = (object_type, str(object_id))
                if object_ref in seen_object_refs:
                    raise ValueError(
                        f"Action {action_type_name!r}: two sub_writes both resolved to the "
                        f"identical {object_type} {object_id!r}"
                    )
                seen_object_refs.add(object_ref)

                self._authorize_sub_write(
                    user_record, object_type, object_id, operation, execute_action_id, rbac_allowed
                )

                # Submission criteria -- now PER SUB_WRITE, not per action;
                # see core/ontology/submission_criteria.py's own docstring
                # for why this stays a property of the write being
                # proposed, not a generic validation bolted onto "update"
                # itself. The "parameter" check kind still reads from the
                # action's own declared parameter names, shared across
                # every sub_write, not a per-sub_write namespace.
                criteria = sw_def.get("submission_criteria", [])
                if criteria:
                    current_state = self._read_current_state_for_criteria(object_type, object_id, criteria) \
                        if operation == "update" else None
                    evaluate_submission_criteria(criteria, current_state, parameters, user_record)

                # Resolve this sub_write's own declared mutations into a
                # concrete field-value dict -- this, not free-form model
                # input, is what actually gets written.
                # A DELETE HAS NO MUTATIONS. Validation has allowed that
                # since deletes were added -- a delete names an object, not
                # a change to it -- but this path still required the key,
                # so a delete action validated cleanly at load and raised
                # KeyError the moment an agent proposed one.
                #
                # Each half was tested and the SEAM between them was not,
                # which is what the end-to-end test that found this exists
                # for.
                changes = {
                    mutation["set"]["property"]: self._resolve_mutation_value(mutation["set"]["value"],
                                                                                parameters, user_record)
                    for mutation in (sw_def.get("mutations") or [])
                }

                # For "update," expected_current_values is built PER
                # STORAGE GROUP (same _group_changes_by_storage()
                # confirm_and_execute() itself uses) -- this is what makes
                # a multi-storage update possible at all; see write_log.py's
                # own module docstring for the full mechanism.
                expected_current_values = self._expected_current_values_for(
                    operation, object_type, object_id, changes, action_type_name
                )
                if operation == "update":
                    changes = self._drop_values_the_pipeline_produced(
                        user_record, object_type, object_id, changes,
                        expected_current_values, action_type_name,
                    )
                    expected_current_values = {
                        field: value for field, value in expected_current_values.items()
                        if field in changes
                    }
                resolved_sub_writes.append(
                    SubWrite(object_type, object_id, operation, changes, expected_current_values)
                )

        # AT PROPOSAL, so a value no field accepts never reaches a queue
        # looking like a decision somebody could make.
        self._refuse_constraint_violations(resolved_sub_writes)
        self._refuse_cross_compartment(
            user_record, action_type_name, action_def, parameters,
            resolved_sub_writes,
        )

        description = _describe_action(action_type_name, action_def, parameters)
        return PendingWrite(
            tuple(resolved_sub_writes), user_record.user_id, description, action_type_name,
            origin, datetime.now(UTC), self.generation,
            parameters=dict(parameters), proposer=user_record,
        )

    def _criteria_for(self, pending: PendingWrite) -> list[tuple[str, Any, list]]:
        """Each sub_write's criteria, from the CURRENT action definition.

        CURRENT, not the definition in force when the write was
        proposed, and that is the same choice step 6b already made
        about fields: the deployment's rules today are what governs a
        decision taken today. A write proposed before a four-eyes rule
        was added must still obey it.
        """
        action_def = self.action_types.get(pending.action_type_name) or {}
        declared = action_def.get("sub_writes") or []
        return [
            (sub_write.object_type, sub_write.object_id, (sw_def or {}).get("submission_criteria") or [])
            for sub_write, sw_def in zip(pending.sub_writes, declared, strict=False)
        ]

    def eligible_task_indexes(self, pending: PendingWrite, approver: UserRecord,
                               roles: dict) -> set[int]:
        """Which of a request's tasks this reviewer may decide.

        FOUNDRY SCOPES A REVIEWER TO WHAT THEY CAN REVIEW: "approve or
        reject all tasks in the request THAT YOU ARE ELIGIBLE TO
        REVIEW". This is that set.

        WHAT DIFFERS BETWEEN TASKS IS THE OBJECT, not the action. Every
        task in one request shares an action type, so the
        `execute:<ActionType>` grant is identical across all of them --
        it decides whether a reviewer may act on the REQUEST at all.
        MAC is what differs: a reviewer in one security partition may
        decide the tasks touching objects in it and not the others.

        check_access() is the existing primitive for exactly that
        question, combining MAC on the object with RBAC on the action,
        and reusing it means eligibility here cannot drift from
        eligibility anywhere else.

        A CREATE HAS NO OBJECT TO CHECK. There is nothing to read a
        security value from, so it falls back to the action grant
        alone -- the same answer the request-level check already gives.
        """
        eligible = set()
        for index, sub_write in enumerate(pending.sub_writes):
            if sub_write.operation == "create":
                if authorize(approver, roles, f"execute:{pending.action_type_name}"):
                    eligible.add(index)
                continue
            if check_access(
                self.mediator, approver, roles, sub_write.object_type,
                sub_write.object_id, f"execute:{pending.action_type_name}",
            ):
                eligible.add(index)
        return eligible

    def _check_approver_criteria(self, pending: PendingWrite, approver: UserRecord) -> None:
        """Re-evaluates submission criteria with the APPROVER acting.

        WHY AGAIN, when propose_action() already evaluated them: it
        evaluated them against the PROPOSER. A four-eyes rule is about
        the approver and says nothing at propose time -- there is no
        approver yet. Evaluating only once is why four-eyes could not
        be enforced at all before this.

        The proposer is threaded through so `proposer.<attribute>`
        resolves, which is what makes the rule unspoofable -- see
        submission_criteria.py on why a parameter cannot do this job.
        """
        for object_type, object_id, criteria in self._criteria_for(pending):
            if not criteria:
                continue
            self._refuse_criteria_this_write_cannot_answer(pending, criteria)
            current_state = self._read_current_state_for_criteria(
                object_type, object_id, criteria,
            )
            evaluate_submission_criteria(
                criteria, current_state, pending.parameters, approver,
                proposer=pending.proposer,
            )

    def _refuse_criteria_this_write_cannot_answer(self, pending: PendingWrite,
                                                   criteria: list) -> None:
        """Refuses a stored write a NEW parameter rule cannot be tested on.

        THE UNSTATED PRECONDITION (001's F-08), made concrete at the
        confirm path. A "parameter" criterion is silently SKIPPED when
        its field is absent from the call's parameters, and at PROPOSE
        time that is right: a rule about `amount` has nothing to say
        about an action never given an amount, and required-ness is
        validated before criteria are ever evaluated (propose_action,
        the "Missing required parameter" raise).

        AT CONFIRM THE ORDERING DOES NOT HOLD, because the two halves
        come from different moments. _criteria_for() deliberately reads
        the CURRENT action definition -- "a write proposed before a
        four-eyes rule was added must still obey it" -- while
        pending.parameters was captured under the definition in force
        when it was proposed. REPRODUCED before fixing:

            stored parameters : {'employee_id': 'e1'}
            new rule          : amount less_than 1000
            verdict           : PASSED -- silently skipped

            the same rule with `amount` supplied -> correctly refused

        So a rule added today is skipped precisely BECAUSE the write
        predates it, which is the exact opposite of what _criteria_for
        promises.

        NARROW ON PURPOSE: only a parameter the CURRENT definition
        declares `required: true` can be absent for this reason. An
        OPTIONAL parameter being absent is the legitimate case the skip
        was designed for and is indistinguishable from it, so it is
        left alone -- widening this would start inventing violations.

        REFUSES RATHER THAN SKIPS, following _fields_no_longer_declared
        and log_write_unapplyable: a stored write that cannot be judged
        under today's rules is re-proposed, not waved through. Fail
        closed is this project's posture everywhere else.
        """
        declared = (self.action_types.get(pending.action_type_name) or {}).get("parameters") or {}
        for criterion in criteria:
            if criterion.get("check") != "parameter":
                continue
            field_name = criterion.get("field")
            if field_name in pending.parameters:
                continue
            if not (declared.get(field_name) or {}).get("required"):
                # Optional and unsupplied: the skip's original, correct case.
                continue
            raise ValueError(
                f"This write was proposed before {field_name!r} became a required "
                f"parameter of {pending.action_type_name!r}, so the rule "
                f"{criterion.get('description') or field_name!r} cannot be checked "
                f"against it. Re-propose the action."
            )

    def confirm_and_execute(self, pending: PendingWrite, approved: bool,
                             approver: UserRecord | None = None) -> dict | None:
        # ALWAYS goes through _apply_batch() below, one sub_write or
        # many -- see this file's own AI-notes at the bottom, and
        # write_log.py's own MULTI-OBJECT BATCHES docstring section,
        # for why: uniform REPRESENTATION (a write_log_batches row
        # exists for every write, not just multi-object ones) is what
        # lets the CODE stay genuinely branch-free, the same way
        # _group_changes_by_storage() already lets a single-storage
        # object apply through the exact same loop as a multi-storage
        # one, with no special case for either.
        # STILL APPLICABLE? A pending write proposed under one
        # configuration can be confirmed under another -- the store
        # survives a reload, deliberately, because discarding proposals
        # on every configuration change would make an approvals inbox
        # useless. So the ontology it was written against may no longer
        # describe the fields it targets.
        #
        # CHECKED AT CONFIRM TIME rather than only at apply time,
        # because the failure would otherwise arrive AFTER a human
        # approved it: the approver would be told their decision was
        # accepted and then that it could not be carried out, which is
        # the worst order to learn those two things in.
        #
        # HOT_RELOAD_PLAN.md step 6 also wants these marked unapplyable
        # at RELOAD time, so an inbox never shows a proposal that
        # cannot be approved. That is a better experience and it is not
        # the correctness half -- a write must be refused whether or
        # not anything got round to marking it, and this is the refusal
        # that cannot be skipped.
        if approved and approver is not None:
            # BEFORE the unapplyable check and before anything is
            # written: an approver who is not permitted to approve
            # should learn that, not learn about a schema change they
            # cannot act on either way.
            self._check_approver_criteria(pending, approver)

        if approved:
            # AGAIN AT CONFIRM, against the CURRENT schema. A proposal
            # made before a constraint existed must not slip through by
            # being approved after it -- re-evaluated at the point of use.
            self._refuse_constraint_violations(pending.sub_writes)
            unapplyable = self._fields_no_longer_declared(pending)
            if unapplyable:
                self.audit_log.log_write_unapplyable(
                    pending.user_id, pending.description,
                    pending.proposed_under_generation, self.generation, unapplyable,
                )
                raise ValueError(
                    f"This write can no longer be applied: it changes "
                    f"{', '.join(unapplyable)}, which the ontology no longer "
                    f"declares. It was proposed under configuration generation "
                    f"{pending.proposed_under_generation} and the deployment is now "
                    f"on {self.generation}. Nothing has been written."
                )
            # AND AGAINST THE CURRENT MAC (004-7). Every other check
            # here already re-runs at the point of use; the security
            # value of the OBJECTS did not, so a proposal outlived the
            # authority it was made under.
            #
            # REPRODUCED: propose while a ticket is us-west, move the
            # ticket to us-east, and the SAME action is refused when
            # proposed fresh while the older proposal still applies. A
            # write nobody may make now is not made safe by having been
            # askable earlier.
            #
            # AFTER the undeclared-field check, deliberately. A write
            # whose SECURITY FIELD has been removed from the ontology
            # cannot have its reach evaluated at all, and that write
            # has a better, more specific refusal waiting above --
            # three existing tests found this order by failing with a
            # KeyError when it was the other way round.
            self._refuse_writes_outside_current_mac(pending, approver)

        request_id = str(uuid.uuid4())
        self.audit_log.log_pre(
            request_id, pending.user_id, pending.description, f"write:{pending.action_type_name}",
            {
                # An explicit, computed field stating what happened,
                # not something a reader has to infer by counting --
                # same "explicit signal, not implicit inference"
                # principle log_access() already follows by reporting
                # mac_allowed/rbac_allowed independently rather than
                # only a combined allow/deny bit.
                "sub_write_count": len(pending.sub_writes),
                # Provenance, recorded here because the audit log is
                # the only place it survives the process. A reader
                # asking "did a person choose this, or did the agent"
                # otherwise has to infer it from which route happened
                # to be hit, which the log does not record.
                "origin": pending.origin,
                "proposed_at": pending.proposed_at.isoformat(),
                # The configuration in force when this was PROPOSED.
                # The audit log stamps the generation in force when it
                # is APPLIED, so an entry carrying two different
                # numbers is a write that outlived a configuration
                # change -- which is exactly the thing an approvals
                # inbox makes ordinary, and which nothing could
                # currently detect. Recorded now; what to DO about a
                # mismatch is a later step of HOT_RELOAD_PLAN.md.
                "proposed_under_generation": pending.proposed_under_generation,
                # WHO APPROVED IT, which this entry recorded nowhere.
                # user_id above is the PROPOSER -- correct, since the
                # write is theirs -- so a four-eyes deployment could
                # enforce that two different people were involved and
                # then not be able to PROVE it afterwards. The control
                # existed; the evidence did not.
                #
                # None when no approver was supplied, which is honest
                # rather than tidy: scripts/run_deployment.py confirms
                # without one, and writing the proposer into this field
                # would make a single-party write look like a reviewed
                # one in the log.
                "approved_by": approver.user_id if approver is not None else None,
                # THE PAIR IS THE EVIDENCE, so it is computed here
                # rather than left to a reader to derive. Someone
                # auditing a four-eyes control asks one question --
                # were these the same person -- and a log that makes
                # them compare two fields invites the comparison being
                # done wrong, or not at all.
                "self_approved": (
                    approver is not None and approver.user_id == pending.user_id
                ),
                "sub_writes": [
                    {"object_type": sw.object_type, "object_id": sw.object_id, "changes": sw.changes}
                    for sw in pending.sub_writes
                ],
            },
            approved,
        )

        if not approved:
            return None

        object_ids = self._apply_batch(pending)
        self.audit_log.log_post(request_id, "success", object_ids)
        return {"status": "written", "object_ids": object_ids}

    def fields_no_longer_declared(self, pending: PendingWrite) -> list[str]:
        """Public name for the same question the confirm path asks.

        THE INBOX AND THE CONFIRM PATH MUST AGREE. A listing that
        computed applicability its own way could show a write as
        approvable that confirm then refuses -- or, worse, mark one
        unapplyable that would have worked, so nobody tries.

        One function, two callers, no second opinion.
        """
        return self._fields_no_longer_declared(pending)

    def _refuse_writes_outside_current_mac(self, pending: PendingWrite,
                                            approver: UserRecord | None) -> None:
        """Every object this write touches is still reachable NOW.

        CHECKED AGAINST THE PROPOSER, not the approver, and that
        choice is the whole design of this function.

        I FIRST CHECKED THE APPROVER -- they are live, they are
        deciding now, and Foundry requires the submitter to see what
        they edit. Three existing tests failed, and reading them
        settled it: the same fixture asserts that `bob` CANNOT PROPOSE
        against auth_001 because he is in another org ("MAC boundary
        test"), while three four-eyes tests have bob APPROVING a write
        to that same object. Requiring the approver to reach the
        object would narrow who may approve -- a cross-org supervisor
        could no longer sign anything off -- and that is a policy
        decision for the deployment's owner, not a bug fix. It is
        recorded for them instead.

        SO: the write is re-checked against the authority it was
        PROPOSED under. That closes what 004-7 actually reproduced --
        an object moving out of reach between propose and confirm --
        and leaves four-eyes exactly as it was.

        AND ITS LIMIT, stated because the next reader will ask: this
        uses the proposer's record as captured at propose time, so it
        catches the OBJECT moving, not the PROPOSER's own clearance
        being revoked. Catching that needs a user-directory lookup
        this layer does not have. Recorded as such rather than implied
        by a reassuring name.

        CREATES ARE SKIPPED for the same reason propose skips them:
        the object does not exist yet, so it has no security value to
        be outside of.
        """
        proposer = pending.proposer
        if proposer is None or proposer.security_value is None:
            return
        for sub_write in pending.sub_writes:
            if getattr(sub_write, "operation", None) == "create":
                continue
            object_type = sub_write.object_type
            object_id = sub_write.object_id
            # ONLY WHERE THE OBJECT HAS A SECURITY VALUE AT ALL.
            # `None` means the row is gone or never had one -- a
            # DELETED object, most often -- and that is not "in another
            # compartment", it is "not there". Tests for deleting and
            # then re-writing an object found this: refusing on a
            # missing value blocked a write whose whole purpose was to
            # bring the object back, which no security rule intends.
            #
            # The narrow claim is the true one: a write is refused when
            # the object has MOVED OUT of the proposer's reach.
            current = self._adapter_mediator._get_security_value(object_type, object_id)
            if current is None or current == proposer.security_value:
                continue
            self.audit_log.log_access(
                proposer.user_id, object_type, object_id,
                f"write:{pending.action_type_name}", False, True,
            )
            raise PermissionError(
                f"This write can no longer be applied: {object_type} "
                f"{object_id!r} is no longer within reach of "
                f"{proposer.user_id!r}, who proposed it. It was proposed "
                f"under configuration generation "
                f"{pending.proposed_under_generation}; nothing has been written."
            )

    def _refuse_constraint_violations(self, sub_writes) -> None:
        """Raises if any change breaks its field's declared constraints.

        EVERY VIOLATION AT ONCE, not the first. Somebody fixing a form
        should not discover the second problem only after fixing the
        first.

        A type or field that no longer exists is not this check's
        concern -- _fields_no_longer_declared reports it, with its own
        message.
        """
        from core.ontology.constraints import violation

        problems = []
        for sub_write in sub_writes:
            try:
                declared = self._adapter_mediator._type_schema(sub_write.object_type)
            except (KeyError, ValueError):
                continue
            fields = declared.get("fields") or {}
            for field_name, value in sub_write.changes.items():
                if field_name not in fields:
                    continue
                reason = violation(fields[field_name], value)
                if reason is not None:
                    problems.append(f"{sub_write.object_type}.{field_name}: {reason}")
        if problems:
            raise ConstraintViolation("; ".join(problems))

    def _fields_no_longer_declared(self, pending: PendingWrite) -> list[str]:
        """Fields this write targets that the current ontology lacks.

        Returned as "Type.field" strings because that is what an
        operator greps ontology_schema.yaml for -- a bare field name
        sends them to the wrong declaration when two types share one.

        AN UNKNOWN OBJECT TYPE COUNTS TOO, and is the sharper case: a
        type removed entirely takes every field with it, and reporting
        only "the type is gone" would leave the approver guessing which
        of their changes were affected.
        """
        missing: list[str] = []
        for sub_write in pending.sub_writes:
            try:
                declared = self._adapter_mediator._type_schema(sub_write.object_type)
            except (KeyError, ValueError):
                missing.extend(
                    f"{sub_write.object_type}.{field}" for field in sub_write.changes
                )
                continue
            # THE ID FIELD IS DECLARED SEPARATELY, not inside `fields`,
            # and a create legitimately sets it. Found by five existing
            # tests: without this, every create was refused as targeting
            # an undeclared field, and the message said so while
            # reporting the SAME generation on both sides -- which is
            # itself the tell that nothing had changed and the check was
            # simply wrong.
            declared_names = set(declared.get("fields", {}))
            id_field = declared.get("id_field")
            if id_field is not None:
                declared_names.add(id_field)
            missing.extend(
                f"{sub_write.object_type}.{field}"
                for field in sub_write.changes if field not in declared_names
            )
        return missing

    def _apply_batch(self, pending: PendingWrite) -> list:
        # THE actual atomicity boundary for the WHOLE write, one
        # sub_write or many -- see write_log.py's own MULTI-OBJECT
        # BATCHES docstring section for the full mechanism this
        # implements: log the batch's COMPLETE, already-resolved intent
        # FIRST (trivially atomic, one INSERT, regardless of how many
        # sub_writes it describes), THEN apply each sub_write's own
        # share SEQUENTIALLY, in the batch's own declared LIST order
        # (referential correctness -- a sub_write creating an object
        # must apply before another sub_write that references it),
        # THEN mark the whole batch applied.
        #
        # Locks for EVERY object in this batch, acquired ONCE, up
        # front, in SORTED order (deadlock avoidance -- see
        # DataMediator._locks_for_objects()'s own docstring), held for
        # the WHOLE sequence, released together at the end -- NOT
        # acquired per-sub_write inside the loop below. This is why
        # _apply_one_update()/_apply_one_create() below no longer
        # acquire their own lock the way the pre-batch
        # _apply_update_via_log()/_apply_create_via_log() used to:
        # threading.Lock is not reentrant, so acquiring the SAME
        # object's lock twice from the same thread (once here, once
        # again inside a per-sub_write helper) would deadlock outright,
        # not just be redundant.
        object_refs = [(sw.object_type, sw.object_id) for sw in pending.sub_writes]
        with self._adapter_mediator._locks_for_objects(object_refs):
            batch_id = self.write_log.log_pending_batch(
                [
                    {
                        "object_type": sw.object_type, "object_id": sw.object_id, "operation": sw.operation,
                        "changes": sw.changes, "expected_current_values": sw.expected_current_values,
                    }
                    for sw in pending.sub_writes
                ],
                pending.user_id, pending.description,
            )

            object_ids: list[Any] = []
            try:
                for sub_write in pending.sub_writes:
                    if sub_write.operation == "delete":
                        object_ids.append(
                            self._apply_one_delete(
                                sub_write, batch_id, pending.user_id, pending.description
                            )
                        )
                    elif sub_write.operation == "update":
                        object_ids.append(
                            self._apply_one_update(
                                sub_write, batch_id, pending.user_id, pending.description,
                                batch_already_committed=bool(object_ids),
                            )
                        )
                    else:
                        object_ids.append(
                            self._apply_one_create(sub_write, batch_id, pending.user_id, pending.description)
                        )
            except Exception:
                # A REAL, confirmed bug this closes, found by running two
                # genuinely concurrent confirm_and_execute() calls against
                # the same account for the first time (see tests/unit/
                # test_write_path_concurrency.py).
                #
                # The common cause is the optimistic-concurrency check
                # correctly REJECTING this write because another caller
                # changed the object first. That rejection is right. What
                # was wrong is what it left behind: the batch was already
                # logged as pending, so the exception propagated with the
                # batch still marked pending forever.
                #
                # That is not a cosmetic leak. resume_pending_writes()
                # runs unguarded at startup (api/app.py's own create_app())
                # and would find this batch, try to re-apply it, hit the
                # SAME stale-value check, and raise -- so a single rejected
                # concurrent write would prevent the server from starting
                # again. Confirmed directly, not reasoned about.
                #
                # Marking it applied is the correct resolution when NOTHING
                # applied: there is genuinely nothing for recovery to
                # finish. A PARTIAL failure is deliberately left pending
                # instead -- that is exactly the state crash recovery
                # exists to reconcile, and abandoning it would strand a
                # half-written batch.
                if not object_ids:
                    self.write_log.mark_batch_applied(batch_id)
                raise

            # INVARIANT: a batch is only marked applied when every one
            # of its sub-writes produced a real object id. If these ever
            # diverge, the batch is being recorded as complete while
            # part of it never ran -- the exact corruption Point 2 of
            # the machinery audit found and fixed, where crash recovery
            # then skips a write that never happened. Asserted rather
            # than commented because a silent divergence here is
            # unrecoverable: once marked applied, nothing ever revisits
            # it.
            assert len(object_ids) == len(pending.sub_writes) and all(
                object_id is not None for object_id in object_ids
            ), (
                f"batch {batch_id} marking applied with {len(object_ids)} of "
                f"{len(pending.sub_writes)} sub-writes done, ids={object_ids}"
            )
            self.write_log.mark_batch_applied(batch_id)

        return object_ids

    def _apply_one_update(self, sub_write: SubWrite, batch_id: str, user_id: str, description: str,
                           batch_already_committed: bool = False) -> Any:
        # ONE sub_write's own share of a (possibly multi-object) batch
        # -- see _apply_batch() above for the locking and batch-logging
        # this is always called from within, and for why this no
        # longer acquires its own per-object lock the way the pre-
        # batch _apply_update_via_log() used to. Logs this ONE sub_
        # write's own write_log row, batch_id set, THEN applies each
        # storage's own share of the mutations SEQUENTIALLY (same
        # _group_changes_by_storage() mechanism as before -- a single-
        # group `groups` list is simply the degenerate case), THEN
        # marks this row applied.
        log_id = self.write_log.log_pending_update(
            sub_write.object_type, sub_write.object_id,
            sub_write.changes, sub_write.expected_current_values,
            user_id, description, batch_id=batch_id,
        )

        groups = self._group_changes_by_storage(sub_write.object_type, sub_write.changes)
        # Tracks whether any storage group has already COMMITTED, which
        # decides what a later failure means: nothing applied yet is a
        # clean rejection to abandon, whereas a partially-applied entry
        # must stay pending for crash recovery to reconcile.
        applied_groups = 0
        for adapter, resolved_type_config, group_changes in groups:
            group_expected = {
                field_name: sub_write.expected_current_values[field_name]
                for field_name in group_changes
            }
            success = self._write_fields_with_limiter(
                sub_write.object_type, sub_write.object_id, adapter, resolved_type_config,
                group_changes, group_expected,
            )
            if not success:
                # NOTHING in this entry committed, so the log row is
                # abandoned rather than left pending. Without this, a
                # rejected write leaves a row that get_field()'s own
                # write-log masking keeps reporting as the object's
                # value -- a read showing a number that was never
                # written, indefinitely. Found by running two genuinely
                # concurrent writes for the first time (see tests/unit/
                # test_write_path_concurrency.py); previously recorded
                # as a known limitation, now closed for the case where
                # it is unambiguously safe to close.
                #
                # DELIBERATELY only when applied_groups is empty. If an
                # EARLIER group already committed, this entry describes
                # a genuinely half-applied write, and that is precisely
                # what crash recovery exists to reconcile -- abandoning
                # it would strand the applied half with no record.
                # Abandoned ONLY when this write changed nothing AND
                # nothing earlier in the same batch did either. A
                # multi-object action whose FIRST sub-write already
                # committed is genuinely half-applied: marking this row
                # applied would tell crash recovery there is nothing to
                # reconcile, stranding the mismatch permanently and
                # leaving get_field() masking a value that will never
                # exist. That state must stay pending -- see
                # _apply_batch()'s own handling.
                if not applied_groups and not batch_already_committed:
                    # ABANDONED, WHICH IS WHAT THIS COMMENT HAS SAID
                    # ALL ALONG (PA001-A3). It called mark_applied,
                    # and `applied` is exactly what the overlay,
                    # edit_history and edits_touching_field read -- so
                    # a REFUSED write was served as the object's
                    # value. Measured: the database held 900, the
                    # ontology reported 800.
                    self.write_log.mark_abandoned(log_id)
                raise ValueError(
                    f"{sub_write.object_type} {sub_write.object_id!r} changed since this "
                    f"write was proposed -- refresh and retry"
                )
            applied_groups += 1

        # INVARIANT: every storage group committed before this row is
        # marked applied. An MDO object spans several physical tables,
        # and marking the row applied with only some of them written
        # would leave get_field() reporting the unwritten ones as
        # updated -- a read showing a value that does not exist, with
        # nothing left pending for recovery to notice.
        assert applied_groups == len(groups), (
            f"{sub_write.object_type} {sub_write.object_id!r}: marking applied with "
            f"{applied_groups} of {len(groups)} storage groups written"
        )
        self.write_log.mark_applied(log_id)

        # LAST EDIT WINS: a write after a delete makes the object
        # visible again, so the derived index must drop it -- the same
        # rule Foundry's own indexing uses ("most recent update wins").
        # Unconditional rather than guarded by a lookup: clearing an
        # object that was never deleted is a no-op, and a lookup on
        # every write would cost more than the clear it avoids.
        self.write_log.clear_delete(sub_write.object_type, sub_write.object_id)
        return sub_write.object_id

    def _apply_one_delete(self, sub_write: SubWrite, batch_id: str, user_id: str,
                           description: str) -> Any:
        """Records a delete. Writes NOTHING to the customer's database.

        Following Foundry directly: a delete there is an EDIT, written
        to the writeback layer rather than the backing datasource, so
        "users have access to both the original data and the edited
        data." Their resolution rule is that when an object's latest
        edit is a delete it "is not visible in the ontology, regardless
        of whether any corresponding row is in one of the data
        sources."

        Three real consequences follow, and all of them are why this is
        the right model here rather than a compromise:
          - Elysium's external read-only guarantee stays intact. We
            never destroy a row we do not own.
          - The delete is REVERSIBLE. A later create for the same id
            wins, because the read path takes the latest applied
            operation.
          - Crash recovery is trivial where a destructive delete would
            be genuinely ambiguous. A missing row cannot tell you
            whether YOUR delete succeeded, someone else's did, or it
            never existed -- but this record lives in storage this
            project owns and can simply be read.

        THREE STEPS, IN THIS ORDER: the pending log entry, the index row,
        then the entry marked applied. (This said there was "no second
        step that could fail partway". There was -- the index row -- and
        001's F-27 found the window: marked applied FIRST, a crash before
        the index row left an applied delete that resume SKIPS, and an
        object that stayed visible with nothing pending to fix it.)
        """
        log_id = self.write_log.log_pending_update(
            sub_write.object_type, sub_write.object_id,
            {}, sub_write.expected_current_values,
            user_id, description, batch_id=batch_id, operation="delete",
        )

        # The DERIVED INDEX, updated as part of applying the delete.
        # Reads consult this rather than resolving deleted-ness by
        # scanning the log, which cost 47.2 ms per search at 55,000
        # log rows and grew with edit history forever.
        #
        # The log entry is written FIRST, still -- an index row always
        # has a log record behind it. What moved is MARKING it applied,
        # to last: a crash anywhere before that leaves a PENDING entry,
        # which _resume_one_delete_entry finishes. (The old comment said
        # rebuild_deleted_index() would recover a stale index; nothing
        # calls it -- 001's F-28.)
        self.write_log.record_delete(
            sub_write.object_type, sub_write.object_id, log_id
        )
        self.write_log.mark_applied(log_id)
        return sub_write.object_id

    def _apply_one_create(self, sub_write: SubWrite, batch_id: str, user_id: str, description: str) -> Any:
        # THE create-side counterpart to _apply_one_update() above --
        # see write_log.py's own module docstring for the shared
        # mechanism, and _apply_batch() above for the locking and
        # batch-logging this is always called from within. Requires
        # sub_write.changes to already include the type's own id_field,
        # explicitly -- propose_action() enforces this upfront; matches
        # Palantir Foundry's own MDO requirement that an object's
        # primary key already exist, matching, in every backing
        # datasource (verified directly, not assumed -- see
        # https://www.palantir.com/docs/foundry/object-permissioning/multi-datasource-objects).
        id_field = self._adapter_mediator._type_schema(sub_write.object_type)["id_field"]
        log_id = self.write_log.log_pending_create(
            sub_write.object_type, sub_write.object_id,
            sub_write.changes, user_id, description, batch_id=batch_id,
        )

        groups = self._group_changes_by_storage(sub_write.object_type, sub_write.changes)
        for adapter, resolved_type_config, group_changes in groups:
            # Every group's own row needs the id as one of its actual
            # inserted columns -- unlike update, create_object() has no
            # separate object_id parameter for a WHERE clause; the id
            # is just another field being inserted, into EVERY
            # storage, not just whichever ONE group's mutations
            # happened to place it in naturally (a no-op overwrite for
            # that one group, a real injection for every other).
            group_with_id = {**group_changes, id_field: sub_write.object_id}
            self._create_object_with_limiter(sub_write.object_type, adapter, resolved_type_config, group_with_id)

        self.write_log.mark_applied(log_id)
        return sub_write.object_id
