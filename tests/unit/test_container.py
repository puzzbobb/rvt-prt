"""Unit tests for Revit CFB container reader and gzip stream decompression."""
import pathlib

from rvt_prt.core import container

SAMPLE_MODEL = pathlib.Path("oracle/Snowdon Towers Sample HVAC.rvt")

import pytest  # noqa: E402

pytestmark = pytest.mark.skipif(not SAMPLE_MODEL.exists(), reason="Snowdon model not present")


def test_open_file():
    assert SAMPLE_MODEL.exists(), f"Sample model not found at {SAMPLE_MODEL}"
    rf = container.open_file(str(SAMPLE_MODEL))
    assert isinstance(rf, container.RevitFile)


def test_partition_names():
    rf = container.open_file(str(SAMPLE_MODEL))
    pnames = rf.partition_names()
    assert len(pnames) > 0
    assert any("Partition" in p for p in pnames)


def test_inflated_stream():
    rf = container.open_file(str(SAMPLE_MODEL))
    pnames = rf.partition_names()
    first_partition = pnames[0]
    buf = rf.inflated(first_partition)
    assert isinstance(buf, (bytes, bytearray))
    assert len(buf) > 0
