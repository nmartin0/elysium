"""Search by meaning: which text a type is searched by (R45, 17 October).

    object_types:
      SupportTicket:
        semantic_search:
          from: [subject, body]

An EMBEDDING is a list of numbers a small model gives a piece of text --
a point on a map where texts that mean the same land close together.
"I was charged twice" and "duplicate payment" share no word and sit side
by side. Elysium embeds each row's declared text locally
(core/embeddings.py) and ranks rows by how near they are: "related in
meaning" under a search, "similar records" on an object.

WORDS STILL DECIDE WHAT MATCHES. A search's text query defines an object
SET -- the one counts, charts, exports, saved views and triggers share
(mediator._set_members). A nearest-neighbour rank has no edge to it:
every row is SOME distance away, and which are "near enough" moves with
the model. So meaning is offered BESIDE the word matches, never mixed
into them, and no count, chart or trigger depends on a model's ranking.

NEVER A CLASSIFIED INPUT (R42, as enrichment). An embedding is nearly as
revealing as its text: from embeddings alone Morris et al. recovered
"92% of 32-token text inputs exactly" and "89% of full names from
embedded notes" (EMNLP 2023). An embedding of a classified field IS
classified, and whether those may be processed by a model at all is D3,
still open. Refused at load.

WHO MAY USE IT: someone who may read the type AND every input field. A
ranking by a field's meaning tells you about the field; someone refused
`body` must not be able to ask which tickets read like "refund fraud".
The vectors themselves are never served.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from core.ontology.classifications import field_classifications
from core.ontology.field_types import is_computed

#: How many fields one declaration may embed together.
MAX_INPUTS = 8


@dataclass(frozen=True)
class SemanticSearch:
    inputs: tuple[str, ...]


def semantic_search_of(type_def: Mapping) -> "SemanticSearch | None":
    """The type's declaration, or None. Unvalidated: load checks first."""
    declared = type_def.get("semantic_search")
    if not declared:
        return None
    inputs = declared.get("from")
    if isinstance(inputs, str):
        inputs = [inputs]
    return SemanticSearch(tuple(inputs or ()))


def validate_semantic_search(object_types: Mapping, embedding_model: "str | None") -> None:
    """Refuses, at load, a declaration that could not be embedded -- or
    that would send a classified value to a model."""
    for type_name, type_def in object_types.items():
        if "semantic_search" not in type_def:
            continue
        where = f"{type_name}.semantic_search"
        declared = type_def["semantic_search"]
        if not hasattr(declared, "items") or set(declared) != {"from"}:
            raise ValueError(f"{where} is {{from: [fields]}}: the text a row is searched by.")
        if not embedding_model:
            raise ValueError(f"{where} needs a model to embed with: set `llm.embedding_model` in "
                             f"config.yaml (nomic-embed-text, say, after `ollama pull` on the "
                             f"server).")
        search = semantic_search_of(type_def)
        assert search is not None
        fields = type_def.get("fields") or {}
        if not 1 <= len(search.inputs) <= MAX_INPUTS:
            raise ValueError(f"{where}: `from` names 1 to {MAX_INPUTS} fields.")
        if len(set(search.inputs)) != len(search.inputs):
            raise ValueError(f"{where}: `from` names a field twice.")
        for name in search.inputs:
            if not isinstance(name, str) or name not in fields:
                raise ValueError(f"{where}: `from` names {name!r}, which this type does not have.")
            source = fields[name]
            if source.get("type", "data") != "data":
                raise ValueError(f"{where}: {name!r} is a {source['type']}; meaning is read "
                                 f"from text.")
            if is_computed(source):
                raise ValueError(f"{where}: {name!r} is computed; embed the fields it comes "
                                 f"from instead.")
            if (source.get("data_type") or "string") != "string":
                raise ValueError(f"{where}: {name!r} is {source['data_type']}; meaning is "
                                 f"read from text.")
            labels = field_classifications(source)
            if labels:
                raise ValueError(f"{where}: {name!r} is classified {sorted(labels)}. An "
                                 f"embedding is nearly as revealing as its text, and a "
                                 f"classified field is never sent to a model.")
