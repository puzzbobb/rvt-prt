"""Unit tests for the schema registry (registry.py) and the object-graph decoder (objgraph.py)."""
import struct

from rvt_prt.core import objgraph, registry


def _name(s, width):
    b = s.encode()
    return struct.pack("<H" if width == 2 else "<I", len(b)) + b


def _field(name, raw, extra=b""):
    return _name(name, 4) + struct.pack("<I", raw) + extra


def _schema(opaque=True):
    # tag 12 Point {m_xyz: 3 x f64}; tag 13 Node {m_p: Point inline, m_next: pointer, m_n: i32}
    point = b"\0\0" + _name("Point", 2) + b"\0\0" + struct.pack("<II", 0, 1) + _field("m_xyz", 0x1007, struct.pack("<I", 3)) + struct.pack("<I", 0) * opaque
    node = (b"\0\0" + _name("Node", 2) + b"\0\0" + struct.pack("<II", 0, 3)
            + _field("m_p", 0x000e, struct.pack("<H", 12)) + _field("m_next", 0x010e) + _field("m_n", 0x0004) + struct.pack("<I", 0) * opaque)
    return point + node + bytes(8)


def test_registry_reads_classes_and_descriptors():
    r = registry.parse(_schema())
    assert [c.name for c in r.classes] == ["Point", "Node"]
    f = r.named("Node").fields
    assert (f[0].base, f[0].modifier, f[0].references) == (14, 0, [12])
    assert (f[1].base, f[1].modifier) == (14, 1)
    assert r.named("Point").fields[0].array_count == 3


def test_registry_reads_pre_2014_classes_without_opaque_counts():
    old, new = registry.parse(_schema(opaque=False)), registry.parse(_schema())
    assert [(c.name, [f.raw for f in c.fields]) for c in old.classes] == [(c.name, [f.raw for f in c.fields]) for c in new.classes]


def test_graph_follows_pointers_in_first_seen_order():
    r = registry.parse(_schema())
    node = lambda xyz, token, n: struct.pack("<3d", *xyz) + (struct.pack("<IH", token, 13) if token else struct.pack("<I", 0)) + struct.pack("<i", n)
    body = struct.pack("<H", 13) + node((1, 2, 3), 7, 10) + node((4, 5, 6), 0, 20)
    g = objgraph.Decoder(r).graph(body)
    assert [o.name for o in g.objects] == ["Node", "Node"]
    assert g.objects[0].fields["m_p"]["m_xyz"] == [1.0, 2.0, 3.0] and g.objects[1].fields["m_n"] == 20
    assert g.target(0, g.objects[0].fields["m_next"]) == 1 and g.objects[1].token == 7
