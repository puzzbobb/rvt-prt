"""Schema classes and their serialization tags (port of rvt-rs `formats::schema_classes`, #154).

`Formats/Latest` is a sequence of class records separated by a zero u16. A
class's tag is not stored: it is its definition ordinal, 12 for the first
class and one more for each further definition, top-level or inline.
"""
import functools
import struct


FIRST_TAG = 12
MAX_NEST = 64


class SchemaError(Exception):
    pass


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.next_tag = FIRST_TAG
        self.classes = {}  # tag -> (name, base, version, field_count)

    def u16(self, at):
        if at + 2 > len(self.data):
            raise SchemaError(f"u16 past end at {at:#x}")
        return struct.unpack_from("<H", self.data, at)[0]

    def u32(self, at):
        if at + 4 > len(self.data):
            raise SchemaError(f"u32 past end at {at:#x}")
        return struct.unpack_from("<I", self.data, at)[0]

    def name(self, at, width):
        n = self.u16(at) if width == 2 else self.u32(at)
        start = at + width
        raw = self.data[start:start + n]
        if not 1 <= n <= 250 or len(raw) != n or not all(0x20 <= b < 0x7f for b in raw):
            raise SchemaError(f"bad name at {at:#x}")
        return raw.decode("ascii"), start + n

    def inline_class(self, at, reference, depth):
        if self.u16(at) != 0:
            raise SchemaError(f"inline pad at {at:#x}")
        tag, nxt = self.cls(at + 2, depth + 1)
        if tag != reference & 0x7FFF:
            raise SchemaError(f"inline tag mismatch at {at:#x}")
        return tag, nxt

    def class_ref(self, at, depth):
        reference = self.u16(at)
        if not reference & 0x8000:
            return True, at + 2
        _, nxt = self.inline_class(at + 2, reference, depth)
        return True, nxt

    def field_type(self, at, depth):
        if depth > MAX_NEST:
            raise SchemaError("types nest too deep")
        word = self.u32(at)
        at += 4
        kind, modifier = word & 0xFF, (word >> 8) & 0xFF
        if modifier & 0xF0 not in (0x00, 0x10, 0x50, 0x60):
            raise SchemaError(f"modifier {modifier:#x} at {at - 4:#x}")
        if modifier & 0xF0 == 0x10:
            if self.u32(at) > 65_536:
                raise SchemaError("array count")
            at += 4
        if kind == 0x0D:
            if self.data[at:at + 5] != b"\x01\x00\x00\x00\x20":
                raise SchemaError(f"array filler at {at:#x}")
            inner_ref, at = self.field_type(at + 5, depth + 1)
            if inner_ref:
                return self.class_ref(at, depth)
            return False, at
        if kind == 0x0E and modifier & 0x0F == 0:
            return self.class_ref(at, depth)
        return False, at

    def cls(self, at, depth):
        if depth > MAX_NEST:
            raise SchemaError("classes nest too deep")
        name, p = self.name(at, 2)
        tag = self.next_tag
        self.next_tag += 1
        reference = self.u16(p)
        p += 2
        base = None
        if reference & 0x8000:
            base, p = self.inline_class(p, reference, depth)
        elif reference:
            base = reference
        version, field_count = self.u32(p), self.u32(p + 4)
        p += 8
        if field_count > 2000:
            raise SchemaError("field count")
        fields = []
        for _ in range(field_count):
            fname, p = self.name(p, 4)
            _, p = self.field_type(p, depth)
            fields.append(fname)
        guids = self.u32(p)
        p += 4 + 16 * guids
        if guids > 60_000 or p > len(self.data):
            raise SchemaError("guid count")
        self.classes[tag] = (name, base, version, fields)
        return tag, p


def parse(data: bytes):
    r = _Reader(data)
    at = 0
    while at + 2 <= len(data):
        if r.u16(at) != 0:
            break
        at += 2
        if at >= len(data) or not any(data[at:]):
            break
        saved = (r.next_tag, dict(r.classes))
        try:
            _, at = r.cls(at, 0)
        except SchemaError:
            r.next_tag, r.classes = saved
            break
    return r.classes


@functools.cache
def classes(path: str):
    """tag -> (name, base tag, version, field names) for the file at `path`."""
    from . import container
    with container.reading(path, "class catalog (Formats/Latest)"):
        return parse(container.schema_bytes(path))


@functools.cache
def tags(path: str) -> dict[str, int]:
    return {name: tag for tag, (name, *_rest) in classes(path).items()}
