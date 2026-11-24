"""Model text drawn as its letters, not rvt-rs's box (skipped without Snowdon's site link)."""
import pathlib

import numpy as np
import pytest

from rvt_prt.geometry import linkgeom

LINK = pathlib.Path(__file__).resolve().parents[2] / "links" / "Snowdon Towers Sample Site.rvt"
pytestmark = pytest.mark.skipif(not LINK.exists(), reason="Snowdon links not present")
TEXT = 1348443  # the site's one model text


def _box(tag):
    lo, hi = np.array([-82.34, -72.16, -6.39]), np.array([-73.08, -71.81, -3.77])
    corners = np.array([[(hi if k & bit else lo)[a] for a, bit in enumerate((1, 2, 4))] for k in range(8)])
    return linkgeom.Item("IfcBuildingElementProxy", corners, linkgeom.BOX_FACES, "", 0, np.eye(4), "", tag)


def test_model_text_is_its_letters():
    other = _box(1)
    out = linkgeom._model_text(LINK, [_box(TEXT), other])
    text = out[0]
    assert out[1] is other
    assert text.category == -2000151  # Generic Models
    assert len(text.faces) > 1000
    # welded: the letters' outlines are sharp, the triangles inside their faces are not
    edges = linkgeom._sharp_edges(text.verts, text.faces)
    assert 600 < len(edges) < len(text.faces)
    lo, hi = text.verts.min(0), text.verts.max(0)
    assert (lo >= [-82.34, -72.17, -6.4]).all() and (hi <= [-73.08, -71.8, -3.76]).all()


def test_model_text_rvt_rs_left_out_stays_out():
    assert linkgeom._model_text(LINK, [_box(1)])[0].tag == 1
