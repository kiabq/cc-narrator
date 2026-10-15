# claude-voice-augmented — Design

**Date:** 2026-10-14
**Status:** Draft for review

## Purpose

Narrate Claude Code's responses aloud with ElevenLabs while working interactively, in a workflow with many concurrent sessions. This version targets Ghostty; Superset follows later. One voice narrates the session you are working in; a second, quieter voice announces when other sessions finish, fail, or need attention.

Built first as a personal proof of concept, structured so it can later be published as a Claude Code plugin plus a Python package.

## Goals

- Narrate the current session's assistant prose as it is written, block by block, inside the normal interactive Claude Code TUI.
- Announce events (finished, failed, needs permission/input) from all other sessions on a separate, quieter voice.
- Identify sessions by spoken label; the label source is swappable (title, branch, ticket later).
- Never slow down, block, or break a Claude Code session.

## Non-goals (for this version)

- Token-level streaming. Narration granularity is one transcript text block.
- Platforms other than macOS.
- Narrating code, tool calls, or tool output.
- LLM summarization of replies before speech.
- A shared background daemon, menu-bar app, or terminal-focus detection.
- Ticket-system integration for labels (the label interface allows it later).
- Superset support.

## Key facts this design relies on

Verified by a spike on 2026-10-14 (Claude Code 2.1.292) or from the official docs (code.claude.com/docs/en/hooks.md, sessions.md, settings-reference.md):

- Session transcripts are append-only JSONL. Each assistant text block is written as its own line when the block completes, ~0.5 s before the following tool call runs (spike). Text and `tool_use` are separate entries.
- Every hook receives `session_id` and `transcript_path` on stdin. `SessionStart` also receives `source` (`startup` | `resume` | `clear` | `compact`) and `session_title` when set via `--name` or `/rename` (docs).
- Hook events used: `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `Stop`, `StopFailure`, `Notification`, `PermissionRequest` (docs).
- Dictated prompts (`/voice`) still fire `UserPromptSubmit`. There are no voice-specific hooks and no built-in TTS (docs).
- The transcript format is internal, not a documented contract. Parsing must be defensive.

## Naming

| Thing | Name |
|---|---|
| Repo / plugin / PyPI distribution | `claude-voice-augmented` |
| Import package | `claude_voice_augmented` |
| CLI | `claude-voice-augmented`, alias `cva` |
| Slash command | `/narrate` |
| State dir | `~/.cache/claude-voice-augmented/` |
| Config dir | `~/.config/claude-voice-augmented/` |

Check Anthropic's brand guidelines for third-party use of "Claude" before publishing.

## Architecture

One watcher process per Claude Code session, started and stopped by plugin hooks. Every watcher tracks its own transcript; only the watcher for the **current session** narrates. Announcements for other sessions come from hook events and play on a second, quieter channel.

```
claude-voice-augmented/
  plugin/
    .claude-plugin/plugin.json
    hooks/hooks.json      SessionStart, SessionEnd, UserPromptSubmit, Stop,
                          StopFailure, Notification, PermissionRequest
                          → `cva hook <event>`
    commands/narrate.md   /narrate on | off | focus
  src/claude_voice_augmented/
    cli.py         entry point: hook, watch, doctor, say
    hooks.py       read hook stdin, update state, start/signal/stop watcher
    watcher.py     per-session loop wiring the units below together
    transcript.py  tail JSONL; yield new assistant text blocks
    prose.py       markdown → speakable prose, split into sentences
    label.py       spoken session label
    events.py      hook event → announcement line
    focus.py       global current-session state
    tts.py         ElevenLabs streaming client
    player.py      two audio channels with ducking and fade-out
    control.py     per-session and global state files
    config.py      settings loading
  tests/
  .env.example
  pyproject.toml
