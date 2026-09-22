# Writing configuration from the UI, and owning the UI kit

Two directions from the owner, September 22. Both measured before
being answered.

---

# Part 1. UI edits reflected down into the YAML

The owner: edits made in the web UI should be reflected into the YAML
files they change, so outside programs -- and Elysium's own LLMs --
can read the configuration.

## Why this is not obvious: the files are mostly COMMENTS

  deployment/etc/config.yaml            104 comment lines of 127
  deployment/etc/ontology_schema.yaml    90 comment lines of 162

The explanation IS the file. A writer that drops comments would strip
the reasoning out of the most-read documents in the deployment.

## Measured, on the real files

  PyYAML (what the codebase has today, safe_dump):
      comments kept 0 of 104, and 0 of 90.  It destroys all of them.

  ruamel.yaml in round-trip mode:
      comments kept 104 of 104, and 90 of 90 --
      and with indent(mapping=2, sequence=4, offset=2) and a wide
      line width, the round trip is BYTE-IDENTICAL to both shipped
      files.

Byte-identical matters more than it sounds: it means a UI edit
rewrites ONLY the lines it changed. The diff an operator reviews is
the change, not a reformatting of the whole file, and version control
stays useful.

## So the design is: YAML STAYS THE SOURCE OF TRUTH

The UI does not own the configuration and does not keep a second copy
of it in a database. It edits the files, and everything that reads
them today -- the loader, an operator with an editor, an outside
program, the internal agent -- keeps reading exactly the same thing.

## What must hold, and why each one is real

  - VALIDATE BEFORE WRITING. The proposed content goes through the
    SAME validation the loader runs at startup. A file that would not
    load must never reach the disk: the failure mode is a deployment
    that cannot start.
  - COMPARE AND SET. Refuse the write if the file changed on disk
    since the UI read it. An operator editing by hand and the UI
    writing must not silently clobber each other.
  - THE READ-ONLY PANEL'S REASON STANDS. DeploymentConfig says today
    that nothing is editable because "runtime config editing needs a
    per-request snapshot first, or a change mid-flight leaves one
    request disagreeing with itself". That is still true -- and it is
    already solved for reloads: a write produces a NEW GENERATION,
    recorded in config_history, adopted at an epoch boundary, with
    rollback. Writes take that path, not a live mutation.
  - NO SECRETS EVER WRITTEN. Credentials live outside these files and
    stay there. The UI must not be able to put one in a file that is
    read by everything and committed to git.
  - AN AUDIT ENTRY PER WRITE, naming who and what: configuration is
    the thing an attacker changes to make everything else permissible.

## What it gives the internal LLM

The agent already reads the ontology to know what it may search. With
writes reflected into the same files, what an admin changed in the UI
is visible to the agent through the ordinary configuration it already
consumes -- no second representation, and no chance of the two
disagreeing.

---

# Part 2. Moving off Blueprint

The owner: less dependence on a single company's library, since they
could cut it off and strand us -- and perhaps a better, more featured
library instead.

## First, the risk is not what it looks like

Blueprint is APACHE-2.0, at 6.18.0 here. Nobody can revoke a licence
already granted: the code we have stays usable forever, and could be
forked. THE REAL RISK IS ABANDONMENT -- no fixes when React moves, no
security patches, no new browser quirks handled -- plus being tied to
one company's design language.

That changes the answer. Guarding against abandonment does not mean
finding a bigger library; it means owning the parts we use.

## Measured: the coupling is shallow

  49 import sites, 22 distinct components.
  Button 62, Tag 42, Callout 28, InputGroup 19, FormGroup 17,
  HTMLTable 12, HTMLSelect 7, Spinner 6, NonIdealState 5, Card 5,
  Menu/MenuItem 8, Dialog 3, Checkbox 3, Popover 2, NumericInput 2,
  Tab/Tabs 3, TextArea 1, Switch 1, Icon 1, Alert 1.

The hard parts of a component library -- virtualised grids, date
pickers, comboboxes, drag-and-drop -- are not used at all. Most of
what Blueprint provides here is a button with a class name.

## So a MORE featured library is the wrong direction

A richer library is a DEEPER coupling to another single vendor, and
the candidates are all single-vendor too: Base UI is the MUI
company's, React Aria is Adobe's, Mantine is a small team's. Swapping
Blueprint for a bigger dependency trades a shallow coupling for a
deep one and calls it safety.

## The proposal: own the kit, borrow only the hard behaviour

  ui/packages/ui-kit -- OURS, in the repository:
    Button, Tag, Callout, Input, FormGroup, Table, Select, Spinner,
    NonIdealState, Card, TextArea, Icon.
  These are markup and CSS. They are ours to keep, and nobody can
  abandon them.

  HEADLESS PRIMITIVES, VENDORED (copied in, not installed), for the
  six that are genuinely hard -- focus trapping, ARIA wiring,
  keyboard handling, dismissal:
    Dialog, Popover, Menu, Tabs, Checkbox/Switch, Alert.
  Copied in, an upstream change or abandonment cannot strand us. The
  precedent is live: shadcn/ui switched its default primitive from
  Radix to Base UI, and every copy already made kept working.

## The migration, in order

  1. Build the kit with its own tests, next to Blueprint.
  2. Convert panel by panel, keeping the ~920 frontend tests passing
     at every step -- they are the parity check.
  3. Vendor the six primitives, converting the overlay components
     last, since they are where behaviour (not appearance) lives.
  4. Remove @blueprintjs, and add a lint rule refusing new imports of
     it, so the migration cannot silently reverse.

## The honest cost

The twelve simple components are an afternoon each at most; the six
behavioural ones are the real work, and they are where a mistake is
invisible until a keyboard user hits it. Accessibility is the reason
to borrow behaviour rather than write it: it is easy to build a dialog
that looks right and traps nobody.
