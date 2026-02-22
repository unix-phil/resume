# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

A macOS CLI tool that manages tmux sessions on a remote VM. It opens Terminal.app windows that SSH into the remote host and attach to named tmux sessions (prefixed `resume-`). Built with Typer + Rich.

## Commands

```bash
./resume --test           # Run full test suite
./resume --test -v        # Verbose
./resume --test -k test_name  # Run a single test by name
```

The `./resume` shell script bootstraps `uv`, syncs dependencies, and dispatches to `uv run python -m resume.main`. There is no separate build or lint step.

## Architecture

**Single module CLI** — all logic lives in `src/resume/main.py`. One Typer command (`main()`) with mutually exclusive options (`--setup`, `--list`, `--remove`, `--detach`, `--clear`) or a positional session name. No subcommands.

**Key helpers:**
- `ssh_run(host, cmd)` — runs a command on the remote host via SSH with login shell
- `open_terminal_window(host, name)` — opens a Terminal.app window via AppleScript, sets custom title to `resume-{name}`
- `close_resume_terminal_windows()` — closes only Terminal windows whose tab custom title starts with `resume-`
- `list_remote_sessions(host)` — parses `tmux list-sessions` output, returns `(name, attached)` tuples for `resume-*` sessions

**Config:** JSON at `~/.config/resume/config.json`, just `{"ssh_host": "user@host"}`.

## Testing patterns

Tests are in `tests/test_main.py` using pytest. Key conventions:

- **Config isolation:** `isolate_config` fixture (autouse) redirects config to `tmp_path`. `with_host` fixture pre-populates an SSH host.
- **CLI tests:** Use `typer.testing.CliRunner` to invoke the app and assert on exit code + output text.
- **Mocking:** SSH and subprocess calls are patched with `unittest.mock.patch`. Never call real SSH in tests.
- **Test classes:** Grouped by feature (e.g., `TestCliClear`, `TestCliDetach`, `TestMutualExclusivity`).
