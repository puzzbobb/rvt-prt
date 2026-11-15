"""Open a Revit file and inflate its streams, as rvt-rs's reader does.

Ported from rvt-rs `src/compression.rs`: database streams are stored in
65,249-byte pages whose last 353 bytes are a checksum (stripped first),
and a `Partitions/NN` stream is every gzip member found in it, inflated
and concatenated in order.
"""
import contextlib
import functools
import pathlib
import re
import struct
import zlib

import olefile

STORED_PAGE = 65_249
PAGE_PAYLOAD = 64_896
GZIP_MAGIC = b"\x1f\x8b\x08"
PAGED = {
    "Formats/Latest", "Global/ContentDocuments", "Global/DocumentIncrementTable",
    "Global/ElemTable", "Global/History", "Global/Latest", "Global/PartitionTable",
}


def is_paged(name: str) -> bool:
    if name.startswith("Partitions/"):
        rest = name[len("Partitions/"):]
        return bool(rest) and "/" not in rest
    return name in PAGED


def strip_pages(data: bytes) -> bytes:
    full = len(data) // STORED_PAGE
    if full == 0:
        return data
    parts = [data[p * STORED_PAGE: p * STORED_PAGE + PAGE_PAYLOAD] for p in range(full)]
    parts.append(data[full * STORED_PAGE:])
    return b"".join(parts)


def gzip_header_len(data: bytes, at: int):
    if data[at:at + 3] != GZIP_MAGIC or at + 10 > len(data):
        return None
    flags = data[at + 3]
    pos = at + 10
    if flags & 0x04:
        if pos + 2 > len(data):
            return None
        pos += 2 + int.from_bytes(data[pos:pos + 2], "little")
    for bit in (0x08, 0x10):
        if flags & bit:
            end = data.find(b"\0", pos)
            if end < 0:
                return None
            pos = end + 1
    if flags & 0x02:
        pos += 2
    return None if pos > len(data) else pos - at


CHUNK = 1 << 18

# How much a file may inflate to. Revit's streams inflate to 4-5 times the file (testfamily 4.0,
# Snowdon's HVAC 4.1, Structural 4.6); DEFLATE can reach 1,032 times, and a file made to (a
# decompression bomb) would take the machine's memory. A file past the limit is refused.
INFLATE_RATIO = 40
INFLATE_FLOOR = 64 << 20


class UnsupportedFile(ValueError):
    """A file rvt-prt cannot print: not a Revit project, damaged, or of a Revit release
    outside SHEET_RELEASES."""


class DamagedFile(UnsupportedFile):
    """A Revit file whose contents do not read as Revit writes them: cut short, corrupted, or
    made to mislead a reader."""


def inflate_limit(path) -> int:
    """The bytes the file at `path` may inflate to, in all (INFLATE_RATIO, INFLATE_FLOOR)."""
    return max(INFLATE_FLOOR, INFLATE_RATIO * pathlib.Path(path).stat().st_size)


class Budget:
    """What is left of a file's inflate limit, shared by its streams."""

    def __init__(self, limit):
        self.limit = self.left = limit

    def take(self, n):
        self.left -= n
        if self.left < 0:
            raise DamagedFile(f"it inflates to more than {self.limit >> 20} MB, {INFLATE_RATIO} times its size or more: "
                              "not a file Revit wrote")


def inflate(data, wbits, budget=None) -> bytes:
    """`data` inflated whole (zlib.decompress), within `budget` (Budget; None: unbounded)."""
    if budget is None:
        return zlib.decompress(data, wbits)
    d = zlib.decompressobj(wbits)
    out = d.decompress(data, budget.left + 1)
    budget.take(len(out))
    if not d.eof:
        raise zlib.error("incomplete or truncated stream")
    return out


# what reading damaged bytes raises, short of running out of memory or time
_MISREAD = (ValueError, KeyError, IndexError, TypeError, AttributeError, OverflowError, RecursionError,
            struct.error, zlib.error, EOFError)


@contextlib.contextmanager
def reading(path, what):
    """Reading `what` of the file at `path`: a misread (a count past the data, an unknown marker,
    a stream that does not inflate) is a DamagedFile saying which part, not a traceback."""
    try:
        yield
    except UnsupportedFile:
        raise
    except _MISREAD as e:
        raise DamagedFile(f"{pathlib.Path(path).name} cannot be read: its {what} is damaged or not as Revit writes it "
                          f"({type(e).__name__}: {str(e)[:120]})") from e


