# claude-voice-augmented

Narrates the Claude Code session you're working in with an ElevenLabs voice, and
announces when your other sessions finish, fail, or need you, on a second, quieter voice.

macOS only for now, tested in Ghostty.

## How it works

- Plugin hooks start a small watcher process for every Claude Code session.
- The watcher reads the session transcript and speaks Claude's prose; code blocks are skipped.
- Only the **current session** (the one you most recently sent a prompt to) is narrated.
- Other sessions announce events by name: "six-three-nine-bravo finished."
- Sessions are named by `/rename` title, then git branch, then a short spelled-out ID.

## Install

1. Install the CLI (puts `cva` in `~/.local/bin`, which must be on your `PATH`):

       uv tool install --editable /path/to/claude-voice-augmented

2. Configure:

       mkdir -p ~/.config/claude-voice-augmented
       cp .env.example ~/.config/claude-voice-augmented/.env
       # fill in ELEVENLABS_API_KEY and the two voice IDs
       cva doctor
       cva say "Narrator check."
       cva say "Announcer check." --announcer

3. Install the plugin from inside Claude Code:

       /plugin marketplace add /path/to/claude-voice-augmented
       /plugin install claude-voice-augmented@claude-voice-augmented

   Restart your Claude Code sessions afterwards.

## Use

- `/narrate off` / `/narrate on`: narration for this session.
- `/narrate focus`: narrate this session without sending a prompt.
- `CVA_ENABLED_BY_DEFAULT=false` starts new sessions silent.

## Troubleshooting

- Hook errors: `~/.cache/claude-voice-augmented/logs/hooks.log`
- Watcher logs: `~/.cache/claude-voice-augmented/logs/<session-id>.log`
- After a Claude Code upgrade, run `uv run pytest -m live` to check that the transcript format still parses.
