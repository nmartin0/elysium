"""A REST/JSON API as a source (19 October).

    books:
      adapter: rest
      connection:
        base_url: "https://api.example.com/v1"
        auth: {type: bearer, token: "${BOOKS_TOKEN}"}
        tables:
          invoices:
            path: "/invoices"
            records: "data"              # dotted path to the list; "" for a root list
            pagination:
              type: cursor               # cursor | next_url | link_header | page | offset | none
              cursor_field: "cursor"     # where the next token is, in the reply
              cursor_param: "cursor"     # the query parameter it is sent back as
        # timeout_seconds: 60
        # max_retries: 5

HOW THE PRECEDENT SHAPED IT (Airbyte's declarative connectors, dlt's
rest_api source, Fivetran's Connector SDK, RFC 9110 / RFC 6585 / RFC 8288
and the IETF RateLimit draft):

  - EVERY SYNC READS EVERY PAGE. An API asked only for what changed never
    reports deletions -- "the only way to capture them is a full re-sync"
    (Fivetran) -- and the mirror's mass-deletion guard still stands
    between a short read and the served copy.
  - PAGINATION IS DECLARED, NOT GUESSED: dlt detects it but says "for
    production environments, we recommend specifying an explicit
    paginator". The same family every tool offers: a token in the reply,
    a next URL in the reply, a Link rel="next" header, page numbers,
    offsets, or one page.
  - 429 AND 5XX ARE RETRIED, with connection errors and timeouts, up to
    five times, waiting 1, 2, 4, 8, 16 seconds (dlt's defaults; Airbyte
    and Fivetran agree on the shape). A Retry-After -- seconds or an HTTP
    date -- WINS, as dlt and Fivetran do by default and the IETF draft
    says it "MUST take precedence", capped at dlt's 300 seconds.
  - EVERY OTHER 4XX STOPS AT ONCE, 401 and 403 named as credentials
    refused: Fivetran's "fail fast with the status code and response
    body". The body is cut short, and the credential is never in it.
  - MONEY STAYS EXACT: JSON numbers are parsed as Decimal, never float.
  - NO TOOL OFFERS A CONSISTENT READ ACROSS PAGES. A record served twice
    reaches the sync's duplicate guard; a page token the API repeats is a
    broken API, refused rather than looped on.
  - ONE READ PER SYNC, inside the consistent read: the columns checked and
    the rows copied come from the same pages.
  - THE LOGIN GOES TO ONE PLACE: a next page on another host is refused,
    and an error quoting the reply masks every credential (both found in
    review, 19 October). Page and offset paging end on an EMPTY page and
    refuse a page served twice. The health check is one quick attempt.

COLUMNS ARE THE KEYS THE RECORDS CARRY. An API that leaves a key out when
its value is null will make that column look removed in a sync where it
is null everywhere; the drift policy then serves it empty, which is what
it is.

READ ONLY, and only by the sync: questions are answered from gold.
"""

import email.utils
import json
import re
import time
from collections.abc import Mapping
from contextlib import contextmanager
from decimal import Decimal
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

from core.ontology.interface import ExternalReadAdapter, StorageUnavailable

PAGINATION = ("cursor", "next_url", "link_header", "page", "offset", "none")
RETRIED = frozenset({429, 500, 502, 503, 504})
DEFAULT_TIMEOUT_SECONDS = 60          # dlt's request_timeout
DEFAULT_MAX_RETRIES = 5               # Airbyte's and dlt's
MAX_RETRY_DELAY_SECONDS = 300         # dlt's request_max_retry_delay
#: A guard, not a limit anyone should meet: an API that never stops
#: paging is broken, and this says so instead of reading forever.
MAX_PAGES = 100_000
_LINK_NEXT = re.compile(r'<([^>]*)>\s*;[^,]*\brel="?next"?', re.IGNORECASE)


class ApiRefused(ValueError):
    """The API answered, and the answer means the configuration is wrong."""


def _sleep(seconds: float) -> None:      # one place for tests to stand in
    time.sleep(seconds)