```

### Unit responsibilities

- **hooks.py:** Reads the hook JSON from stdin and acts on the event (table below). Must exit 0 within 100 ms and catch every exception.
- **watcher.py:** The only module that wires units together. Runs a ~100 ms loop: check control files, read new transcript blocks, narrate or skip, play pending announcements. A future shared-daemon version would replace only this module.
- **transcript.py:** Opens `transcript_path` and follows appended lines. Yields text from entries where `type == "assistant"`, `isSidechain` is not true, and the content block `type == "text"`. Deduplicates by `uuid`. Buffers incomplete lines until a newline arrives. Ignores unknown entry types and malformed JSON. Reopens the file if it is replaced or truncated, and exits if it is deleted. Starts at end-of-file (tail mode), so restarts never replay old text.
- **prose.py:** Converts markdown to speech text. Removes fenced code blocks entirely. Unwraps inline code (``word`` → word). Strips emphasis, heading, and list markers. Reads link text without the URL. Shortens filesystem paths to their final component. Flattens tables to "header: value" phrases, or skips tables wider than four columns. Splits the result into sentences. Pure function.
- **label.py:** `label_for(session) -> str`. Resolution order: `session_title` (from `SessionStart`), then the git branch of the session's `cwd`, then a short ID. The short ID is the first 4 characters of `session_id`, with letters spelled in the NATO alphabet (e.g. `639b` → "six-three-nine-bravo"). Branches are spoken with separators turned into spaces, e.g. "feat ABC-123 login fix".
- **events.py:** Maps hook events to lines: `Stop` → "{label} finished." `StopFailure` → "{label} hit an error." `PermissionRequest` → "{label} needs permission." `Notification` → "{label} needs your attention." Pure function.
- **focus.py:** Reads and writes the global `focus` file containing the current session ID.
- **tts.py:** `synthesize(text, voice_id) -> iterator[bytes]`. Calls ElevenLabs streaming text-to-speech with raw PCM output, configured model (default `eleven_flash_v2_5`), and a 5 s timeout. Accessed through a small protocol so tests can use a fake.
- **player.py:** Two channels, narrator and announcer, each a `sounddevice` output stream at its own volume. Operations: `enqueue(channel, pcm_iter)`, `clear(channel)` with a ~100 ms fade-out, and duck/unduck of the narrator channel. Plays audio as chunks arrive. Accessed through a protocol so tests can use a fake.
- **control.py:** File-based state (layout below). Atomic writes (write a temp file, then rename).
- **config.py:** Loads environment variables, then `~/.config/claude-voice-augmented/.env`, then defaults. Validates required keys.

### Hook actions

| Event | Action |
|---|---|
| `SessionStart` | Clean up stale session dirs. If config is invalid, return a `systemMessage` explaining why and do nothing else. Otherwise create the session dir, store `session_title`, `cwd`, and the Claude Code PID, then launch `cva watch <session_id>` detached. On `source: clear`/`resume`, first stop any watcher previously started from the same Claude Code PID. |
| `UserPromptSubmit` | Set `focus` to this session. Write a `clear` signal for this session. If the watcher PID is dead, respawn it. |
| `Stop`, `StopFailure`, `Notification`, `PermissionRequest` | If this session is not the current one, append `{event, ts}` to its `announce` file. |
| `SessionEnd` | Stop the watcher (SIGTERM via pidfile) and remove the session dir. |

The watcher is launched fully detached: new session, stdio sent to `/dev/null` / the log file. The hook returns immediately.

### State layout

```
~/.cache/claude-voice-augmented/
  focus              current session_id
  announcer.lock     flock: one announcement plays at a time
  last_speaker       session_id that last spoke on the narrator channel
  sessions/<session_id>/
    watcher.pid
    meta.json        session_title, cwd, claude_pid, started_at
    enabled          present = narration on (created per CVA_ENABLED_BY_DEFAULT)
    clear            signal file: watcher clears narrator queue, deletes file
    announce         JSON lines of pending announcements
  logs/<session_id>.log   rotating, 1 MB × 3
