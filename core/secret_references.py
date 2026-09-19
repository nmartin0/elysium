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
