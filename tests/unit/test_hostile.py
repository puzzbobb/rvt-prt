"""Files made to hurt a reader: what bounds the memory and time a file can take, and what it
can make rvt-prt open or trust."""
import gzip
import os
import struct
import time
import types
import zlib

import pytest

from rvt_prt.core import container, objgraph, paths, registry
from rvt_prt.geometry import links
from rvt_prt.render import pool


def test_a_stream_that_inflates_past_the_limit_is_refused():
    bomb = zlib.compress(bytes(50 << 20), 9)  # 50 MB of zeros in about 50 KB
    assert len(bomb) < 100_000
    with pytest.raises(container.DamagedFile, match="inflates to more than"):
        container.inflate(bomb, 15, container.Budget(1 << 20))
    assert len(container.inflate(bomb, 15, container.Budget(64 << 20))) == 50 << 20


def test_the_limit_is_shared_by_a_file_s_streams():
    member = gzip.compress(bytes(600_000))
    budget = container.Budget(1_000_000)
    assert len(container.inflate_members(member, budget)[0]) == 600_000
    with pytest.raises(container.DamagedFile):
        container.inflate_members(member, budget)


def test_inflate_limit_follows_the_file_size(tmp_path):
    f = tmp_path / "small.rvt"
    f.write_bytes(bytes(1000))
    assert container.inflate_limit(f) == container.INFLATE_FLOOR
    f.write_bytes(bytes(4 << 20))
    assert container.inflate_limit(f) == container.INFLATE_RATIO * (4 << 20)


def _name(s, width):
    b = s.encode()
    return struct.pack("<H" if width == 2 else "<I", len(b)) + b


def _schema():
    # tag 12 Empty {}; tag 13 Bag {m_items: a counted array of Empty, inline}
    empty = b"\0\0" + _name("Empty", 2) + b"\0\0" + struct.pack("<II", 0, 0) + struct.pack("<I", 0)
    bag = (b"\0\0" + _name("Bag", 2) + b"\0\0" + struct.pack("<II", 0, 1)
           + _name("m_items", 4) + struct.pack("<I", 0x500e) + struct.pack("<H", 12) + struct.pack("<I", 0))
    return empty + bag + bytes(8)


def test_an_array_count_past_the_record_is_not_looped_over():
    dec = objgraph.Decoder(registry.parse(_schema()))
    few = struct.pack("<H", 13) + struct.pack("<I", 3)
    assert dec.graph(few).objects[0].fields["m_items"] == [{}, {}, {}]
    t = time.monotonic()
    with pytest.raises(ValueError):
        dec.graph(struct.pack("<H", 13) + struct.pack("<I", 0xFFFFFFFF))  # 4 billion elements of no bytes
    assert time.monotonic() - t < 1


def test_a_record_cut_short_is_a_value_error():
    dec = objgraph.Decoder(registry.parse(_schema()))
    with pytest.raises(ValueError):
        dec.graph(struct.pack("<H", 13) + b"\x01")


def test_a_misread_names_the_file_and_the_part(tmp_path):
    with pytest.raises(container.DamagedFile, match=r"model.rvt cannot be read: its element records"):
        with container.reading(tmp_path / "model.rvt", "element records"):
            struct.unpack_from("<I", b"", 0)


@pytest.mark.parametrize("name, ok", [
    ("Arch.rvt", True), ("Snowdon Towers Sample Architectural.rvt", True),
    ("../Arch.rvt", False), ("/etc/Arch.rvt", False), ("links/Arch.rvt", False),
    ("C:\\models\\Arch.rvt", False), ("..\\Arch.rvt", False), ("", False),
])
def test_a_linked_model_is_named_by_file_name_alone(name, ok):
    assert links.file_name_alone(name) is ok


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX ownership")
def test_a_cache_folder_others_can_write_to_is_not_trusted(tmp_path):
    mine = paths.private(tmp_path / "mine" / "cache")
    assert mine.stat().st_mode & 0o777 == 0o700 and paths.trusted(mine)
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    assert not paths.trusted(shared)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="forked sheet processes")
def test_a_sheet_that_takes_too_long_is_stopped(monkeypatch):
    monkeypatch.setattr(pool, "_render_worker", lambda task: time.sleep(60))
    monkeypatch.setattr(pool, "SHEET_TIMEOUT", 0.5)
    sheet = types.SimpleNamespace(number="A101")
    t = time.monotonic()
    results, failed = pool._attempt([(0, sheet, None, "pdf")], 1)
    assert not results and len(failed) == 1 and "over 0.5 s" in failed[0][1]
    assert time.monotonic() - t < 10


@pytest.mark.skipif(not hasattr(os, "fork"), reason="the limited print runs in a child process")
def test_a_print_out_of_memory_is_one_line(tmp_path, capsys, monkeypatch):
    from rvt_prt import cli

    def abort(_args):  # as the native extension does when an allocation fails at the limit
        os.abort()
    monkeypatch.setattr(cli, "_run", abort)
    assert cli.main(["print", str(tmp_path / "m.rvt"), "--memory-limit", "1"]) == 1
    assert capsys.readouterr().err.strip() == "rvt-prt: out of memory within --memory-limit 1 GB (the print was stopped)"
