# Simplifying access control without weakening it

Researched and audited September 22, after the owner asked whether
there are better ways -- or better defaults -- to secure sensitive
data while reducing what an administrator has to do.

---

# Part 1. What Elysium does today (AUDITED, not remembered)

## 1.1 Two mechanisms, and only one of them is per field

  MAC, and it is ROW-LEVEL ONLY. policy.yaml declares ONE
  `security_attribute` ("region" in the shipped deployment). Each user
  carries a value for it; each object type declares the field whose
  value must match, directly or through a via_field chain. The check
  itself is one line:

      security_value is not None and security_value == user_value

  An exact match on a single attribute. There is NO lattice, no
  hierarchy, no per-FIELD classification. MAC decides WHICH OBJECTS a
  person may see, never which properties.

  RBAC, and it IS per field. A role holds `allowed_actions`, a flat
  list of strings: `read:Customer`, `read:Customer.email`,
  `read:Transaction.amount`. A field is visible only with its OWN
  grant; the id_field is no exception. `read:` implies `discover:`,
  which is the only implication in the system.

## 1.2 The burden, counted rather than asserted

The shipped ontology has 2 types and 11 grantable names, and the
customer_service role enumerates 14 grants. Extrapolated honestly:

    10 types x 15 fields   ->    160 grant strings PER ROLE
    50 types x 20 fields   ->  1,050 grant strings PER ROLE
   120 types x 25 fields   ->  3,120 grant strings PER ROLE

Every one hand-written, per role, per deployment. Add a property to a
type and every role that should see it needs editing. THAT is the
administration cost, and it is the thing worth attacking.

## 1.3 What is already better than the precedent, and must not be lost

AN OBJECT TYPE CANNOT LOAD WITHOUT A SECURITY DECLARATION. Validation
refuses a type whose `security` declares neither `field` nor
`via_field`. Both lakehouse vendors default to UNPROTECTED-until-
tagged; Elysium is deny-by-default STRUCTURALLY, at load. Every
proposal below keeps that.

---

# Part 2. The precedent: classify the data, not the grants

Both major lakehouse vendors shipped the same answer within a year of
each other.

DATABRICKS: ABAC policies "control access based on the attributes of
the data, so a single policy can cover many matching tables instead of
each one being configured individually". Attributes are GOVERNED TAGS
-- account-level key/value pairs like `sensitivity:confidential` or
`pii:ssn` -- applied to catalogs, schemas, tables and columns, which
"inherit from parent to child objects".

SNOWFLAKE: attach the masking policy TO A TAG, then tag the column or
schema; tag inheritance then "protects all table and view columns in
the schema whose data types match".

AND THE RECOMMENDATION THAT MATTERS MOST: "Data creators do not need
to configure any access controls if policies are set at higher levels,
which Databricks recommends."

---

# Part 3. The proposal

## 3.1 Grant by TAG, not by name

Declare a small vocabulary -- `pii`, `financial`, `internal`,
`restricted` -- and tag FIELDS with it. A role then grants
`read:tag:pii` instead of enumerating every field that is PII.

    customer_service:
      allowed_actions:
        - read:tag:internal
        - read:tag:financial
        # and nothing per-field

The 1,050 strings become a handful. Adding a property to a type grants
nothing new by accident: it is unreadable until tagged, which is the
deny-by-default behaviour we already have, now at field level.

## 3.2 Inherit from the type; declare only the exceptions

Precedent: securables "inherit tags from their parent catalog or
schema". Ours: a field inherits its object type's tags unless it
declares its own. An administrator classifies the TYPE, then marks the
two fields that are more sensitive than the rest.

## 3.3 PROPAGATE ALONG LINEAGE -- the piece Elysium can do now and
     could not before

Snowflake lets a tag "be propagated to downstream objects ... when the
downstream object depends on a tagged object", and the policy then
protects those automatically.

ELYSIUM JUST BUILT THE LINEAGE THIS NEEDS (patch 340, and gold's
conform). A gold property derived from a silver column derived from a
classified source column INHERITS THAT CLASSIFICATION, with no second
act of administration.

This is not only convenience. The classic leak is derived data that
quietly lost its classification on the way -- which is exactly the
risk gold created (OPEN_RISKS.md item 2). Propagation closes it by
construction rather than by vigilance.

## 3.4 A scanner that PROPOSES tags, never applies them

Databricks ships automatic classification for PII using classifiers
and models. Ours should propose: a field named `email` holding things
shaped like addresses is probably `pii`. It writes a proposal an
administrator accepts -- the same rule as the pipeline builder, where
the machine proposes and a person decides.

## 3.5 Keep MAC exactly as it is, and do not let tags near it

MAC answers WHICH OBJECTS; tags answer WHICH PROPERTIES. They are
different questions and must stay different mechanisms. A tag must
never be able to widen MAC, and MAC must never be expressible as a
tag: the moment "clearance" becomes a tag somebody can apply, the
Bell-LaPadula property this system was built on stops holding.

---

# Part 4. The three warnings the same research carries

## 4.1 Taxonomy overlap needs a stated conflict rule

The documented failure is "designing a governed-tag taxonomy that
avoids ambiguous overlaps" and "preventing conflicts when several
policies cover the same object".

  THE RULE: MOST RESTRICTIVE WINS, stated in the file and tested, not
  emergent from evaluation order. A field carrying `internal` and
  `pii` requires the grant for `pii`.

## 4.2 Who may APPLY a tag is its own permission

Databricks gives governed tags their own permissions controlling who
can apply which. Without that, tagging is a back door: anybody who can
retag a field can declassify it. In Elysium this is a new action --
`classify:` -- and it is NOT implied by `manage:users`.

## 4.3 The pipeline sees everything, and that has to be said out loud

Their own guidance flags "planning pipeline service-principal
exemptions without overexposing data". Elysium's sync reads sources
directly and necessarily sees every value, tagged or not. That is the
same trust boundary as OPEN_RISKS.md item 2, now with a second reason
to write it into INSTALL.md rather than leave it implied.

---

# Part 5. What this does NOT change

  - MAC stays a single attribute, exact match, refusing on absence.
  - Validation still refuses a type with no security declaration.
  - `read:` still implies `discover:`.
  - Per-field grants REMAIN VALID: a deployment that wants to
    enumerate can, and existing policy files keep working. Tags are an
    additional way to say the same thing, not a replacement -- which
    is what makes this adoptable rather than a migration.

# Part 6. The order to build it

  1. TAGS AS METADATA ONLY: declare them, tag fields, show them in the
     UI. Nothing enforces yet -- so nothing can break.
  2. `read:tag:X` GRANTS, evaluated beside the existing per-field
     grants, most-restrictive-wins. Tested with a control that removes
     the tag check and proves a test fails.
  3. INHERITANCE from type to field.
  4. PROPAGATION along lineage, with a report showing what inherited
     what -- an administrator must be able to SEE a classification
     that arrived by derivation, or it is magic.
  5. THE SCANNER, proposing only.
  6. `classify:` as its own permission, before any of this is exposed
     in an editing UI.
