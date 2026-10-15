from cc_narrator.focus import read_focus, write_focus


def test_focus_round_trip(tmp_path):
    assert read_focus(tmp_path) is None
    write_focus(tmp_path, "s1")
    assert read_focus(tmp_path) == "s1"
    write_focus(tmp_path, "s2")
    assert read_focus(tmp_path) == "s2"


def test_blank_focus_reads_as_none(tmp_path):
    (tmp_path / "focus").write_text("  \n")
    assert read_focus(tmp_path) is None
