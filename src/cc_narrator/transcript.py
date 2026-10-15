"""Follow a Claude Code session transcript and yield new assistant text blocks.

The transcript format is internal to Claude Code, so parsing is defensive: anything
unrecognized is skipped.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextBlock:
    uuid: str
    text: str


def _extract(entry: object) -> TextBlock | None:
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return None
    if entry.get("isSidechain") is True:
        return None
    uuid = entry.get("uuid")
    message = entry.get("message")
    if not isinstance(uuid, str) or not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
    else:
        return None
    text = "\n\n".join(t for t in texts if t.strip())
    return TextBlock(uuid, text) if text else None


class TranscriptReader:
    def __init__(self, path: Path, start_at_end: bool = True):
        self.path = Path(path)
        self.deleted = False
        self._fh: BinaryIO | None = None
        self._inode: int | None = None
        self._buffer = b""
        self._seen: set[str] = set()
        self._open(seek_end=start_at_end)

    def _open(self, seek_end: bool) -> None:
        try:
            fh = open(self.path, "rb")
        except FileNotFoundError:
            return
        if self._fh is not None:
            self._fh.close()
        self._fh = fh
        self._inode = os.fstat(fh.fileno()).st_ino
        self._buffer = b""
        if seek_end:
            fh.seek(0, os.SEEK_END)

    def read_new(self) -> list[TextBlock]:
        try:
            stat = os.stat(self.path)
        except FileNotFoundError:
            if self._fh is not None:
                self.deleted = True
            return []
        if self._fh is None:
            self._open(seek_end=False)  # created after we started: all of it is new
        elif stat.st_ino != self._inode or stat.st_size < self._fh.tell():
            self._open(seek_end=True)  # replaced or truncated
        if self._fh is None:
            return []

        self._buffer += self._fh.read()
        *lines, self._buffer = self._buffer.split(b"\n")
        blocks: list[TextBlock] = []
        for raw in lines:
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                log.debug("skipping unreadable transcript line")
                continue
            block = _extract(entry)
            if block is None or block.uuid in self._seen:
                continue
            self._seen.add(block.uuid)
            blocks.append(block)
        return blocks

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None
