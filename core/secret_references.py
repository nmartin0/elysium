"""Keeping credentials out of configuration files.

THE PROBLEM, NOW CONCRETE. A SQLAlchemy silo is declared with a URL,
and a real one carries a password:

    url: "postgresql+psycopg://elysium:hunter2@db.internal/warehouse"

That file is read by anyone who can read the config directory, lands
in every backup, and goes into version control if a deployment tracks
its own configuration -- which is the ordinary thing to do.

`${VAR}`, DELIBERATELY, AND NOTHING CLEVERER. It is the notation
operators already know from shell, docker-compose, Kubernetes
manifests and CI configuration, and it needs no new vocabulary in a
file that already has plenty.

WHAT THIS IS NOT. Not a secret store, not rotation, not an audit of
who read what. It moves a credential from a file Elysium reads into
the process environment, which is where systemd's `EnvironmentFile=`,
a container runtime's secret mount, and every CI system already put
them. That is a smaller claim than "secret management" and it is the
one worth making first.

A MISSING VARIABLE IS FATAL, and that is the whole point. Substituting
an empty string would produce a URL that looks complete and connects
as nobody, and the resulting error would name the database rather than
the configuration. Refusing at load names the variable.
"""

import os
import re
from urllib.parse import urlsplit

# ${NAME}, with names restricted to what an environment variable may
# actually be called. A loose pattern would match `${...}` inside a
# password that happens to contain braces and then fail to find it.
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MissingSecret(ValueError):
    """A configuration names an environment variable that is not set.

    ITS OWN TYPE so the loader can say WHICH variable rather than
    letting a half-substituted string reach a driver, where the error
    would be about the database instead.
    """


# KEYS WHOSE VALUE IS A CREDENTIAL BY NAME. A small, fixed set,
# deliberately not a pattern -- the same reasoning submission_criteria
# gives for its operators: a closed vocabulary a person can read and a
# linter can check, rather than something that needs its own evaluator
# and surprises somebody at load time.
_SECRET_KEYS = frozenset({"password", "secret", "token", "api_key", "access_key"})


class PlaintextSecret(ValueError):
    """A configuration carries a credential instead of a ${VAR} reference."""


def _refuse_plaintext(value: str, where: str) -> None:
    """Refuses a literal credential where a ${VAR} belongs (SEC-05).

    WHY AT LOAD, AND WHY REFUSE RATHER THAN WARN. `data_silos.yaml` is
    on manifest.py's PUBLISHABLE list and is copied into the lake
    VERBATIM -- file contents, not names, with nothing redacting on the
    way. manifest.py's own comment four lines below that list states
    the rule this breaks: "a lake reader must never become a credential
    reader, and the whole point of a lake is that many things read it."
    Excluding credentials.db is careful and right; including
    data_silos.yaml reopens the same door, because that file is exactly
    where a database URL with an inline password lives. And a lake
    Elysium did not create may be world-readable -- run_sync prints
    that warning at every sync.

    So a warning is not enough: by the time anyone reads it the
    credential is already in the lake, and the lake is the thing many
    processes read.

    CHECKED BEFORE SUBSTITUTION, which is the whole reason this is a
    separate pass. After expansion a correctly-written `${DB_PW}`
    config ALSO contains a real password, and the two are then
    indistinguishable. Only the raw value can tell them apart.

    TWO SHAPES, because a credential arrives two ways:
      - a URL with a password in its userinfo
        (postgresql+psycopg://user:hunter2@host/db)
      - a key named for a secret holding a literal
        (password: hunter2)

    NOT A GENERAL SECRET SCANNER. It refuses what a ${VAR} could
    plainly have carried instead, and says which variable to set. A
    high-entropy string in a field named `note` is somebody else's
    problem and guessing at it would fail loads for no reason.
    """
    if _REFERENCE.search(value):
        # A reference is exactly what we are asking for. A value that
        # MIXES a reference and a literal -- "${USER}:hunter2@host" --
        # is not refused here, deliberately: detecting which half is
        # the secret means parsing a URL that is not yet complete.
        return

    leaf = where.rsplit(".", 1)[-1].rstrip("]").split("[")[0]
    if leaf in _SECRET_KEYS and value:
        raise PlaintextSecret(
            f"{where} holds a literal credential. Put it in the environment "
            f"and reference it, so the value never reaches a file that is "
            f"copied into the lake:\n\n    {leaf}: \"${{ELYSIUM_{leaf.upper()}}}\"\n"
        )

    if "://" not in value:
        return
    try:
        parsed = urlsplit(value)
    except ValueError:
        # Not parseable as a URL, so not a URL credential. A malformed
        # connection string fails later, where the message is about the
        # connection rather than about secrets.
        return
    if parsed.password:
        raise PlaintextSecret(
            f"{where} is a URL carrying a password in plain text. That file is "
            f"published into the lake verbatim, so put the password in the "
            f"environment and reference it:\n\n    "
            f"{parsed.scheme}://{parsed.username or 'user'}:${{ELYSIUM_DB_PASSWORD}}"
            f"@{parsed.hostname or 'host'}/...\n"
        )


def expand_secrets(value, *, where: str = "configuration"):
    """Replaces every ${VAR} in a config value from the environment.

    RECURSIVE THROUGH DICTS AND LISTS, because a connection block is a
    dict and nothing guarantees the credential sits at the top level.

    STRINGS ONLY at the leaves -- a port number is an int and must
    stay one, and calling str() on it to run a regex would silently
    change its type.
    """
    if isinstance(value, dict):
        return {
            key: expand_secrets(item, where=f"{where}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            expand_secrets(item, where=f"{where}[{index}]")
            for index, item in enumerate(value)
        ]
    if not isinstance(value, str):
        return value

    # BEFORE substitution -- see _refuse_plaintext() for why the order
    # is the point rather than an implementation detail.
    _refuse_plaintext(value, where)

    def replace(match: re.Match) -> str:
        name = match.group(1)
        try:
            return os.environ[name]
        except KeyError:
            raise MissingSecret(
                f"{where} refers to ${{{name}}}, which is not set in the "
                f"environment. Set it before starting Elysium -- systemd's "
                f"EnvironmentFile= is the usual place."
            ) from None

    return _REFERENCE.sub(replace, value)
