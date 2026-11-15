import pytest

from rvt_prt.metrics import bench


@pytest.fixture(autouse=True, scope="session")
def _no_print_records(tmp_path_factory):
    """Prints made by the tests are not appended to bench/prints.jsonl (the print-time record)."""
    log = bench.LOG
    bench.LOG = tmp_path_factory.mktemp("bench") / "prints.jsonl"
    yield
    bench.LOG = log