```

## Data flow

### Narration (current session)

1. The watcher finds a new assistant text block.
2. If `enabled` is absent or `focus` does not equal this session, it marks the block read and moves on.
3. `prose.py` converts the block. If `last_speaker` differs from this session, the label goes first ("six-three-nine-bravo:") and `last_speaker` is updated.
4. `tts.py` streams PCM into the narrator channel, and playback starts on the first chunk. The next block's audio is fetched while the current block plays (one block ahead).
5. Target delay: ≤ 0.6 s from the transcript write to first audio.

### Announcements (other sessions)

1. The watcher reads new lines from `announce`. It drops any older than `CVA_ANNOUNCE_MAX_AGE_SECONDS`.
2. It takes `announcer.lock` (blocking, with a 30 s timeout), ducks the narrator channel to 50%, and plays "{label} {event line}" on the announcer channel at announcer volume. Then it unducks and releases the lock.
3. Announcements always include the label. The current session never announces its own events.

### Focus switching

1. `UserPromptSubmit` in session X sets `focus = X` and clears X's queue.
2. The previously current watcher sees the focus change on its next loop, fades out within ~100 ms, and drops its queue. It does not finish the sentence.
3. X narrates only blocks written after it became current. There is no catch-up replay.

### Slash command

`/narrate on|off` creates or removes `enabled` for the invoking session (`off` also clears the queue). `/narrate focus` sets `focus` to the invoking session without sending a prompt. The command file runs `cva` via a Bash invocation with `$CLAUDE_SESSION_ID` (or the equivalent provided to plugin commands; confirm during implementation).

## Configuration

`.env.example` (committed; real values live in `~/.config/claude-voice-augmented/.env`, never in the repo):

```sh
ELEVENLABS_API_KEY=
CVA_NARRATOR_VOICE_ID=
CVA_ANNOUNCER_VOICE_ID=
CVA_TTS_MODEL=eleven_flash_v2_5
CVA_NARRATOR_VOLUME=1.0
CVA_ANNOUNCER_VOLUME=0.4
CVA_ENABLED_BY_DEFAULT=true
CVA_ANNOUNCE_MAX_AGE_SECONDS=60
```

Required: `ELEVENLABS_API_KEY`, `CVA_NARRATOR_VOICE_ID`, `CVA_ANNOUNCER_VOICE_ID`.

## Error handling

The main rule: narration never interferes with Claude Code. Every hook exits 0, catches all exceptions, and stays within 100 ms.

| Failure | Behavior |
|---|---|
| Missing/invalid config | No watcher. One `systemMessage` from `SessionStart`. |
| ElevenLabs 401/403 | Disable narration for the session. Say "Narration disabled: ElevenLabs key rejected" once with macOS `say`. |
| ElevenLabs 429/5xx/timeout | Retry once after 1 s, then skip the block and log it. |
| Audio device lost/changed | Reopen the stream on the current default device. Drop the clip that was playing. |
| Partial transcript line | Buffer until a newline arrives. |
| Unknown/malformed entry | Skip it and log at debug level. |
| Transcript replaced/truncated | Reopen and continue from its end. |
| Transcript deleted | The watcher exits. |
| Watcher crash | `UserPromptSubmit` respawns it. |
| Claude Code killed without `SessionEnd` | The watcher polls `claude_pid` and exits when that process is gone. |
| Stale session dirs | `SessionStart` removes dirs with a dead watcher that are older than 24 h. |

## Workspaces

This version targets **Ghostty** only, which needs no special handling. Superset support is future work (below).

## Testing

- **Unit (pytest, no network or audio):**
  - `prose`: table-driven markdown → speech cases.
  - `transcript`: fixture JSONL, including a sanitized copy of the spike transcript, partial lines, duplicate uuids, sidechain entries, unknown types, and truncation.
  - `label`: each step of the resolution chain plus NATO spelling.
  - `events`, `focus`, `control`, `config`: tested against `tmp_path`.
- **Watcher (fake TTS + fake player):** checks what is spoken and on which channel; label on speaker change; stop on focus switch; ducking during announcements; stale announcement drop; disabled sessions stay silent.
- **Hooks:** feed sample stdin JSON for each event and assert the resulting state, exit code 0, and runtime under 100 ms.
- **Format drift (opt-in, marked `live`):** runs `claude -p` with a tool call and asserts that `transcript.py` extracts the expected text. Run after Claude Code upgrades.
- **Manual:** `cva doctor` validates the key and voice IDs and lists the audio device. `cva say "text" [--announcer]` plays a test clip.

## Tooling

- Python ≥ 3.11, managed with `uv`; `ruff` for lint/format; `pytest`.
- Runtime deps: `httpx`, `sounddevice`, `python-dotenv`.
- Plugin hooks call the `cva` executable (installed with `uv tool install`). The plugin README documents installing it.

## Future work (out of scope)

- **Superset support.** Superset can install its own Claude Code status hooks and play completion sounds. Ours run alongside them, and Superset's sounds should be turned off to avoid hearing two alerts. Each task runs in a git worktree, so the branch label is usually meaningful. Verify whether Superset runs Claude Code with a different `HOME` or config dir; if so, add `CVA_STATE_DIR` so both workspaces share one state dir and `focus` works across them.

- Labels from Superset workspace names or ticket numbers/titles via additional `label.py` resolvers.
- Picking up `/rename` mid-session (title is only known at `SessionStart` today).
- Hotkey to silence narration mid-reply.
- Shared daemon for cross-session scheduling and priorities.
- Linux support.