def inflate_members(data: bytes, budget=None) -> list[bytes]:
    """Every gzip member of `data`, inflated; false magic matches are skipped. Members are fed
    through a memoryview (slicing bytes copied the rest of the stream for every member: 86 s for
    4,532 members of a 78 MB partition) and the search resumes after each member's end. Within
    `budget` (Budget), counted a chunk at a time."""
    out = []
    view = memoryview(data)
    at = data.find(GZIP_MAGIC)
    while at >= 0:
        header = gzip_header_len(data, at)
        nxt = at + 3
        if header is not None:
            d = zlib.decompressobj(-15)
            pos, parts = at + header, []
            try:
                # bounded chunks: `unused_data` copies whatever input follows the member's end
                while not d.eof and pos < len(data):
                    parts.append(d.decompress(view[pos:pos + CHUNK]))
                    pos += CHUNK
                    if budget is not None:
                        budget.take(len(parts[-1]))
                if d.eof:
                    out.append(b"".join(parts))
                    nxt = min(len(data), pos) - len(d.unused_data)
            except zlib.error:
                pass
        at = data.find(GZIP_MAGIC, nxt)
    return out


class RevitFile:
    def __init__(self, path):
        self.path = str(path)
        self.ole = olefile.OleFileIO(self.path)
        self.budget = Budget(inflate_limit(self.path))  # for every stream inflated from it

    def stream_names(self) -> list[str]:
        return sorted("/".join(p) for p in self.ole.listdir())

    def read_stream(self, name: str) -> bytes:
        return self.ole.openstream(name.split("/")).read()

    def partition_names(self) -> list[str]:
        return [n for n in self.stream_names() if n.startswith("Partitions/")]

    @functools.cache
    def inflated(self, name: str) -> bytes:
        with reading(self.path, f"stream {name}"):
            raw = self.read_stream(name)
            if is_paged(name):
                raw = strip_pages(raw)
            return b"".join(inflate_members(raw, self.budget))


def schema_bytes(path) -> bytes:
    """The file's class catalog, `Formats/Latest`, inflated (within the file's inflate limit)."""
    raw = strip_pages(olefile.OleFileIO(str(path)).openstream(["Formats", "Latest"]).read())
    head = gzip_header_len(raw, 0)
    if head is None:
        raise ValueError("Formats/Latest does not start with a gzip member")
    limit = inflate_limit(path)
    data = zlib.decompressobj(-15).decompress(raw[head:], limit + 1)
    Budget(limit).take(len(data))
    return data


SHEET_RELEASES = (2014, 2027)  # the releases whose element records rvt_prt reads


GEOMETRY_RELEASES = (2014, 2027)  # the releases whose element geometry rvt-rs reads (_native.GEOMETRY_RELEASES)
_RELEASE_YEARS = range(2014, 2041)  # what rvt-rs takes for a release in BasicFileInfo


@functools.cache
def revit_release(path) -> int | None:
    """The Revit release that saved the file, from BasicFileInfo as rvt-rs reads it (its UTF-16
    text's first four digits that make a year 2014-2040: 2025 files hold length-prefixed
    strings, "\x042025\x1220240307_1300(x64)..."), else its "Autodesk Revit ... 20xx" (files
    before 2014, which rvt-rs does not read), else None (2008 files record only a build date)."""
    text = _basic_file_info(path)
    for m in re.finditer(r"(?=(\d{4}))", text):
        if int(m.group(1)) in _RELEASE_YEARS:
            return int(m.group(1))
    named = re.search(r"Autodesk Revit[A-Za-z ]*? (20\d\d)\b", text)
    return int(named.group(1)) if named else None


def revit_build(path) -> str | None:
    """The build date of the Revit that saved the file, as YYYY-MM-DD, from BasicFileInfo's
    "Revit Build: 20080126_1900" or "20240307_1300(x64)", else None."""
    m = re.search(r"Build: [^\d]*(\d{4})(\d\d)(\d\d)_", _basic_file_info(path)) or \
        re.search(r"(\d{4})(\d\d)(\d\d)_\d{4}\(x64\)", _basic_file_info(path))
    return "-".join(m.groups()) if m else None


def capabilities(path) -> dict:
    """What rvt_prt can read from `path` (as rvt-rs's `_native.capabilities`, in Python): its
    release, its build as written ("20240307_1300(x64)", "Development Build", or None), and
    whether rvt-rs reads its geometry. Raises UnsupportedFile when no release is found."""
    release = revit_release(path)
    if release is None:
        raise UnsupportedFile(f"{pathlib.Path(path).name}: no Revit release in its BasicFileInfo")
    text = _basic_file_info(path)
    m = re.search(r"Build: ([^)]*\))", text) or re.search(r"\d{8}_\d{4}\(x64\)", text)
    build = (m.group(1) if m.lastindex else m.group(0)) if m else ("Development Build" if "Development Build" in text else None)
    return {"revit_version": release, "build": build,
            "geometry": GEOMETRY_RELEASES[0] <= release <= GEOMETRY_RELEASES[1]}


@functools.cache
def _basic_file_info(path) -> str:
    """BasicFileInfo's text, else ""."""
    try:
        return olefile.OleFileIO(str(path)).openstream("BasicFileInfo").read().decode("utf-16le", "replace")
    except (OSError, *_MISREAD):  # absent, or a container olefile cannot follow
        return ""


@functools.cache
def open_file(path) -> "RevitFile":
    """One RevitFile per path, so its inflated partitions are cached once."""
    return RevitFile(str(path))
