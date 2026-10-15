"""Turn Claude's markdown into text that sounds natural when spoken."""

from __future__ import annotations

import re

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HR = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_QUOTE = re.compile(r"^\s*>\s?")
_TABLE_SEP_CELL = re.compile(r"^:?-{3,}:?$")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_URL = re.compile(r"https?://\S+")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC_STAR = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])")
_ITALIC_UNDER = re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_STRIKE = re.compile(r"~~(.+?)~~")
_PATH = re.compile(r"(?<![\w/.~-])(?P<prefix>~/|\.{1,2}/|/)?(?P<body>(?:[\w.@+-]+/)+[\w.@+-]+)")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_MAX_TABLE_COLUMNS = 4


def _shorten_path(match: re.Match[str]) -> str:
    body = match.group("body")
    last = body.rsplit("/", 1)[-1]
    if match.group("prefix") is None and body.count("/") == 1 and "." not in last.rstrip("."):
        return match.group(0)  # "and/or", "1/2": not a path
    return last


def _inline(text: str) -> str:
    spans: list[str] = []

    def protect(match: re.Match[str]) -> str:
        spans.append(match.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = _CODE_SPAN.sub(protect, text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("a link", text)
    text = _BOLD.sub(r"\2", text)
    text = _ITALIC_STAR.sub(r"\1", text)
    text = _ITALIC_UNDER.sub(r"\1", text)
    text = _STRIKE.sub(r"\1", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], text)
    return _PATH.sub(_shorten_path, text)


def _terminate(text: str) -> str:
    return text if not text or text[-1] in ".!?:" else text + "."


def _table(lines: list[str]) -> str:
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]
    rows = [r for r in rows if not all(_TABLE_SEP_CELL.match(c) for c in r if c)]
    if not rows or len(rows[0]) > _MAX_TABLE_COLUMNS:
        return ""
    header, *body = rows
    phrases = []
    for row in body:
        pairs = [f"{_inline(h)}: {_inline(v)}" for h, v in zip(header, row, strict=False) if v]
        if pairs:
            phrases.append(", ".join(pairs) + ".")
    return " ".join(phrases)


def to_speech(markdown: str) -> str:
    segments: list[str] = []
    table: list[str] = []
    fence: str | None = None

    def flush_table() -> None:
        if table:
            segments.append(_table(table))
            table.clear()

    for line in markdown.splitlines():
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        opening = _FENCE.match(line)
        if opening:
            flush_table()
            fence = opening.group(1)[:3]
            continue
        if line.strip().startswith("|"):
            table.append(line)
            continue
        flush_table()
        if not line.strip() or _HR.match(line):
            continue
        if _HEADING.match(line):
            segments.append(_terminate(_inline(_HEADING.sub("", line).strip())))
        elif _LIST.match(line):
            segments.append(_terminate(_inline(_LIST.sub("", line).strip())))
        else:
            segments.append(_inline(_QUOTE.sub("", line).strip()))
    flush_table()
    return re.sub(r"\s+", " ", " ".join(s for s in segments if s)).strip()


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def chunk(text: str, max_chars: int = 400) -> list[str]:
    pieces: list[str] = []
    current = ""
    for sentence in sentences(text):
        candidate = f"{current} {sentence}" if current else sentence
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces
