"""Element records as object graphs, decoded from the schema (registry.py). Port of rvt-rs
`native_segments.rs`, the record framing of `native_document.rs` and the graph decoder of
`native_parameters.rs` (Apache-2.0; the native object-graph reader was contributed upstream in rvt-rs #255).

- A `Partitions/NN` stream (page checksums stripped) is 8 bytes, then markers, each a u16 class
  tag: ContentMarker (`u32 token`, then `u32 count` for a plain one, or `u16 ContentKey tag ·
  u32 count · 16-byte key` for a keyed one; token 0 and count 0xFFFFFFFF end the stream),
  SegmentMarker (`u32 flags · u32 objects · u32 size · u32 raw bytes`, then `u64 channel` and
  `size - 8` bytes of gzip; flag 1 continues the previous segment, flag 2 continues into the
  next), SegmentCheckback (`u32` the last segment's size) and SignatureMarker (bytes and a
  UTF-16 string). Keyed groups are embedded content (another document's: a loaded family's), read by
  `embedded_bodies`.
- A group of channel 102 or 103 is records `u64 id · u32 · u32 length · body · u32 length`.
  Channel 103 holds each element's saved graphics.
- A body is an object graph: the root's u16 class tag, then its fields as the schema lays them
  out (base class first). A pointer field is `u32 token` and, when non-zero and not external,
  a u16 class tag; the objects it points to follow in first-seen order, each read the same way
  with the token naming it (0xFFFFFFFF: an owned, unshared object). The whole body is consumed.

Values: bool, ints, floats as Python scalars; strings as str; arrays and composites as lists;
inline objects as dicts keyed by field name (`Class::field` where a lineage repeats a name);
pointers as Ptr(token, class tag, offset). An object is Obj(tag, name, token, fields).
"""
import struct
from collections import namedtuple

from . import memory

Ptr = namedtuple("Ptr", "token tag offset")
Obj = namedtuple("Obj", "tag name token fields")

_U16, _U32, _I16, _I32, _I64, _F32, _F64 = (struct.Struct(f).unpack_from for f in ("<H", "<I", "<h", "<i", "<q", "<f", "<d"))


ES_ENTITY = -1  # the pointer queue's tag for an Extensible Storage entity
# An array's count is read from the record: one greater than the bytes left (and than _MANY, for
# elements that take no bytes) is not Revit's, and would be looped over (4 billion times) as read.
_MANY = 1 << 16


class Graph:
    """objects: [Obj], root first; edges: {(source object index, pointer offset): target index}."""
    __slots__ = ("objects", "edges", "_tokens", "partial")

    def __init__(self, objects, edges):
        self.objects, self.edges = objects, edges
        self._tokens = None
        self.partial = False  # True when reading stopped at a class the catalog lacks

    def target(self, source, ptr):
        """The object index a Ptr in object `source`'s fields points to, or None. A pointer saved
        without its class (B-rep topology links: an EdgeLoop's or Edge's next and face) has no
        edge and names its target by token alone (rvt-rs PointerIndex::resolve)."""
        if not isinstance(ptr, Ptr) or not ptr.token:
            return None
        hit = self.edges.get((source, ptr.offset))
        if hit is not None or ptr.token == 0xFFFFFFFF:
            return hit
        if self._tokens is None:
            self._tokens = {}
            for i, o in enumerate(self.objects):
                self._tokens.setdefault(o.token, i)
        return self._tokens.get(ptr.token)


