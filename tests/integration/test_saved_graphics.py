"""The saved-graphics reader on Snowdon's architectural link (skipped without the file). The values
were checked object by object against rvt-rs's reader (examples/dump_saved_graphics.rs): all
3,915 graphs of the 14 plan sheets' family instances and symbols are identical."""
import pathlib

import numpy as np
import pytest

from rvt_prt.elements import savedgraphics

LINK = pathlib.Path(__file__).resolve().parents[2] / "links" / "Snowdon Towers Sample Architectural.rvt"
pytestmark = pytest.mark.skipif(not LINK.exists(), reason="Snowdon links not present")


def test_door_instance_names_its_regenerated_symbol():
    link = savedgraphics.Link(LINK)
    sym, m = link.instance(631497)
    assert sym == 2162734  # Revit's DXF block "Door-Passage-Single-Flush - 36" x 84"-2162734-..."
    assert np.allclose(m[:3, 3], [-100.1458333, 21.875, -5.9166667], atol=1e-6)
    g = link.graph(sym)
    assert len(g.objects) == 1240
    arcs = [o for o in g.objects if o.name == "GArc"]
    assert any(abs(a.fields["m_radius"] - 3.0) < 1e-9 for a in arcs)  # the 36" type's swing


def test_door_symbol_primitives():
    prims = savedgraphics.Link(LINK).primitives(2162734)
    solids = [p for p in prims if p.kind == "solid"]
    assert sum(len(p.points) for p in solids) == 292  # every B-rep Edge once
    assert any(c[0] == "dir" and c[1] == 6 for p in prims for c in p.conds)
