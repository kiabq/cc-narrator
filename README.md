# cc-narrator

Hear what Claude Code is doing while it works. cc-narrator reads the session you're
working in aloud with an ElevenLabs voice, and announces when your other sessions
finish, fail, or need you, on a second, quieter voice.

> **Alpha.** macOS only, tested in Ghostty. Expect rough edges.
>
> cc-narrator is an independent project. It is not affiliated with or endorsed by Anthropic.

## How it works

- Plugin hooks start a small watcher process for every Claude Code session.
- The watcher follows the session transcript and speaks Claude's prose as each block
  is written, so you hear it mid-turn, between tool calls. Code blocks are skipped.
- Only the **current session** (the one you most recently sent a prompt to) is narrated.
- Other sessions announce events by name: "six-three-nine-bravo needs permission."
- Sessions are named by `/rename` title, then git branch, then a short spelled-out ID.

## Requirements

- macOS
- [uv](https://docs.astral.sh/uv/)
- Claude Code
- An [ElevenLabs](https://elevenlabs.io) API key and two voice IDs (one for the
  narrator, one for the announcer). Each voice's menu in the Voice Library has
  "Copy voice ID".

## Install

1. Install the `cc-narrate` command (into `~/.local/bin`, which must be on your `PATH`):

   ```sh
   uv tool install git+https://github.com/kiabq/cc-narrator
   ```

2. Configure it:

   ```sh
   mkdir -p ~/.config/cc-narrator
   curl -fsSL https://raw.githubusercontent.com/kiabq/cc-narrator/main/.env.example \
     -o ~/.config/cc-narrator/.env
   # edit ~/.config/cc-narrator/.env: fill in ELEVENLABS_API_KEY and the two voice IDs
   cc-narrate doctor
   cc-narrate say "Narrator check."
   cc-narrate say "Announcer check." --announcer
   ```

3. Install the plugin from inside Claude Code:

   ```
   /plugin marketplace add kiabq/cc-narrator
   /plugin install cc-narrator@cc-narrator
   ```

   Then restart your Claude Code sessions.

## Use

- `/narrate off`, `/narrate on`: narration for this session (`/cc-narrator:narrate`
  if another plugin also has a `/narrate` command).
- `/narrate focus`: narrate this session without sending a prompt.
- `/narrate-voice narrator <voice-id>` or `/narrate-voice announcer <voice-id>`: switch
  a voice (also `cc-narrate voice ...`). The ID is checked with ElevenLabs before it's
  saved to the config file, and running sessions pick it up right away.
  `/narrate-voice` alone shows the current voices.
- Narration is on by default. Set `CC_NARRATOR_ENABLED_BY_DEFAULT=false` to start new
  sessions silent.
- To stream long output, split it into blocks: narration is spoken per transcript
  text block, not per token.

All settings are listed in [`.env.example`](.env.example). Environment variables
override the config file.

## Troubleshooting

- `cc-narrate doctor` checks the key, both voices, and the audio device.
- Hook errors: `~/.cache/cc-narrator/logs/hooks.log`
- Watcher logs: `~/.cache/cc-narrator/logs/<session-id>.log`
- Nothing at all? Check that `cc-narrate` is on the `PATH` that Claude Code's hooks see.

## Development

```sh
git clone https://github.com/kiabq/cc-narrator && cd cc-narrator
uv sync
uv run pytest           # unit tests
uv run pytest -m live   # checks the Claude Code transcript format still parses
uv tool install --editable .
/plugin marketplace add /path/to/cc-narrator   # inside Claude Code, for a local checkout
```

## License

[MIT](LICENSE)