class Decoder:
    """Compiled per-class field readers for one registry."""

    def __init__(self, registry):
        self.reg = registry
        self.plans = {}
        self.compiled = {}
        self.names = {}  # {class tag: its name, None for one the catalog lacks (graph)}

    def plan(self, tag):
        p = self.plans.get(tag)
        if p is None:
            lineage, t = [], tag
            while t >= 12:
                c = self.reg.cls(t)
                if c is None:
                    raise ValueError(f"unknown class {t}")
                if len(lineage) > len(self.reg.classes):
                    raise ValueError(f"class {tag} is its own ancestor")
                lineage.append(c)
                t = c.parent
            counts = {}
            for c in lineage:
                for f in c.fields:
                    if not f.flags & 2:
                        counts[f.name] = counts.get(f.name, 0) + 1
            p = []
            for c in reversed(lineage):
                for f in c.fields:
                    if f.flags & 2:
                        continue  # transient (rvt-rs: measured on VWall)
                    if f.flags and not (c.name == "VarExpr" and f.name == "m_refCt" and f.flags == 4):
                        raise ValueError(f"unsupported field flags {c.name}.{f.name}: {f.flags}")
                    key = f"{c.name}::{f.name}" if counts[f.name] > 1 else f.name
                    if c.name == "VarSketchObj" and f.name == "m_params" and f.base == 14 and f.modifier == 0x54:
                        f = type(f)(f.name, f.raw, f.base, 0x51, f.flags, f.array_count, f.references, f.nested)
                    p.append((key, self.reader(f, c.name)))
            self.plans[tag] = p
        return p

    def reader(self, f, owner=""):
        """A function (state, pos) -> (value, pos) for field descriptor f."""
        base, mod = f.base, f.modifier
        if owner == "ClassDefinitionRef" and f.name == "m_ref" and base == 10 and mod == 0:
            return lambda st, pos: ({"class_tag": _U16(st.body, pos)[0]}, pos + 2)
        if owner == "ESEntity" and f.name == "m_blob" and base == 14 and mod == 1:
            # an Extensible Storage entity (rvt-rs entity_pointer): i32 0 (absent) or -1 and the
            # schema's GUID; the entity's fields follow in the pointer queue, laid out by that
            # schema (an ES schema element), not by a catalog class
            def entity(st, pos):
                disc = struct.unpack_from("<i", st.body, pos)[0]
                if disc != -1:
                    return {"discriminator": disc}, pos + 4
                guid = bytes(st.body[pos + 4:pos + 20])
                st.pending.append((0xFFFFFFFF, ES_ENTITY, pos))
                return {"discriminator": -1, "schema_guid": guid}, pos + 20
            return entity
        if base == 14 and 1 <= mod <= 3:
            external = mod == 3

            def ptr(st, pos):
                token = _U32(st.body, pos)[0]
                if token and not external:
                    tag = _U16(st.body, pos + 4)[0]
                    st.pending.append((token, tag, pos))
                    return Ptr(token, tag, pos), pos + 6
                return Ptr(token, None, pos), pos + 4
            return ptr
        if base == 8 and mod == 0x60:
            def text(st, pos):
                n = _U32(st.body, pos)[0]
                return st.body[pos + 4:pos + 4 + 2 * n].decode("utf-16-le"), pos + 4 + 2 * n
            return text
        if mod in (0x10, 0x11, 0x12, 0x13, 0x50, 0x51, 0x52, 0x53):
            fixed = mod < 0x50
            item = type(f)(f.name, f.raw, base, mod & 0xF, f.flags, None, f.references, f.nested)
            if mod & 0xF == 0 and base in self._SCALAR:  # runs of scalars: one unpack
                code = self._SCALAR[base]
                if fixed:
                    s = struct.Struct(f"<{f.array_count}{code}")
                    return lambda st, pos: (list(s.unpack_from(st.body, pos)), pos + s.size)
                size = struct.calcsize(code)

                def scalars(st, pos):
                    n = _U32(st.body, pos)[0]
                    return list(struct.unpack_from(f"<{n}{code}", st.body, pos + 4)), pos + 4 + size * n
                return scalars
            one = self.reader(item, owner)
            count = f.array_count

            def array(st, pos):
                if fixed:
                    n = count
                else:
                    n = _U32(st.body, pos)[0]
                    pos += 4
                    if n > _MANY and n > len(st.body) - pos:
                        raise ValueError(f"array of {n} in {len(st.body) - pos} bytes")
                out = []
                for _ in range(n):
                    v, pos = one(st, pos)
                    out.append(v)
                return out, pos
            return array
        if mod == 0:
            if base == 1:
                return lambda st, pos: (st.body[pos] != 0, pos + 1)
            if base == 2:
                return lambda st, pos: (st.body[pos], pos + 1)
            if base == 3:
                return lambda st, pos: (_I16(st.body, pos)[0], pos + 2)
            if base == 4:
                return lambda st, pos: (_I32(st.body, pos)[0], pos + 4)
            if base == 5:
                return lambda st, pos: (_U32(st.body, pos)[0], pos + 4)
            if base == 6:
                return lambda st, pos: (_F32(st.body, pos)[0], pos + 4)
            if base == 7:
                return lambda st, pos: (_F64(st.body, pos)[0], pos + 8)
            if base == 9:
                return lambda st, pos: (bytes(st.body[pos:pos + 16]), pos + 16)
            if base == 11:
                return lambda st, pos: (_I64(st.body, pos)[0], pos + 8)
            if base == 13:
                return self.reader(f.nested, owner)
            if base == 14:
                tag = f.references[0]
                return lambda st, pos: self.read_class(st, tag, pos)
        raise ValueError(f"unsupported field {f.name}: base {base} modifier {mod:#x}")

    _SCALAR = {1: "?", 2: "B", 3: "h", 4: "i", 5: "I", 6: "f", 7: "d", 11: "q"}

    def read_class(self, st, tag, pos):
        fn = self.compiled.get(tag)
        if fn is None:
            fn = self._compile(tag)
        return fn(st, pos)

    def _compile(self, tag):
        """A generated reader for class `tag`: runs of fixed-size scalars (and fixed f64 arrays)
        read with one struct unpack, pointers read inline, inline classes and arrays of classes or
        pointers through the classes' own generated readers; other fields through reader functions."""
        self.compiled[tag] = None  # in progress (an inline class cannot contain itself)
        plan = self.plan(tag)  # first: it refuses a class the catalog lacks or one that is its own ancestor
        lineage, t = [], tag
        while t >= 12:
            c = self.reg.cls(t)
            lineage.append(c)
            t = c.parent
        raw = [f for c in reversed(lineage) for f in c.fields if not f.flags & 2]
        fields = []  # (key, kind, data)
        for (key, read), f in zip(plan, raw):
            if f.modifier == 0 and f.base in self._SCALAR:
                fields.append((key, "s", (self._SCALAR[f.base], None)))
            elif f.modifier == 0x10 and f.base == 7 and f.array_count:
                fields.append((key, "s", (f"{f.array_count}d", (f.array_count,))))
            elif (f.modifier == 0x10 and f.base == 13 and f.array_count and f.nested is not None
                  and f.nested.base == 7 and f.nested.modifier == 0x10 and f.nested.array_count):
                fields.append((key, "s", (f"{f.array_count * f.nested.array_count}d", (f.array_count, f.nested.array_count))))
            elif f.base == 14 and f.modifier in (1, 2) and read.__name__ == "ptr":
                fields.append((key, "p", None))
            elif f.base == 14 and f.modifier == 3 and read.__name__ == "ptr":
                fields.append((key, "x", None))
            elif f.base == 14 and f.modifier == 0 and read.__name__ == "<lambda>" and f.references:
                fields.append((key, "c", f.references[0]))
            elif f.base == 14 and f.modifier in (0x50, 0x51, 0x52, 0x10, 0x11, 0x12) and f.references:
                fields.append((key, "a", (f.modifier, f.array_count, f.references[0])))
            elif f.base == 14 and f.modifier in (0x50, 0x51, 0x52, 0x53, 0x10, 0x11, 0x12, 0x13) and f.modifier & 0xF:
                fields.append((key, "a", (f.modifier, f.array_count, None)))
            else:
                fields.append((key, "r", read))
        for key, kind, data in fields:  # nested classes first
            ctag = data if kind == "c" else data[2] if kind == "a" and data[0] & 0xF == 0 else None
            if ctag is not None and ctag not in self.compiled:
                self._compile(ctag)
        env = {"_S": {}, "_R": {}, "_C": self.compiled, "_U32": _U32, "_U16": _U16, "Ptr": Ptr}
        L = ["def read(st, pos):", "    body = st.body", "    pend = st.pending", "    out = {}"]
        i = 0
        while i < len(fields):
            key, kind, data = fields[i]
            if kind == "s":
                j, fmt = i, "<"
                while j < len(fields) and fields[j][1] == "s":
                    fmt += fields[j][2][0]
                    j += 1
                st_ = struct.Struct(fmt)
                env["_S"][i] = st_
                L += [f"    v = _S[{i}].unpack_from(body, pos)", f"    pos += {st_.size}"]
                k = 0
                for key2, _k, (f1, shape) in fields[i:j]:
                    if shape is None:
                        L.append(f"    out[{key2!r}] = v[{k}]")
                        k += 1
                    elif len(shape) == 1:
                        L.append(f"    out[{key2!r}] = list(v[{k}:{k + shape[0]}])")
                        k += shape[0]
                    else:
                        n, m = shape
                        rows = ", ".join(f"list(v[{k + a * m}:{k + (a + 1) * m}])" for a in range(n))
                        L.append(f"    out[{key2!r}] = [{rows}]")
                        k += n * m
                i = j
                continue
            if kind == "p":
                L += ["    t = _U32(body, pos)[0]",
                      "    if t:",
                      "        g = _U16(body, pos + 4)[0]; pend.append((t, g, pos))",
                      f"        out[{key!r}] = Ptr(t, g, pos); pos += 6",
                      "    else:",
                      f"        out[{key!r}] = Ptr(0, None, pos); pos += 4"]
            elif kind == "x":
                L += [f"    out[{key!r}] = Ptr(_U32(body, pos)[0], None, pos); pos += 4"]
            elif kind == "c":
                L.append(f"    out[{key!r}], pos = _C[{data}](st, pos)")
            elif kind == "a":
                mod, count, ctag = data
                L.append(f"    n = {count}" if mod < 0x50 else "    n = _U32(body, pos)[0]; pos += 4")
                if mod >= 0x50:
                    L.append(f"    if n > {_MANY} and n > len(body) - pos: raise ValueError('array count past the record')")
                L.append("    lst = []")
                if mod & 0xF == 0:
                    L += [f"    fn = _C[{ctag}]", "    for _ in range(n):", "        x, pos = fn(st, pos); lst.append(x)"]
                elif mod & 0xF == 3:
                    L += ["    for _ in range(n):", "        lst.append(Ptr(_U32(body, pos)[0], None, pos)); pos += 4"]
                else:
                    L += ["    for _ in range(n):",
                          "        t = _U32(body, pos)[0]",
                          "        if t:",
                          "            g = _U16(body, pos + 4)[0]; pend.append((t, g, pos)); lst.append(Ptr(t, g, pos)); pos += 6",
                          "        else:",
                          "            lst.append(Ptr(0, None, pos)); pos += 4"]
                L.append(f"    out[{key!r}] = lst")
            else:
                env["_R"][i] = data
                L.append(f"    out[{key!r}], pos = _R[{i}](st, pos)")
            i += 1
        L.append("    return out, pos")
        exec("\n".join(L), env)  # noqa: S102 - generated from the file's own schema, no external text
        self.compiled[tag] = env["read"]
        return env["read"]

    def graph(self, body):
        """The body's object graph (Graph). A body that does not read as its classes lay it out
        (a count or an offset past its end, a class that cannot be compiled) is a ValueError,
        whatever reading it ran into."""
        try:
            return self._graph(body)
        except ValueError:
            raise
        except (struct.error, IndexError, KeyError, TypeError, AttributeError, OverflowError, RecursionError) as e:
            raise ValueError(f"record does not decode ({type(e).__name__}: {str(e)[:80]})") from e

    def _graph(self, body):
        st = _State(body)
        pending = st.pending
        objects, edges, shared = [], {}, {}
        queue = [(0, _U16(body, 0)[0])]
        pos, qi = 2, 0
        partial = False
        names, compiled = self.names, self.compiled
        while qi < len(queue):
            token, tag = queue[qi]
            qi += 1
            name = names.get(tag, False)
            if name is False:
                c = self.reg.cls(tag) if tag != ES_ENTITY else None
                name = names[tag] = c.name if c is not None else None
            if name is None:
                # an Extensible Storage entity (its layout is its ES schema's, not read here) or
                # a class the catalog does not describe: its length is unknown, so the objects
                # after it are not read; those before it are whole
                partial = True
                break
            start = len(pending)
            fn = compiled.get(tag) or self._compile(tag)
            fields, pos = fn(st, pos)
            src = len(objects)
            objects.append(Obj(tag, name, token, fields))
            for ptoken, ptag, offset in pending[start:]:
                hit = shared.get(ptoken)
                if hit is not None:
                    index = hit
                else:
                    index = len(queue)
                    queue.append((ptoken, ptag))
                    if ptoken != 0xFFFFFFFF:
                        shared[ptoken] = index
                edges[(src, offset)] = index
        if pos != len(body) and not partial:
            raise ValueError(f"graph leaves {len(body) - pos} bytes")
        g = Graph(objects, edges)
        g.partial = partial
        return g


