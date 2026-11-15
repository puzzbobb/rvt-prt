"""Damaged copies of a small model: each lists its sheets or is refused as an UnsupportedFile,
never a traceback of another kind, and never for long. Skipped without the test oracle."""
import pathlib
import random
import time

import pytest

from rvt_prt import RevitModel, UnsupportedFile

MODEL = pathlib.Path(__file__).resolve().parents[2] / "oracle" / "testfamily" / "TestProject.rvt"
pytestmark = pytest.mark.skipif(not MODEL.exists(), reason="oracle/testfamily not present")


def _damaged(data, rng):
    b = bytearray(data)
    for _ in range(rng.choice((1, 3, 10, 100))):
        if not b:
            break
        i = rng.randrange(len(b))
        kind = rng.randrange(4)
        if kind == 0:
            b[i] ^= 1 << rng.randrange(8)
        elif kind == 1:
            b[i:i + 4] = b"\xff\xff\xff\xff"
        elif kind == 2:
            del b[i:i + rng.choice((1, 4, 512))]
        else:
            del b[max(i, 600):]
    return bytes(b)


@pytest.mark.parametrize("seed", range(40))
def test_a_damaged_file_lists_or_is_refused(seed, tmp_path):
    f = tmp_path / f"damaged{seed}.rvt"
    f.write_bytes(_damaged(MODEL.read_bytes(), random.Random(seed)))
    t = time.monotonic()
    try:
        assert isinstance(RevitModel(f).sheets, list)
    except UnsupportedFile as e:
        assert f.name in str(e) and "\n" not in str(e)
    assert time.monotonic() - t < 20
