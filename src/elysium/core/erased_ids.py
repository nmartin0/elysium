"""Whether an id is one the erasure register says to forget (R13).

THE REGISTER HOLDS NO IDS. core/mirror/erasure.py records an erasure as a
salted hash of "<type>:<id>", so the one record that must survive is not
itself a list of who asked to be forgotten. Every store that holds ids
therefore forgets the same way the mirror does: hash what it holds, and
compare. These are the comparisons, in one place, so the stores beside
the mirror -- frozen sets, the write log, the approvals queue, paused
questions, notifications -- cannot each decide differently what
"mentions an erased person" means.

A LEAF: it is handed the register's hasher and hash sets as arguments,
and imports nothing from core. Every store can reach it.

`key_hash(object_type, object_id) -> str` and `hashes_by_type:
{object_type: {hash, ...}}` are ErasureRegister.hasher() and
.hashes_by_type().
"""

from collections.abc import Callable, Iterable, Iterator
from typing import Any

KeyHash = Callable[[str, Any], str]


def is_erased(key_hash: KeyHash, hashes_by_type: dict, object_type: Any, object_id: Any) -> bool:
    """This one object, of this one type."""
    hashes = hashes_by_type.get(str(object_type))
    if not hashes or object_id is None:
        return False
    return key_hash(str(object_type), object_id) in hashes


def is_erased_as_any_type(key_hash: KeyHash, hashes_by_type: dict, value: Any) -> bool:
    """A value in an id position whose type the holder does not record --
    an action parameter, a search result after a link, a frozen set's
    origin filter. Checked against every erased type.

    ONLY FOR VALUES IN ID POSITIONS. "2" is an erased Transaction's id and
    also an amount; asking of every value in a payload would forget a
    proposal for changing somebody else's amount to 2.
    """
    if value is None or isinstance(value, (bool, dict, list, tuple, set)):
        return False
    return any(key_hash(object_type, value) in hashes
               for object_type, hashes in hashes_by_type.items() if hashes)


def any_erased(key_hash: KeyHash, hashes_by_type: dict,
               typed: Iterable[tuple[Any, Any]]) -> bool:
    """Any (type, id) pair, where a type of None means "unrecorded"."""
    for object_type, object_id in typed:
        if object_type is None:
            if is_erased_as_any_type(key_hash, hashes_by_type, object_id):
                return True
        elif is_erased(key_hash, hashes_by_type, object_type, object_id):
            return True
    return False


def ids_in_gathered(gathered: Iterable) -> Iterator[tuple[Any, Any]]:
    """Every id a run of the agent named or was shown, as (type, id).

    THE ID POSITIONS OF A GATHERED ENTRY: the object it read
    (`object_id`, `object_ids`), and the ids a search or a link returned
    (a list `result`). A search's results are its own type's; any other
    list -- a link, a search_around -- may be another type's, so it is
    returned untyped and checked against all of them.
    """
    for entry in gathered or ():
        if not isinstance(entry, dict):
            continue
        object_type = entry.get("object_type")
        if entry.get("object_id") is not None:
            yield object_type, entry["object_id"]
        for object_id in entry.get("object_ids") or ():
            yield object_type, object_id
        result = entry.get("result")
        if isinstance(result, list):
            own = (object_type if entry.get("step") in ("search_object", "search_text",
                                                        "search_meaning") else None)
            for object_id in result:
                if not isinstance(object_id, (dict, list)):
                    yield own, object_id
        elif isinstance(result, dict) and entry.get("step") == "get_object":
            for object_id in result:
                yield object_type, object_id
