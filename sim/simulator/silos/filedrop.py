"""
filedrop.py  (a folder somebody drops files into, which is how small
businesses actually integrate)

More common than any DATABASE connection. A small business's bank
statement arrives as a CSV download. Its supplier's price list arrives
as a spreadsheet by email. Its payroll provider drops a file on a
share every fortnight. Its card processor publishes a settlement file
nightly. None of that is a database and all of it is real operational
data that a platform ends up reading -- which is why Foundry lists
plain directories, SMB shares, SFTP and FTP alongside its database
connectors.

What this silo is: a directory, and a discipline about how files
appear in it.

The discipline is the interesting part, and it is the thing a naive
implementation gets wrong. A consumer polling a folder reads whatever
is there when it looks. If a file is written in place over several
seconds, the consumer can and eventually will read half of it -- a CSV
truncated mid-row, parsed without complaint into a short file with a
mangled last record. So well-behaved publishers write to a temporary
name and rename into place, because rename within a filesystem is
atomic and a consumer therefore sees the file either not at all or
complete.

And not every real publisher does this. Plenty write in place, and the
resulting torn reads are a genuine, recurring integration failure.
`place()` is atomic by default and takes `atomic=False` so that
condition can be produced deliberately -- it is a property of the
upstream being simulated, not a test hook.

CSV dialect defaults to what these files really look like: CRLF line
endings and a UTF-8 BOM, because the overwhelming majority are
produced by, or intended to be opened in, Excel on Windows. Excel
misreads a UTF-8 file without the BOM, so exporters emit one, and a
consumer that assumes clean UTF-8 finds three stray bytes on the first
field name. Defaulting to the tidy form would be simulating a file
nobody sends.
"""

import csv
import io
import os
import random
import re
import zipfile
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from simulator.silo import ConnectionDescriptor, Silo, SiloError
from simulator.silos.nodatabase import refuse_database

#: Byte order mark. Excel needs it to read UTF-8 correctly, so real
#: exports carry it, so consumers have to cope with it.
UTF8_BOM = "\ufeff"

#: Suffix used while a file is being written, before the rename that
#: publishes it. Chosen to be obviously incomplete to anything that
#: lists the directory, and to be a suffix rather than a prefix so a
#: consumer filtering on `*.csv` skips it naturally.
PARTIAL_SUFFIX = ".part"

#: What a terminated silo's directory is renamed to. Recoverable: a
#: share going away is usually a mount dropping or a permission
#: change, not a deletion.
TERMINATED_SUFFIX = ".gone"

#: Where a share's files are while it is out (simulator/outages.py).
OFFLINE_SUFFIX = ".offline"

#: The encodings a file may be written in (REAL_SOURCES.md F3). Excel's
#: UTF-8 export carries a byte order mark; its plain comma-delimited one is
#: in the Windows code page, which writes "?" for what it cannot hold.
ENCODINGS = ("utf-8", "utf-8-sig", "cp1252")
#: Comma, the semicolon a comma-decimal locale's Excel uses, and tab.
DELIMITERS = (",", ";", "\t")