class _State:
    __slots__ = ("body", "pending")

    def __init__(self, body):
        self.body = body
        self.pending = []


def segments(prepared, registry, want=lambda channel, keyed: True, budget=None):
    """(channel, key, group bytes) of every continuation group of a page-stripped partition that
    `want(channel, keyed)`: key None for an unkeyed group, else the ContentKey's 16 bytes (a keyed
    group is another document's content: a loaded family's). The others are not decompressed.
    What is decompressed counts against `budget` (container.Budget, the file's inflate limit)."""
    from .container import inflate
    if any(registry.named(n) is None for n in ("ContentMarker", "ContentKey", "SegmentMarker", "SegmentCheckback")):
        from .container import UnsupportedFile  # Revit 2008-2011: partitions framed another way
        raise UnsupportedFile("its partitions have no segment markers")
    tag = lambda n: registry.named(n).tag
    content, content_key, segment, checkback = tag("ContentMarker"), tag("ContentKey"), tag("SegmentMarker"), tag("SegmentCheckback")
    signature = registry.named("SignatureMarker").tag if registry.named("SignatureMarker") else None
    pos, keyed, key, active = 8, False, None, None
    n = len(prepared)
    while pos + 2 <= n:
        marker = _U16(prepared, pos)[0]
        pos += 2
        if marker == content:
            token = _U32(prepared, pos)[0]
            pos += 4
            if token == 0:
                count = _U32(prepared, pos)[0]
                pos += 4
                keyed = False
                if count == 0xFFFFFFFF:
                    return
            else:
                if token != 0xFFFFFFFF or _U16(prepared, pos)[0] != content_key:
                    raise ValueError("content key pointer")
                key = bytes(prepared[pos + 6:pos + 22])
                pos += 2 + 4 + 16
                keyed = True
        elif marker == segment:
            flags, _count, size, _raw = struct.unpack_from("<IIII", prepared, pos)
            pos += 16
            if size == 0:
                continue
            channel = struct.unpack_from("<Q", prepared, pos)[0]
            if not flags & 1:
                active = (channel, [] if want(channel, keyed) else None)
            if active is None:
                raise ValueError(f"segment at {pos - 18} continues none")
            if active[1] is not None:
                active[1].append(inflate(prepared[pos + 8:pos + size], 31, budget))
            pos += size
            if not flags & 2:
                if active[1] is not None:
                    yield active[0], key if keyed else None, b"".join(active[1])
                active = None
        elif marker == checkback:
            pos += 4
        elif marker == signature:
            count = _U32(prepared, pos)[0]
            pos += 4 + count
            units = _U32(prepared, pos)[0]
            pos += 4 + 2 * units
        else:
            raise ValueError(f"partition marker {marker} at {pos - 2}")


