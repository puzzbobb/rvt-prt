"""The class registry of `Formats/Latest` with full field descriptors, for schema-driven object
decoding (objgraph.py). Port of rvt-rs `src/schema_registry.rs` (Apache-2.0).

`Formats/Latest` is a sequence of class definitions: `u16 0 · u16 n · name`, a parent reference,
a u32 version-like word, `u32 n` fields, then `u32 n` opaque 16-byte entries (absent before
Revit 2014: those files have no such count, parsed by `opaque=False`); a class's tag is
its definition ordinal plus 12. A reference is a u16 tag whose high bit introduces an inline
definition. A field is `u32 n · name · u32 descriptor` (base type in the low byte, modifier in
the next, flags above), a u32 count for fixed arrays (modifiers 16..19), a class reference for
class-typed values (base 14 with modifier 0, 16 or 80), and for base 13 (composite) a nested
field. The stream ends with 8 zero bytes.

schema.py keeps the older names-only reading used elsewhere.
"""
import functools
import struct
from dataclasses import dataclass, field


@dataclass
class Field:
    name: str
    raw: int  # the u32 descriptor
    base: int
    modifier: int
    flags: int
    array_count: int | None
    references: list  # [class tag]
    nested: "Field | None" = None


@dataclass
class Class:
    tag: int
    name: str
    parent: int
    fields: list = field(default_factory=list)


class Registry:
    def __init__(self, classes):
        self.classes = classes  # index = tag - 12
        self.by_name = {}
        for c in classes:
            self.by_name.setdefault(c.name, c)

    def cls(self, tag):
        i = tag - 12
        return self.classes[i] if 0 <= i < len(self.classes) else None

    def named(self, name):
        return self.by_name.get(name)


class _Reader:
    def __init__(self, data, opaque=True):
        self.d = data
        self.pos = 0
        self.classes = []
        self.opaque = opaque

    def u16(self):
        v = struct.unpack_from("<H", self.d, self.pos)[0]
        self.pos += 2
        return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.pos)[0]
        self.pos += 4
        return v

    def text(self, n):
        if not 1 <= n <= 4096:
            raise ValueError(f"schema name length {n} at {self.pos}")
        t = self.d[self.pos:self.pos + n].decode("utf-8")
        self.pos += n
        return t

    def reference(self):
        at = self.pos
        raw = self.u16()
        tag = raw & 0x7FFF
        if raw & 0x8000:
            if tag != 12 + len(self.classes):
                raise ValueError(f"nonsequential schema definition {tag} at {at}")
            self.definition()
        elif tag >= 12 + len(self.classes):
            raise ValueError(f"forward schema reference {tag} at {at}")
        return tag

    def field(self, depth):
        if depth > 64:
            raise ValueError("schema field recursion")
        name = self.text(self.u32())
        raw = self.u32()
        base, modifier, flags = raw & 0xFF, (raw >> 8) & 0xFF, raw >> 16
        if not (1 <= base <= 14 and modifier in (0, 1, 2, 3, 4, 16, 17, 18, 19, 80, 81, 82, 83, 84, 96)):
            raise ValueError(f"schema descriptor {raw:#x} at {self.pos - 4}")
        count = self.u32() if 16 <= modifier <= 19 else None
        refs = []
        if base == 14 and modifier in (0, 16, 80):
            refs.append(self.reference())
        nested = None
        if base == 13:
            nested = self.field(depth + 1)
            refs.extend(nested.references)
            for _ in range(1, count or 1):
                for expected in nested.references:
                    if self.reference() != expected:
                        raise ValueError("schema composite repeated reference mismatch")
                    refs.append(expected)
            if count is None and nested.base == 14 and nested.array_count is not None:
                for expected in nested.references:  # Revit 2018's SiteSurface.m_facets (rvt-rs #421)
                    if self.reference() != expected:
                        raise ValueError("schema composite trailing reference mismatch")
                    refs.append(expected)
        return Field(name, raw, base, modifier, flags, count, refs, nested)

    def definition(self):
        if self.u16() != 0:
            raise ValueError(f"schema definition header at {self.pos - 2}")
        name = self.text(self.u16())
        ordinal = len(self.classes)
        self.classes.append(None)  # registered before its recursive definitions
        parent = self.reference()
        self.u32()  # version-like word
        fields = [self.field(0) for _ in range(self.u32())]
        if self.opaque:
            n = self.u32()
            self.pos += 16 * n  # opaque entries
        self.classes[ordinal] = Class(12 + ordinal, name, parent, fields)


def parse(data: bytes) -> Registry:
    try:
        return _parse(data, True)
    except (ValueError, struct.error, UnicodeDecodeError) as e:
        try:
            return _parse(data, False)
        except (ValueError, struct.error, UnicodeDecodeError):
            raise e from None


def _parse(data, opaque):
    r = _Reader(data, opaque)
    while len(data) - r.pos > 8:
        r.definition()
    if data[r.pos:r.pos + 8] != bytes(8) or r.pos + 8 != len(data):
        raise ValueError("schema stream terminator")
    for c in r.classes:
        # ElementId's value: `i32 m_id` before Revit 2024, `i64 m_id64` since; one name for both
        if c.name in _ID_CLASSES and [f.name for f in c.fields] == ["m_id"]:
            c.fields[0].name = "m_id64"
    return Registry(r.classes)


_ID_CLASSES = ("Identifier", "ForeignElemRef", "OriginalElementId", "CentralElementId")


@functools.cache
def load(path: str) -> Registry:
    """The registry of the file at `path`."""
    from . import container
    with container.reading(path, "class catalog (Formats/Latest)"):
        return parse(container.schema_bytes(path))
