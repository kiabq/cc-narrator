import pytest

from claude_voice_augmented.prose import chunk, sentences, to_speech


@pytest.mark.parametrize(
    ("markdown", "speech"),
    [
        ("", ""),
        ("Hello **world**.", "Hello world."),
        ("an *emphasized* word and ~~gone~~ text", "an emphasized word and gone text"),
        ("snake_case_name stays", "snake_case_name stays"),
        ("Use `cva doctor` first.", "Use cva doctor first."),
        ("Call `__init__` here.", "Call __init__ here."),
        ("Before\n```python\nprint('x')\n```\nAfter.", "Before After."),
        ("~~~\ncode\n~~~\nDone.", "Done."),
        ("```\nunclosed code\nmore", ""),
        ("# Title\nBody.", "Title. Body."),
        ("## Done!", "Done!"),
        ("- one\n- two.", "one. two."),
        ("1. first\n2) second", "first. second."),
        ("> quoted line", "quoted line"),
        ("---\nText.", "Text."),
        ("See [the docs](https://x.com/a).", "See the docs."),
        ("![diagram](https://x.com/d.png) shows it.", "diagram shows it."),
        ("Go to https://example.com/x now.", "Go to a link now."),
        ("Edit `/Users/box/dev/app/src/main.py:12`.", "Edit main.py:12."),
        ("Open src/app.py.", "Open app.py."),
        ("~/x/y/file.txt is here", "file.txt is here"),
        ("Both and/or work.", "Both and/or work."),
        ("Half is 1/2.", "Half is 1/2."),
        (
            "| Name | Value |\n|---|:---:|\n| a | 1 |\n| b | 2 |",
            "Name: a, Value: 1. Name: b, Value: 2.",
        ),
        ("| a | b | c | d | e |\n|---|---|---|---|---|\n| 1 | 2 | 3 | 4 | 5 |", ""),
        ("Intro:\n\n| K | V |\n|---|---|\n| x | `y` |\n\nEnd.", "Intro: K: x, V: y. End."),
    ],
)
def test_to_speech(markdown, speech):
    assert to_speech(markdown) == speech


def test_sentences():
    assert sentences("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]
    assert sentences("") == []


def test_chunk_short_text_is_one_chunk():
    assert chunk("One. Two.") == ["One. Two."]


def test_chunk_groups_sentences_under_limit():
    text = " ".join(
        f"Sentence number {i} is here and padded out a little bit more." for i in range(20)
    )
    pieces = chunk(text, max_chars=200)
    assert len(pieces) > 1
    assert all(len(p) <= 200 for p in pieces)
    assert " ".join(pieces) == text


def test_chunk_keeps_overlong_sentence_whole():
    long = "word " * 150 + "end."
    assert chunk(long.strip(), max_chars=100) == [long.strip()]


def test_chunk_empty():
    assert chunk("") == []