def records(group):
    """(id, body) of a channel 102 / 103 group. A record is `u64 id · u32 checksum · u32 n`
    (2024 on), or `i32 id · u32 checksum · u32 n` before (Revit 2023 and earlier),
    then n bytes of body and the u32 n echo. The checksum is an
    Adler-32, whose halves are below 65521, so the u32 at +4 is the wide id's high half exactly
    when it reads 0 or 0xFFFFFFFF. A narrow id of -1 is given as 2^64 - 1, as the wide one is."""
    pos, n = 0, len(group)
    view = memoryview(group)
    while pos < n:
        if _U32(group, pos + 4)[0] in (0, 0xFFFFFFFF):
            eid = struct.unpack_from("<Q", group, pos)[0]
            length = _U32(group, pos + 12)[0]
            start = pos + 16
        else:
            eid = _U32(group, pos)[0]
            eid = (1 << 64) - 1 if eid == 0xFFFFFFFF else eid
            length = _U32(group, pos + 8)[0]
            start = pos + 12
        yield eid, view[start:start + length]
        pos = start + length + 4


@memory.per_file
def _bodies(path):
    """The file's element records, every partition read and decompressed once for both
    channel_bodies and embedded_bodies (a cold Snowdon link read them four times, 5 s of
    Architectural's 48): ({102: {id: body}, 103: {...}} of the unkeyed groups, {content key: {id:
    body}} of the keyed channel-102 groups). Channel 101 and keyed 103, which nothing reads, are
    not decompressed."""
    from . import container, registry as reg
    rf = container.open_file(path)
    registry = reg.load(str(path))
    plain, keyed = {102: {}, 103: {}}, {}
    want = lambda ch, k: ch == 102 or (ch == 103 and not k)
    budget = container.Budget(container.inflate_limit(path))
    with container.reading(path, "element records (Partitions)"):
        for name in sorted(rf.partition_names(), key=lambda n: int(n.split("/")[1])):
            prepared = container.strip_pages(rf.read_stream(name))
            for ch, key, group in segments(prepared, registry, want, budget):
                out = plain[ch] if key is None else keyed.setdefault(key, {})
                for eid, body in records(group):
                    if key is None or eid != (1 << 64) - 1:
                        out[eid] = bytes(body)
    return plain, keyed


