import json
import os
from pathlib import Path

from claude_voice_augmented.transcript import TextBlock, TranscriptReader

FIXTURE = Path(__file__).parent / "fixtures" / "spike.jsonl"


def assistant(uuid, *texts, sidechain=False):
    content = [{"type": "text", "text": t} for t in texts]
    return json.dumps(
        {"type": "assistant", "uuid": uuid, "isSidechain": sidechain,
         "message": {"role": "assistant", "content": content}},
        ensure_ascii=False,
    ) + "\n"


def append(path, text):
    with open(path, "ab") as fh:
        fh.write(text.encode() if isinstance(text, str) else text)


def test_reads_fixture_from_start():
    reader = TranscriptReader(FIXTURE, start_at_end=False)
    assert [b.text for b in reader.read_new()] == [
        'Running the first command to print "a".',
        'Running the second command to print "b".',
        'Running the third command to print "c".',
        "I ran the three commands one after another, and each printed its letter.",
    ]


def test_start_at_end_skips_existing_content(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(FIXTURE.read_text())
    reader = TranscriptReader(path)
    assert reader.read_new() == []
    append(path, assistant("new", "Fresh text."))
    assert reader.read_new() == [TextBlock("new", "Fresh text.")]


def test_partial_line_waits_for_newline(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    line = assistant("p", "Split line.")
    append(path, line[:20])
    assert reader.read_new() == []
    append(path, line[20:])
    assert reader.read_new() == [TextBlock("p", "Split line.")]


def test_multibyte_character_split_across_writes(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    raw = assistant("u", "Café ✓ done.").encode()
    cut = raw.index("✓".encode()) + 1  # in the middle of the 3-byte character
    append(path, raw[:cut])
    assert reader.read_new() == []
    append(path, raw[cut:])
    assert reader.read_new() == [TextBlock("u", "Café ✓ done.")]


def test_duplicates_sidechains_and_junk_are_skipped(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    append(path, assistant("a", "Once."))
    append(path, assistant("a", "Once."))
    append(path, assistant("s", "Subagent.", sidechain=True))
    append(path, "{not json\n")
    append(path, '"a string"\n')
    append(path, json.dumps({"type": "mystery", "uuid": "m"}) + "\n")
    append(path, assistant("e", ""))
    assert reader.read_new() == [TextBlock("a", "Once.")]


def test_multiple_text_blocks_in_one_entry_are_joined(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    append(path, assistant("m", "First.", "Second."))
    assert reader.read_new() == [TextBlock("m", "First.\n\nSecond.")]


def test_file_created_after_reader_is_read_from_start(tmp_path):
    path = tmp_path / "later.jsonl"
    reader = TranscriptReader(path)
    assert reader.read_new() == []
    assert not reader.deleted
    path.write_text(assistant("x", "Hello."))
    assert reader.read_new() == [TextBlock("x", "Hello.")]


def test_truncated_file_is_reopened_at_end(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(assistant("a", "A.") * 3)
    reader = TranscriptReader(path)
    path.write_text(assistant("b", "B."))  # shorter than before → truncated
    assert reader.read_new() == []
    append(path, assistant("c", "C."))
    assert reader.read_new() == [TextBlock("c", "C.")]


def test_replaced_file_is_reopened_at_end(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(assistant("a", "A."))
    reader = TranscriptReader(path)
    replacement = tmp_path / "new.jsonl"
    replacement.write_text(assistant("b", "B.") * 5)
    os.replace(replacement, path)
    assert reader.read_new() == []
    append(path, assistant("c", "C."))
    assert reader.read_new() == [TextBlock("c", "C.")]


def test_deleted_file_sets_deleted(tmp_path):
    path = tmp_path / "t.jsonl"
    path.touch()
    reader = TranscriptReader(path)
    path.unlink()
    assert reader.read_new() == []
    assert reader.deleted