def retry_after_seconds(value: "str | None", now: "float | None" = None) -> "float | None":
    """RFC 9110 Retry-After: delay-seconds, or an HTTP-date. None if absent
    or unreadable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - (time.time() if now is None else now))


class RestAdapter(ExternalReadAdapter):
    max_concurrent_reads = None
    pushable_operators = frozenset()

    def __init__(self, connection: Mapping):
        base = connection.get("base_url")
        if not isinstance(base, str) or not base.startswith(("http://", "https://")):
            raise ValueError("rest: connection.base_url must be an http(s) URL.")
        self.base_url = base.rstrip("/") + "/"
        self.timeout = float(connection.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        self.max_retries = int(connection.get("max_retries", DEFAULT_MAX_RETRIES))
        self._headers, self._params, self._auth = self._credentials(connection.get("auth"))
        # THE RAW SECRETS, for masking: a header's VALUE is "Bearer <token>",
        # and an API that echoes only the token in its error went unmasked
        # (found in review, 19 October).
        auth = connection.get("auth") if isinstance(connection.get("auth"), Mapping) else {}
        self._secrets = [str(auth[key]) for key in ("token", "api_key", "password")
                         if auth and auth.get(key)]
        self._origin = _origin(self.base_url)
        tables = connection.get("tables")
        if not isinstance(tables, Mapping) or not tables:
            raise ValueError("rest: connection.tables must name each table and its path.")
        self.tables: dict[str, dict] = {}
        for name, spec in tables.items():
            if not isinstance(spec, Mapping) or not isinstance(spec.get("path"), str):
                raise ValueError(f"rest: table {name!r} needs `path`, such as '/{name}'.")
            paging = dict(spec.get("pagination") or {"type": "none"})
            if paging.get("type") not in PAGINATION:
                raise ValueError(f"rest: table {name!r}: pagination.type must be one of "
                                 f"{PAGINATION}, got {paging.get('type')!r}.")
            if paging["type"] == "cursor" and not paging.get("cursor_field"):
                raise ValueError(f"rest: table {name!r}: cursor pagination needs cursor_field, "
                                 f"where the next token is in the reply.")
            if paging["type"] == "next_url" and not paging.get("next_field"):
                raise ValueError(f"rest: table {name!r}: next_url pagination needs next_field.")
            self.tables[name] = {"path": spec["path"].lstrip("/"),
                                 "records": spec.get("records", "data"),
                                 "params": dict(spec.get("params") or {}),
                                 "paging": paging}
        self._pinned: dict[str, list[dict]] | None = None
        self._session = requests.Session()

    @staticmethod
    def _credentials(auth) -> tuple[dict, dict, "tuple | None"]:
        """(headers, query params, basic auth). The values arrive with
        ${VAR} already expanded from the environment by the loader."""
        if auth is None:
            return {}, {}, None
        if not isinstance(auth, Mapping):
            raise ValueError("rest: auth must be a block with a `type`.")
        kind = auth.get("type")
        if kind == "bearer" and auth.get("token"):
            return {"Authorization": f"Bearer {auth['token']}"}, {}, None
        # `api_key`, `token`, `password`: the keys core/secret_references
        # recognises as credentials, so a plaintext one is refused at load.
        if kind == "api_key" and auth.get("name") and auth.get("api_key"):
            if auth.get("in", "header") == "query":
                return {}, {auth["name"]: auth["api_key"]}, None
            return {auth["name"]: auth["api_key"]}, {}, None
        if kind == "basic" and auth.get("username") is not None:
            return {}, {}, (auth["username"], auth.get("password") or "")
        raise ValueError("rest: auth must be {type: bearer, token}, {type: api_key, name, "
                         "api_key, in: header|query}, or {type: basic, username, password}.")

    # ---- one request -----------------------------------------------------

    def _get(self, url: str, params: dict, *, retries: "int | None" = None) -> requests.Response:
        """GET with the retry rules above; StorageUnavailable when the API
        cannot answer, ApiRefused when its answer means stop."""
        max_retries = self.max_retries if retries is None else retries
        if _origin(url) != self._origin:
            # THE LOGIN GOES TO ONE PLACE. A next-page URL or Link header
            # naming another host would otherwise have been sent the
            # credential (found in review: an API reply of "next":
            # "https://evil.example/steal" got the API key).
            raise ApiRefused(f"rest: the API pointed the next page at {_origin(url)}, not "
                             f"{self._origin}; the credential is not sent there.")
        attempt = 0
        while True:
            try:
                response = self._session.get(url, params={**self._params, **params},
                                             headers=self._headers, auth=self._auth,
                                             timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout) as e:
                failure, wait = f"{type(e).__name__}", None
            else:
                if response.status_code < 400:
                    return response
                if response.status_code not in RETRIED:
                    raise self._refused(url, response)
                failure = f"HTTP {response.status_code}"
                wait = retry_after_seconds(response.headers.get("Retry-After"))
            if attempt >= max_retries:
                raise StorageUnavailable(
                    f"rest {self._where(url)}: {failure}, still after {max_retries} retries.")
            delay = wait if wait is not None else 2.0 ** attempt
            _sleep(min(delay, MAX_RETRY_DELAY_SECONDS))
            attempt += 1

    def _refused(self, url: str, response) -> ApiRefused:
        body = (response.text or "")[:300]
        for secret in sorted(self._secrets, key=len, reverse=True):
            body = body.replace(secret, "***")
        if response.status_code in (401, 403):
            return ApiRefused(f"rest {self._where(url)}: HTTP {response.status_code} -- the API "
                              f"refused the credentials. Check connection.auth. {body}")
        return ApiRefused(f"rest {self._where(url)}: HTTP {response.status_code}. {body}")

    def _where(self, url: str) -> str:
        return url.split("?", 1)[0]

    # ---- one table -------------------------------------------------------

    def _spec(self, table_name: str) -> dict:
        spec = self.tables.get(table_name)
        if spec is None:
            raise StorageUnavailable(f"rest {self.base_url}: no table {table_name!r} is declared "
                                     f"under connection.tables (declared: {sorted(self.tables)}).")
        return spec

    @staticmethod
    def _at(body, path: str):
        node = body
        for key in [part for part in path.split(".") if part]:
            if not isinstance(node, Mapping) or key not in node:
                return None
            node = node[key]
        return node

    def _read_table(self, table_name: str) -> list[dict]:
        if self._pinned is not None and table_name in self._pinned:
            return self._pinned[table_name]
        spec = self._spec(table_name)
        paging = spec["paging"]
        kind = paging["type"]
        url = urljoin(self.base_url, spec["path"])
        params = dict(spec["params"])
        if paging.get("page_size") and paging.get("page_size_param"):
            params[paging["page_size_param"]] = paging["page_size"]
        if kind == "page":
            params[paging.get("page_param", "page")] = paging.get("first_page", 1)
        if kind == "offset":
            params[paging.get("offset_param", "offset")] = 0
        records: list[dict] = []
        seen_tokens: set = set()
        for _ in range(MAX_PAGES):
            response = self._get(url, params)
            try:
                body = json.loads(response.text, parse_float=Decimal)
            except ValueError as e:
                raise ApiRefused(f"rest {self._where(url)}: the reply is not JSON.") from e
            page = body if spec["records"] == "" else self._at(body, spec["records"])
            if not isinstance(page, list):
                raise ApiRefused(f"rest {self._where(url)}: no list of records at "
                                 f"{spec['records']!r} in the reply.")
            for record in page:
                if not isinstance(record, Mapping):
                    raise ApiRefused(f"rest {self._where(url)}: a record is not an object.")
                records.append({key: _flat(value) for key, value in record.items()})
            if kind == "none" or not page:
                break
            if kind == "cursor":
                token = self._at(body, paging["cursor_field"])
                if not token:
                    break
                if not isinstance(token, (str, int, Decimal)):
                    raise ApiRefused(f"rest {self._where(url)}: the page token at "
                                     f"{paging['cursor_field']!r} is not a string or number.")
                if token in seen_tokens:
                    raise ApiRefused(f"rest {self._where(url)}: the API returned the same page "
                                     f"token twice; it would page forever.")
                seen_tokens.add(token)
                params[paging.get("cursor_param", "cursor")] = token
            elif kind == "next_url":
                nxt = self._at(body, paging["next_field"])
                if not nxt:
                    break
                if nxt in seen_tokens:
                    raise ApiRefused(f"rest {self._where(url)}: the next URL repeats.")
                seen_tokens.add(nxt)
                url, params = urljoin(url, nxt), {}
            elif kind == "link_header":
                match = _LINK_NEXT.search(response.headers.get("Link", ""))
                if not match:
                    break
                nxt = urljoin(url, match.group(1))
                if nxt in seen_tokens:
                    raise ApiRefused(f"rest {self._where(url)}: the Link next repeats.")
                seen_tokens.add(nxt)
                url, params = nxt, {}
            elif kind in ("page", "offset"):
                # THE SAME PAGE TWICE IS AN API IGNORING THE PARAMETER, and
                # would be read until the page ceiling -- found in review.
                signature = json.dumps(page, sort_keys=True, default=str)
                if signature in seen_tokens:
                    raise ApiRefused(f"rest {self._where(url)}: the API returned the same page "
                                     f"twice; check pagination.{kind}_param.")
                seen_tokens.add(signature)
                if kind == "page":
                    name = paging.get("page_param", "page")
                    params[name] = int(params[name]) + 1
                else:
                    name = paging.get("offset_param", "offset")
                    params[name] = int(params[name]) + len(page)
                # ONLY AN EMPTY PAGE ENDS IT, not a short one. Airbyte stops
                # on a short page; but a server capping page_size lower than
                # asked makes EVERY page short, and the review read 100 of
                # 300 rows that way, with nothing to notice it. One extra
                # request is the price.
        else:
            raise ApiRefused(f"rest {self._where(url)}: more than {MAX_PAGES} pages; stopped.")
        if self._pinned is not None:
            self._pinned[table_name] = records
        return records

    # ---- what the sync calls --------------------------------------------

    @contextmanager
    def consistent_read(self):
        """Each table read once for the whole sync. Not a snapshot of the
        API -- none exists -- so it yields False, as the truth."""
        if self._pinned is not None:
            yield False
            return
        self._pinned = {}
        try:
            yield False
        finally:
            self._pinned = None

    def health_check(self) -> None:
        """The first page of the first table answers."""
        # ONE ATTEMPT: startup and the Silos screen run this while someone
        # waits, and with retries a 503 asking for 300 s held startup for
        # 25 minutes (found in review). A sync still retries in full.
        name = next(iter(self.tables))
        spec = self._spec(name)
        self._get(urljoin(self.base_url, spec["path"]), dict(spec["params"]), retries=0)

    def columns_present(self, table_name: str) -> set[str]:
        return {key for record in self._read_table(table_name) for key in record}

    def source_column_types(self, table_name: str) -> dict[str, str]:
        return {}                       # JSON says too little to call it a type

    def read_all_rows(self, table_name: str, columns: list[str], type_config: dict) -> list[dict]:
        return [{name: record.get(name) for name in columns}
                for record in self._read_table(table_name)]

    def iter_all_rows(self, table_name: str, columns: list[str], type_config: dict,
                      batch_size: int = 50_000):
        rows = self.read_all_rows(table_name, columns, type_config)
        for start in range(0, len(rows), batch_size):
            yield rows[start:start + batch_size]

    # ---- not called on a source since GOLD-9 ----------------------------

    def _gold_only(self, *_args, **_kwargs):
        raise NotImplementedError("rest is read only by the sync; questions are answered from gold.")

    find_ids = _gold_only
    find_ids_matching_text = _gold_only
    get_raw_field = _gold_only
    resolve_reverse_links_batch = _gold_only
    read_fields_for_ids = _gold_only
    resolve_reverse_link = _gold_only


def _origin(url: str) -> tuple:
    """(scheme, host, port), the default port filled in."""
    parts = urlsplit(url)
    port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    return (parts.scheme, (parts.hostname or "").lower(), port)


def _flat(value: Any) -> Any:
    """Scalars as they came (Decimal for numbers); a nested object or list
    as its JSON text, which is what a column can hold."""
    if isinstance(value, (Mapping, list)):
        return json.dumps(value, default=str, sort_keys=True)
    return value