def channel_bodies(path, channel=103):
    """{element id: record body} of `channel` (102 or 103) across the file's partitions, read once
    per file (shared: not to be changed; a cold Snowdon link read them 23 times, 10.7 s of its 65).
    Where an id has records in several partitions, the highest-numbered partition's (rvt-rs routes
    each element to its current partition from its stored revision; this simpler rule is checked
    against rvt-rs on Snowdon's links: see tests)."""
    return _bodies(path)[0][channel]


def embedded_bodies(path, channel=102):
    """{content key: {element id: record body}} of channel 102 in the file's keyed groups: the
    documents of loaded families, embedded whole (their own elements, views, dimensions, nested
    instances), framed as the project's own records. Ids are unique across the file, but for a
    record of id 2^64 - 1 every group holds (left out). Shared, as channel_bodies'."""
    if channel != 102:
        raise ValueError(f"embedded channel {channel}: only 102 is read")
    return _bodies(path)[1]


@memory.per_file
def decoder(path):
    """The Decoder of a file's own class catalog."""
    from . import registry
    return Decoder(registry.load(str(path)))


def class_name(dec, body):
    """The class name of a record body's root object (None when not in the catalog)."""
    if len(body) < 2:
        return None
    c = dec.reg.cls(_U16(body, 0)[0])
    return c.name if c is not None else None


