# resume

A macOS CLI for managing tmux sessions on a remote VM. Each session opens in its own Terminal.app window, and you can resume them all with a single command.

## Requirements

- macOS (uses Terminal.app via AppleScript)
- A remote host with `tmux` installed
- SSH access to the remote host

## Install

```bash
git clone <repo-url>
cd resume
./install.sh
```

`install.sh` symlinks `resume` into `/usr/local/bin` so you can run it from anywhere. The first run installs [uv](https://github.com/astral-sh/uv) and Python dependencies automatically.

## Setup

Configure your SSH host:

```bash
./resume --setup
# SSH host (e.g. user@hostname): me@myvm
```

This saves to `~/.config/resume/config.json`.

## Usage

### Create or attach to a session

```bash
./resume web
./resume api
```

Each opens a Terminal.app window that SSHs into your VM and attaches to a tmux session named `resume-web`, `resume-api`, etc. If the session already exists and is detached, it reattaches.

### Resume all detached sessions

```bash
./resume
```

With no arguments, opens a Terminal window for every detached session.

### List sessions

```bash
./resume --list
```

Shows all resume sessions and whether they are attached or detached.

### Detach all sessions

```bash
./resume --detach
```

Detaches all attached sessions and closes their Terminal windows. Sessions stay alive on the remote and can be resumed later.

### Remove a session

```bash
./resume --remove web
```

Kills a single tmux session on the remote.

### Clear everything

```bash
./resume --clear
```

Kills all resume tmux sessions on the remote and closes their Terminal windows.
