"""Checks and tidying that need real reference data (DEP-4).

Four libraries, adopted by the owner on 13 October, each doing one
thing a regular expression does badly:

  phonenumbers     Google's libphonenumber metadata: whether a number
  (Apache-2.0)     can exist in a country, and its one international
                   form, E.164 ("+14155550123").
  email-validator  RFC 5322/6531 syntax and normalisation of the domain.
  (Unlicense)      NEVER its deliverability check, which makes DNS
                   queries: a sync or a write must not reach the network
                   because a field holds an address.
  ftfy             repairs mojibake -- "cafÃ©" read with the wrong
  (Apache-2.0)     encoding back to "café". It undoes a known mistake
                   rather than guessing at meaning, which is why it may
                   sit beside NFC in silver's meaning-preserving rule.
  holidays         public holidays by country and subdivision, so a
  (MIT)            date can be flagged for falling on one.

EVERY USE IS DECLARED on a field, never inferred, like every other
check and rule in this project. Each library is imported when a field
first asks for it, so a deployment that declares none never loads them.

TWO PLACES USE THEM, as with every constraint: a WRITE breaking one is
refused (core/ontology/constraints.py), and silver applies the field's
`on_violation` to what a source holds. Standardisation (silver only)
can also rewrite a valid phone number or email address to its one
canonical form, so that the same number written two ways is one value.
"""

import functools
from datetime import date, datetime

# -- phone numbers ---------------------------------------------------------

def phone_regions() -> frozenset:
    import phonenumbers

    return frozenset(phonenumbers.SUPPORTED_REGIONS)


def check_phone_setting(setting, where: str) -> None:
    """`true` (numbers must be written in international form, +...) or a
    region code such as "US" or "GB" for numbers written nationally."""
    if setting is True:
        return
    if not isinstance(setting, str) or setting.upper() not in phone_regions():
        raise ValueError(f"{where} must be true or a region code such as \"US\" or \"GB\", "
                         f"got {setting!r}.")


def _parsed_phone(value: str, setting):
    import phonenumbers

    region = None if setting is True else str(setting).upper()
    try:
        number = phonenumbers.parse(value, region)
    except phonenumbers.NumberParseException:
        return None
    return number if phonenumbers.is_valid_number(number) else None


def phone_problem(value, setting) -> "str | None":
    if _parsed_phone(str(value), setting) is not None:
        return None
    where = "" if setting is True else f" for {str(setting).upper()}"
    hint = " (write it with its country code, +...)" if setting is True else ""
    return f"{value!r} is not a valid phone number{where}{hint}."


def phone_e164(value: str, setting) -> str:
    """The E.164 form of a valid number; anything else unchanged, for the
    constraint (if declared) to report rather than this to hide."""
    import phonenumbers

    number = _parsed_phone(value, setting)
    if number is None:
        return value
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


# -- email addresses -------------------------------------------------------

def email_problem(value) -> "str | None":
    from email_validator import EmailNotValidError, validate_email

    try:
        validate_email(str(value), check_deliverability=False)
    except EmailNotValidError as error:
        return f"{value!r} is not a valid email address: {error}"
    return None


def email_normalised(value: str) -> str:
    """The library's normalised form -- the DOMAIN lower-cased and
    IDNA-normalised, the local part left as written, because RFC 5321
    lets a server treat `Ada` and `ada` as two mailboxes."""
    from email_validator import EmailNotValidError, validate_email

    try:
        return validate_email(value, check_deliverability=False).normalized
    except EmailNotValidError:
        return value


# -- mojibake ----------------------------------------------------------------

def fixed_text(value: str) -> str:
    import ftfy

    return ftfy.fix_text(value)


# -- public holidays --------------------------------------------------------

def check_holiday_setting(setting, where: str) -> None:
    """A country code ("US", "BR") or a country and subdivision
    ("US-CA", "BR-SP")."""
    if not isinstance(setting, str):
        raise ValueError(f"{where} must be a country code such as \"US\" or \"US-CA\", "
                         f"got {setting!r}.")
    country, _, subdivision = setting.upper().partition("-")
    import holidays

    supported = holidays.list_supported_countries()
    if country not in supported:
        raise ValueError(f"{where}: {country!r} is not a country the holidays library knows.")
    if subdivision and subdivision not in supported[country]:
        raise ValueError(f"{where}: {subdivision!r} is not a subdivision of {country}; "
                         f"known: {sorted(supported[country])[:12]}...")


@functools.lru_cache(maxsize=64)
def _calendar(setting: str):
    import holidays

    country, _, subdivision = setting.upper().partition("-")
    return holidays.country_holidays(country, subdiv=subdivision or None)


def holiday_problem(value, setting: str) -> "str | None":
    day = value.date() if isinstance(value, datetime) else value
    if not isinstance(day, date):
        return None
    name = _calendar(setting).get(day)
    if name is None:
        return None
    return f"{value!r} falls on {name}, a public holiday in {setting.upper()}."


# -- which reference data a field uses, and at which version (R40) ----------

#: The library behind each rule that reads reference data.
_LIBRARY_FOR = {"phone": "phonenumbers", "email": "email-validator",
                "fix_text": "ftfy", "not_on_holiday": "holidays"}


def reference_data_used(standardisation, field_defs) -> dict[str, str]:
    """{library: installed version} for every reference-data library the
    given columns' rules use (R40). `standardisation` is {column: rules},
    `field_defs` the declared fields whose constraints are checked."""
    from importlib.metadata import PackageNotFoundError, version

    names = set()
    for rules in (standardisation or {}).values():
        names.update(_LIBRARY_FOR[key] for key in ("phone", "email", "fix_text")
                     if rules and rules.get(key))
    for field_def in field_defs:
        constraints = (field_def or {}).get("constraints") or {}
        names.update(_LIBRARY_FOR[key] for key in ("phone", "email", "not_on_holiday")
                     if constraints.get(key))
    found = {}
    for name in sorted(names):
        try:
            found[name] = version(name)
        except PackageNotFoundError:
            found[name] = "not installed"
    return found
