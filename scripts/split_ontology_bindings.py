"""Write the source bindings out of an existing ontology file
(GOLD-3c).

WHAT IT IS FOR. A deployment written before the split has one
ontology_schema.yaml carrying both what an object IS and where its
data comes from. This writes the source_bindings.yaml that takes the
second half, so nobody has to assemble it by hand and get it subtly
wrong.

IT DOES NOT REWRITE ontology_schema.yaml, and that is deliberate. The
first version did, with yaml.safe_dump, AND DELETED EVERY COMMENT IN
THE FILE -- 27 of them in the shipped deployment, which are most of
what makes an ontology readable. A tool that silently destroys the
prose explaining a decision is worse than one that asks for five
minutes of hand-editing, so this prints exactly which blocks to
delete and leaves the file alone.

(ruamel.yaml round-trips comments, and CONFIG_ROUND_TRIP_AND_UI_KIT.md
already measured it keeping 104 of 104. It is not a dependency yet,
and adding one for a one-off migration script is not the trade this
project makes -- rule 18.)

RUN IT AGAINST A DEPLOYMENT DIRECTORY:

    python -m scripts.split_ontology_bindings deployment/etc

IT PROVES THE ROUND TRIP BEFORE WRITING ANYTHING: the two halves are
merged back and compared with what was read, and a mismatch stops it,
because that means some key would be dropped silently.
"""

import sys
from pathlib import Path

import yaml

from core.ontology.bindings import merge_bindings, split_bindings


def split(directory: Path) -> int:
    schema_path = directory / "ontology_schema.yaml"
    bindings_path = directory / "source_bindings.yaml"
    if not schema_path.exists():
        print(f"no ontology_schema.yaml in {directory}", file=sys.stderr)
        return 1
    if bindings_path.exists():
        print(f"{bindings_path} already exists -- nothing to do", file=sys.stderr)
        return 1

    document = yaml.safe_load(schema_path.read_text()) or {}
    wrapped = "object_types" in document
    types = document.get("object_types") if wrapped else document

    declaration, bindings = split_bindings(types)
    if merge_bindings(declaration, bindings) != types:
        # THE GUARD THAT MATTERS. If the halves do not put back
        # together, some key is being dropped, and writing the files
        # anyway would lose it silently.
        print("the split does not round-trip; nothing written", file=sys.stderr)
        return 1

    bindings_path.write_text(
        "# WHERE EACH OBJECT TYPE'S DATA COMES FROM (GOLD-3c).\n"
        "#\n"
        "# An INGESTION detail, kept out of ontology_schema.yaml so that\n"
        "# file says what an object IS and nothing else. Since GOLD-8 this\n"
        "# is not how reads work either: a read goes to gold, whose table\n"
        "# is the object type and whose columns are property names.\n"
        "#\n"
        "# Written by scripts/split_ontology_bindings.py.\n"
        + yaml.safe_dump({"object_types": bindings}, sort_keys=False)
    )
    print(f"wrote {bindings_path}")
    print()
    print("NOW DELETE THESE FROM ontology_schema.yaml, by hand, keeping")
    print("the comments around them:")
    for object_type, bound in sorted(bindings.items()):
        for key in sorted(set(bound) - {"fields"}):
            print(f"  {object_type}: {key}")
        for field_name, field_bound in sorted((bound.get("fields") or {}).items()):
            for key in sorted(field_bound):
                print(f"  {object_type}.fields.{field_name}: {key}")
    print()
    print("The loader REFUSES to start while both files bind the same")
    print("type, so a half-finished edit cannot go unnoticed.")
    return 0


if __name__ == "__main__":  # pragma: no cover - a one-off operator script
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(split(Path(sys.argv[1])))
