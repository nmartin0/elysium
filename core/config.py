"""
config.py  (generic YAML loading -- org-agnostic)

The ONLY thing this file knows how to do is read a YAML file into a
plain Python dict. It has no idea what the contents mean -- no concept
of "users", "schema", or "model names". That interpretation happens
wherever this is called from.

SECURITY: _StrictSafeLoader is a direct SUBCLASS of yaml.SafeLoader,
not yaml.Loader/yaml.UnsafeLoader -- it registers no additional
constructors of its own, only OVERRIDES construct_mapping() (see
below). This preserves SafeLoader's own safety property exactly:
still only ever produces plain data structures, still cannot execute
arbitrary Python via YAML tags, even though the loading call below is
now yaml.load(f, Loader=_StrictSafeLoader) rather than the bare
yaml.safe_load(f) this file used to call directly.

DUPLICATE KEYS ARE REJECTED, not silently accepted -- this is NOT
yaml.safe_load()'s own default behavior, and the gap this closes is
real, not theoretical: PyYAML has a long-standing, still-open issue
(github.com/yaml/pyyaml/issues/165) confirming it does NOT reject
duplicate mapping keys, even though the YAML 1.2 spec itself requires
mapping keys to be unique. The observed, DEFAULT behavior is silent
data loss -- the LAST occurrence of a repeated key silently wins, with
zero warning anywhere, exactly the kind of "large files, easy to
accidentally duplicate a key while copy-pasting a block" mistake this
project's own deployment YAML files are genuinely vulnerable to (two
object_types blocks both named "Widget," a role pasted twice and only
the second one edited) -- caught directly, empirically, not assumed:
see core/deployment_loader.py's own AI-notes for the real test that
found this. _StrictSafeLoader's own construct_mapping() override runs
for EVERY mapping node PyYAML encounters, at every level of nesting,
not just the top level -- a duplicate key anywhere in the whole YAML
tree is caught, not only ones at the file's own root.

No error handling here on purpose -- a missing file, malformed YAML,
OR a duplicate key should all surface as Python's own clear
FileNotFoundError/yaml.YAMLError (ConstructorError is a YAMLError
subclass), not get wrapped in a vaguer catch-and-reraise that adds
nothing.

Called by: core/deployment_loader.py (the one place config gets read
           and turned into explicit values for core/ functions)
"""

from pathlib import Path

import yaml


class _StrictSafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        seen_keys = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen_keys:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            seen_keys.add(key)
        return super().construct_mapping(node, deep)


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.load(f, Loader=_StrictSafeLoader)
