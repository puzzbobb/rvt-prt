from rvt_prt.metrics.labels import label


def test_public_models_by_what_they_are():
    assert label("links/Snowdon Towers Sample Facades.rvt") == "Snowdon Facades"
    assert label("2019/rst_basic_sample_project.rvt") == "Autodesk structure sample (basic)"
    assert label("test02/TestProject2.rvt") == "test02"


def test_other_files_by_id_only():
    a = label("/somewhere/Client Job 42.rvt")
    assert a.startswith("model ") and "Client" not in a
    assert a == label("Client Job 42.rvt")  # the same wherever the file is
    assert label("3 files") == "3 files"