class FileDropSilo(Silo):
    """One silo that is a directory files are published into."""

    kind: ClassVar[str] = "filedrop"
    #: A folder listens on nothing.
    requires_port: ClassVar[bool] = False

    def __init__(self, name: str, data_dir: Path, folder: str | None = None,
                 *, bom: bool = True, line_terminator: str = "\r\n",
                 encoding: str | None = None, delimiter: str = ",",
                 decimal_comma: bool = False, excel_conversions: bool = False,
                 reorder_columns: bool = False, zipped: bool = False,
                 atomic_writes: bool = True, duplicate_rate: float = 0.0,
                 late_rate: float = 0.0, late_seconds: float = 86400.0,
                 keep_last: int | None = None) -> None:
        super().__init__(name, data_dir)
        #: Named after the silo by default, so a world's directory
        #: reads as a list of systems rather than of folders.
        self.folder = folder or name
        self.bom = bom
        self.line_terminator = line_terminator
        #: True while an outage has the share moved aside.
        self.offline = False
        # The realism options (REAL_SOURCES.md F1-F6), all off unless a
        # pack switches them on.
        if encoding is not None and encoding not in ENCODINGS:
            raise SiloError(f"{name}: encoding must be one of {list(ENCODINGS)}")
        if delimiter not in DELIMITERS:
            raise SiloError(f"{name}: delimiter must be one of {list(DELIMITERS)}")
        if decimal_comma and delimiter == ",":
            raise SiloError(f"{name}: a decimal comma comes with a ';' or tab delimiter, "
                            f"as Excel's does")
        for option, rate in (("duplicate_rate", duplicate_rate), ("late_rate", late_rate)):
            if not 0.0 <= rate <= 1.0:
                raise SiloError(f"{name}: {option} is a share of files, from 0 to 1")
        if late_seconds <= 0:
            raise SiloError(f"{name}: late_seconds must be positive")
        if keep_last is not None and keep_last < 1:
            raise SiloError(f"{name}: keep_last must be at least 1")
        #: None keeps `bom`: UTF-8, with a BOM if it is set.
        self.encoding = encoding or ("utf-8-sig" if bom else "utf-8")
        self.delimiter = delimiter
        #: Numbers written 12,50 rather than 12.50, as a comma-decimal
        #: locale's Excel saves them.
        self.decimal_comma = decimal_comma
        #: What a file opened and saved in Excel comes back as (F4).
        self.excel_conversions = excel_conversions
        #: Columns in a different order each file (F5).
        self.reorder_columns = reorder_columns
        #: Each file delivered inside a .zip of the same name (F6).
        self.zipped = zipped
        #: False: a file is written where it will be read, and is seen
        #: half-written until the next tick finishes it (F1).
        self.atomic_writes = atomic_writes
        #: The share of files sent twice, the copy as "name (1).csv" (F2).
        self.duplicate_rate = duplicate_rate
        #: The share of files that arrive `late_seconds` of simulated time
        #: after they were made (F2).
        self.late_rate = late_rate
        self.late_seconds = late_seconds
        #: Only the newest N files are kept; older ones vanish, as files
        #: do under a retention rule (F2).
        self.keep_last = keep_last
        #: Seeded by name, so a world's files fall the same way each run.
        self._random = random.Random(f"filedrop:{name}")
        #: (due, filename, payload) for late files and half-written ones;
        #: a due of None means "at the next tick".
        self._pending: list[tuple[datetime | None, str, bytes]] = []
        self._now: datetime | None = None

    @property
    def home(self) -> Path:
        """Where consumers are told the share is."""
        return self.data_dir / self.folder

    @property
    def path(self) -> Path:
        """Where the files really are now: the home, or -- during an outage
        (simulator/outages.py) -- moved aside, where publishing carries on
        unseen, as an upstream system keeps exporting while the share is
        unmounted."""
        return self.home.with_name(self.folder + OFFLINE_SUFFIX) if self.offline else self.home

    # -- lifecycle ---------------------------------------------------

    def create(self) -> None:
        if self.path.exists():
            raise SiloError(
                f"{self.name}: {self.path} already exists; remove the world's "
                f"directory to rebuild it"
            )
        self.path.mkdir(parents=True)

    def start(self) -> None:
        """Nothing to start. A directory is readable or it is not."""
        return None

    def stop(self) -> None:
        """Nothing to stop. See start()."""
        return None

    def is_reachable(self) -> bool:
        """Whether the directory exists and can actually be used.

        Readability is checked as well as existence, because the
        realistic way a share becomes unusable is a permission change
        or a dropped mount, not a deletion -- and in both of those the
        path can still be there.
        """
        return self.home.is_dir() and os.access(self.home, os.R_OK | os.X_OK)

    def connection(self, database: str | None = None) -> ConnectionDescriptor:
        refuse_database(self.name, self.kind, database)
        """A path, and the format a consumer should expect to find."""
        details: dict[str, object] = {
            "path": str(self.home),
            "format": "zip" if self.zipped else "csv",
            "encoding": self.encoding,
        }
        if self.delimiter != ",":
            details["delimiter"] = self.delimiter
        return ConnectionDescriptor(kind=self.kind, details=details)

    def terminate(self) -> None:
        """Move the folder aside, so the share abruptly stops existing."""
        if self.path.exists():
            self.path.replace(self.path.with_name(self.path.name + TERMINATED_SUFFIX))

    # -- publishing --------------------------------------------------

    def place(self, filename: str, content: str | bytes, *, atomic: bool = True) -> Path:
        """Publish one file.

        Atomic by default: written under a partial name and renamed
        into place, so a consumer polling the directory sees the file
        either absent or complete. `atomic=False` writes in place,
        which is what a badly-behaved real publisher does and which
        produces torn reads -- a condition worth being able to cause on
        purpose rather than only suffer.
        """
        if "/" in filename or "\\" in filename:
            # A publisher drops files in the folder. A name with a
            # separator in it is a bug in the caller, and allowing it
            # would let a pack write outside its own silo.
            raise SiloError(f"{self.name}: {filename!r} must be a plain file name")
        # Where the files are, not the public home: during an outage the
        # upstream system goes on exporting into the share moved aside.
        if not (self.path.is_dir() and os.access(self.path, os.W_OK | os.X_OK)):
            raise SiloError(f"{self.name}: {self.path} is not reachable")

        target = self.path / filename
        payload = content if isinstance(content, bytes) else self._encode(content)

        if not atomic:
            target.write_bytes(payload)
            return target

        partial = target.with_name(target.name + PARTIAL_SUFFIX)
        partial.write_bytes(payload)
        # Rename within one filesystem is atomic, which is the whole
        # mechanism: the directory entry appears complete or not at all.
        partial.replace(target)
        return target

    def write_csv(self, filename: str, header: Sequence[str],
                  rows: Iterable[Sequence[object]], *, atomic: bool = True) -> Path:
        """Publish a CSV in the dialect these files really use.

        csv.writer is given the line terminator explicitly and the
        result is written with newline="" so Python does not translate
        the terminators a second time. Getting that wrong produces
        CRLFCRLF, which most parsers tolerate and some do not -- a
        difference that only shows up on a consumer nobody tested with.
        """
        header, table = list(header), [list(row) for row in rows]
        if self.reorder_columns and len(header) > 1:
            # Seeded by the file, so the same export comes out the same
            # way each run -- but differently from the one before it.
            order = list(range(len(header)))
            random.Random(f"{self.name}:{filename}").shuffle(order)
            header = [header[i] for i in order]
            table = [[row[i] for i in order] for row in table]
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=self.delimiter,
                            lineterminator=self.line_terminator)
        writer.writerow(header)
        for row in table:
            writer.writerow([self._cell(value) for value in row])
        payload = self._encode(buffer.getvalue())
        if self.zipped:
            packed = io.BytesIO()
            with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(filename, payload)
            filename, payload = filename + ".zip", packed.getvalue()
        return self._deliver(filename, payload, atomic=atomic and self.atomic_writes)

    # -- realism (REAL_SOURCES.md F1-F6) -------------------------------

    def _encode(self, text: str) -> bytes:
        # errors="replace" is what Excel's code-page CSV does: "?" for a
        # character the code page cannot hold.
        return text.encode(self.encoding, errors="replace")

    def _cell(self, value: object) -> object:
        if value is None:
            return ""
        number = isinstance(value, (Decimal, float)) and not isinstance(value, bool)
        if self.excel_conversions:
            value = as_excel_saves(value)
        if self.decimal_comma and number:
            # After Excel's own rules, as a comma-decimal Excel saves:
            # 12.50 becomes 12,5.
            return str(value).replace(".", ",")
        return value

    def _deliver(self, filename: str, payload: bytes, *, atomic: bool) -> Path:
        """Put a finished file where it goes -- or not yet, or twice."""
        target = self.path / filename
        # No clock before the first tick: nothing publishes during seeding,
        # so a file is never made then, and none can be late.
        if self.late_rate and self._now is not None and self._random.random() < self.late_rate:
            due = self._now + timedelta(seconds=self.late_seconds)
            self._pending.append((due, filename, payload))
            return target
        if atomic:
            self.place(filename, payload)
        else:
            # Seen half-written until the next tick finishes it, as an
            # upload that has not completed is (Files.com keeps partial
            # SFTP uploads visible by default). Cut mid-row, which is how
            # a reader meets it.
            self.place(filename, payload[: max(1, len(payload) // 2)], atomic=False)
            self._pending.append((None, filename, payload))
        if self.duplicate_rate and self._random.random() < self.duplicate_rate:
            # At the last dot, as a browser names a second download:
            # report.2026-10-20 (1).csv. A zip keeps its inner name whole.
            inner = filename[:-len(".zip")] if filename.endswith(".zip") else filename
            stem, dot, suffix = inner.rpartition(".")
            copy = f"{stem} (1){dot}{suffix}" if dot else f"{inner} (1)"
            self.place(copy + (".zip" if inner != filename else ""), payload)
        self._expire()
        return target

    def _expire(self) -> None:
        if self.keep_last is None:
            return
        files = sorted((entry for entry in self.path.iterdir()
                        if entry.is_file() and not entry.name.endswith(PARTIAL_SUFFIX)),
                       key=lambda entry: (entry.stat().st_mtime_ns, entry.name))
        for old in files[: max(0, len(files) - self.keep_last)]:
            old.unlink()
            # A file expired while half-written is not finished later:
            # that would bring it back, newer than what replaced it.
            self._pending = [entry for entry in self._pending
                             if not (entry[0] is None and entry[1] == old.name)]

    def between_ticks(self, now: datetime) -> None:
        """Finish what was half-written, and deliver what has come due."""
        self._now = now
        waiting, self._pending = self._pending, []
        for index, (due, filename, payload) in enumerate(waiting):
            try:
                if due is not None and due > now:
                    self._pending.append((due, filename, payload))
                elif due is None:
                    self.place(filename, payload, atomic=False)
                else:
                    # A late file arrives whole; and if a newer export of
                    # the same name came first, it is overwritten with the
                    # older one, as a delayed re-delivery does.
                    self.place(filename, payload)
                    self._expire()
            except Exception:
                # Kept for the next tick rather than lost: a share that is
                # unreachable now may be back then.
                self._pending.extend(waiting[index:])
                raise

    def listing(self) -> list[str]:
        """Published file names, sorted, excluding partial writes.

        A consumer would see the partial files too -- they are really
        there -- but they are not published, and a silo reporting its
        own contents should report what it has published.
        """
        if not self.is_reachable():
            return []
        return sorted(
            entry.name for entry in self.path.iterdir()
            if entry.is_file() and not entry.name.endswith(PARTIAL_SUFFIX)
        )


_LONG_NUMBER = re.compile(r"-?\d{16,}")
_LEADING_ZEROS = re.compile(r"-?0\d+(\.\d+)?")
_DECIMAL = re.compile(r"-?\d+\.\d+")
_E_NUMBER = re.compile(r"\d+[eE]\d+")
_MONTH_NUMBER = re.compile(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{1,2})", re.I)
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_ISO_MOMENT = re.compile(r"(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(:\d{2}(\.\d+)?)?")


def as_excel_saves(value: object) -> str:
    """A value as it comes back from a CSV opened in Excel and saved.

    Microsoft's own list of the automatic conversions
    (support.microsoft.com, "Set automatic data conversions"): leading
    zeros removed (00123 -> 123); 16 or more digits kept to 15 and shown
    in scientific notation (12345678901234567890 -> 1.23457E+19); digits
    around an E read as scientific notation (123E5 -> 1.23E+07); letters
    and digits that look like a date made one (JAN1 -> 1-Jan; MAY32, no
    such day, is May 1932). A number loses its trailing zeros, as the
    General format shows it. And, in a US locale, an ISO date, or a date
    and time with a space and no offset, comes back m/d/yyyy [h:mm]; one
    with a T or an offset is left as text. Saved as the cell shows, which
    is what a CSV keeps.
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime) and value.tzinfo is None:
        return f"{value.month}/{value.day}/{value.year} {value.hour}:{value.minute:02}"
    if isinstance(value, date) and not isinstance(value, datetime):
        return f"{value.month}/{value.day}/{value.year}"
    text = str(value)
    if _LONG_NUMBER.fullmatch(text):
        sign, digits = ("-", text[1:]) if text.startswith("-") else ("", text)
        digits = digits.lstrip("0") or "0"
        if len(digits) < 16:
            return sign + digits
        kept = float(digits[:15] + "0" * (len(digits) - 15))
        return f"{sign}{kept:.5E}"
    if _LEADING_ZEROS.fullmatch(text) or _DECIMAL.fullmatch(text):
        # General format: no leading or trailing zeros. Decimal keeps the
        # digits exactly, where float would show 0.1 + 0.2's error.
        shown = format(Decimal(text).normalize(), "f")
        return shown
    if _E_NUMBER.fullmatch(text):
        return f"{float(text):.2E}"
    month = _MONTH_NUMBER.fullmatch(text)
    if month:
        name, number = month.group(1).title(), int(month.group(2))
        return f"{number}-{name}" if 1 <= number <= 31 else f"{name}-{number:02}"
    moment = _ISO_MOMENT.fullmatch(text)
    if moment:
        y, m, d, hh, mm = (int(moment.group(i)) for i in range(1, 6))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{m}/{d}/{y} {hh}:{mm:02}"
    day = _ISO_DATE.fullmatch(text)
    if day:
        y, m, d = (int(day.group(i)) for i in range(1, 4))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{m}/{d}/{y}"
    return text


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section
# whenever something genuinely open, deferred, or rejected comes up here.
# =============================================================================
#
# RESOLVED (kept for history): place() is atomic by default via write-to-
# partial-then-rename. Writing in place lets a polling consumer read a
# half-written file, which parses as a short CSV with a mangled last row rather
# than as an error -- the worst kind of failure. atomic=False exists so that
# condition can be produced deliberately, because plenty of real publishers do
# write in place; it is a property of the upstream being simulated, not a test
# hook.
#
# RESOLVED: the CSV dialect defaults to CRLF plus a UTF-8 BOM rather than clean
# UTF-8 with newlines. Nearly all of these files are produced by or for Excel
# on Windows, which misreads UTF-8 without a BOM, so exporters emit one and
# consumers find three stray bytes on the first field name. Defaulting to the
# tidy form would be simulating a file nobody sends.
#
# RESOLVED: write_csv passes lineterminator to csv.writer and writes with
# newline="". Both are needed on Windows, where leaving translation on turns
# each "\n" into os.linesep -- already CRLF -- and yields CRLFCRLF.
#
# Untestable on linux, and said plainly rather than covered by a test that
# cannot fail: os.linesep is "\n" here, so CRLF survives translation unchanged
# and removing newline="" changes nothing. Measured directly. The assertion in
# tests/test_filedrop_silo.py is kept for what it documents; a negative control
# confirmed it does not fire. Anyone running the suite on Windows would be
# giving it real teeth for the first time.
#
# DEFERRED (known, intentional, not yet built): no inbox/archive convention.
# Real SFTP drops often move consumed files to an archive folder, and some use
# a `.done` marker file alongside each payload instead of an atomic rename.
# Both are worth simulating and neither is needed until a pack describes a
# publisher that works that way.
#
# DEFERRED: CSV only. Supplier price lists and payroll files are frequently
# .xlsx, and Foundry reads those too. Writing real xlsx means a dependency
# (openpyxl); worth it when a pack needs one, not before.
#
# DEFERRED: no file-size or retention limit. A pack publishing daily for a
# simulated year leaves 365 files, which is fine; one publishing per tick would
# not be. Whichever pack does that first should bring the policy with it.
#
# RESOLVED (20 October, item 11 step 2): realism options, every one off unless a
# pack sets it -- encoding, delimiter, decimal_comma, excel_conversions,
# reorder_columns, zipped, atomic_writes, duplicate_rate, late_rate/
# late_seconds, keep_last. Late and half-written files need the world's
# clock, so the silo has a between_ticks hook the runner calls; everything
# random is seeded by the silo's name.
#
# DELIBERATE: the descriptor states the encoding and delimiter. A real share
# announces neither, but whoever configures a reader is told "it's Excel, on
# a German machine"; hiding it would test guessing, not reading.
#
# DEFERRED: columns appearing on their own (REAL_SOURCES.md F5). A
# publication names its columns, as a contract should; a report template
# that gains one is a pack vocabulary change (`columns: all`), not a silo
# option.
