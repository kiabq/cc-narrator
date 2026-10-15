import subprocess

from claude_voice_augmented.label import git_branch, label_for, speak_branch, spell_id


def test_spell_id():
    assert spell_id("639b1bcb-4b66-4047") == "six-three-nine-bravo"
    assert spell_id("A0F2") == "alfa-zero-foxtrot-two"
    assert spell_id("ab-cd", length=3) == "alfa-bravo-charlie"


def test_speak_branch():
    assert speak_branch("feat/ABC-123-login-fix") == "feat ABC-123 login fix"
    assert speak_branch("fix_thing") == "fix thing"
    assert speak_branch("chore/update-deps") == "chore update deps"


def test_title_wins():
    assert label_for("639b", "Login refactor", "/x", lambda cwd: "feat/y") == "Login refactor"


def test_blank_title_is_ignored():
    assert label_for("639b", "   ", "/x", lambda cwd: "feat/y") == "feat y"


def test_branch_used_without_title():
    assert label_for("639b", None, "/x", lambda cwd: "feat/ABC-1-x") == "feat ABC-1 x"


def test_default_branch_falls_back_to_id():
    # Review Focus 2: many sessions on main must not all be called "main".
    assert label_for("639b", None, "/x", lambda cwd: "main") == "six-three-nine-bravo"


def test_no_cwd_or_branch_uses_id():
    assert label_for("639b") == "six-three-nine-bravo"
    assert label_for("639b", None, "/x", lambda cwd: None) == "six-three-nine-bravo"


def test_git_branch_reads_real_repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "topic", str(tmp_path)], check=True)
    assert git_branch(str(tmp_path)) == "topic"


def test_git_branch_outside_repo(tmp_path):
    assert git_branch(str(tmp_path)) is None
    assert git_branch(str(tmp_path / "missing")) is None