def elements(path, classes=None, bodies=None):
    """(element id, Graph) of the file's element records (channel 102) whose root class is one of
    `classes` (names, or name prefixes ending in "*"; None for every record), in id order.
    Records that do not decode are skipped. `bodies` reuses channel_bodies(path, 102)."""
    dec = decoder(path)
    exact = {c for c in classes or () if not c.endswith("*")}
    prefixes = tuple(c[:-1] for c in classes or () if c.endswith("*"))
    if bodies is None:
        bodies = channel_bodies(path, 102)
        index = _class_index(path)
        ids = sorted(eid for name, eids in index.items()
                     if classes is None or name in exact or name.startswith(prefixes or ("\0",)) for eid in eids)
        selected = ((eid, bodies[eid]) for eid in ids)
    else:
        selected = ((eid, body) for eid, body in sorted(bodies.items())
                    if (name := class_name(dec, body)) is not None
                    and (classes is None or name in exact or name.startswith(prefixes or ("\0",))))
    for eid, body in selected:
        try:
            yield eid, dec.graph(body)
        except Exception:  # a class layout the catalog does not describe as stored
            continue


@memory.per_file
def _class_index(path):
    """{class name: [element id]} of the file's channel-102 records (class_name of each), for
    elements, which otherwise reads the class of every record on each call (Snowdon
    Architectural: 50,530 records, some 25 calls in building its caches)."""
    dec, out = decoder(path), {}
    for eid, body in channel_bodies(path, 102).items():
        name = class_name(dec, body)
        if name is not None:
            out.setdefault(name, []).append(eid)
    return out


def root(path, body):
    """The fields of a record body's root object alone (its pointers unread), or None."""
    dec = decoder(path)
    try:
        return dec.read_class(_State(body), _U16(body, 0)[0], 2)[0]
    except Exception:
        return None


def ref(v):
    """An ElementId field's id (None for -1, absent or not an id)."""
    x = v.get("m_id", {}).get("m_id64") if isinstance(v, dict) else None
    if x is None and isinstance(v, dict):
        x = v.get("m_id64")
    return x if x is not None and x >= 0 else None
