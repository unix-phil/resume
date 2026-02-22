import json
import os
import re
import subprocess
from typing import Optional

import typer
from rich import print

app = typer.Typer(
    help="Manage tmux sessions on a remote VM with Terminal.app windows.",
    add_completion=False,
)

CONFIG_DIR = os.path.expanduser("~/.config/resume")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
PREFIX = "resume-"
SSH_CMD = ["ssh", "-o", "RequestTTY=no"]
# Use the user's default login shell so Homebrew etc. are on PATH
REMOTE_SHELL = "$SHELL -lc"
SESSION_COLORS = [
    "blue", "magenta", "cyan", "green", "yellow", "red",
    "colour39",   # deep sky blue
    "colour208",  # orange
    "colour135",  # medium purple
    "colour70",   # chartreuse
    "colour197",  # deep pink
    "colour33",   # dodger blue
    "colour172",  # dark orange
    "colour48",   # spring green
    "colour99",   # slate blue
    "colour214",  # gold
    "colour168",  # hot pink
    "colour37",   # teal
    "colour190",  # yellow-green
    "colour63",   # royal blue
]


def _shell_quote(s):
    """Single-quote a string for shell."""
    return "'" + s.replace("'", "'\"'\"'") + "'"


def ssh_run(host, remote_cmd, **kwargs):
    """Run a command on the remote host via a login shell."""
    return subprocess.run(
        SSH_CMD + [host, f"{REMOTE_SHELL} {_shell_quote(remote_cmd)}"],
        **kwargs,
    )


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def require_host():
    config = load_config()
    host = config.get("ssh_host")
    if not host:
        print("[red]No SSH host configured.[/red] Run: [bold]./resume --setup[/bold]")
        raise typer.Exit(1)
    return host


def validate_session_name(name):
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        print(f"[red]Invalid session name:[/red] {name}")
        print("Only letters, numbers, hyphens, and underscores are allowed.")
        raise typer.Exit(1)


def list_remote_sessions(host):
    """Return list of (name, attached) tuples for all resume-* sessions."""
    result = ssh_run(
        host, "tmux list-sessions -F '#{session_name}:#{session_attached}' 2>/dev/null || true",
        capture_output=True, text=True,
    )
    sessions = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        name, attached = line.rsplit(":", 1)
        if name.startswith(PREFIX):
            sessions.append((name[len(PREFIX):], attached != "0"))
    return sorted(sessions)


def ssh_create_session(host, name):
    """Create session if it doesn't exist. Return (existed, attached)."""
    full = PREFIX + name
    result = ssh_run(
        host, f"tmux list-sessions -F '#{{session_name}}:#{{session_attached}}' 2>/dev/null || true",
        capture_output=True, text=True,
    )
    existed = False
    attached = False
    for line in result.stdout.strip().splitlines():
        if line.startswith(full + ":"):
            existed = True
            attached = line.split(":")[-1] != "0"
            break
    if not existed:
        ssh_run(host, f"tmux new-session -d -s {full}", check=True)
        color = SESSION_COLORS[hash(name) % len(SESSION_COLORS)]
        ssh_run(host, f"tmux set -t {full} status-style 'bg={color},fg=black'")
    return existed, attached


def ssh_kill_session(host, name):
    full = PREFIX + name
    result = ssh_run(
        host, f"tmux kill-session -t {full}",
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[red]Session '{name}' not found on remote.[/red]")
        raise typer.Exit(1)


def open_terminal_window(host, name):
    full = PREFIX + name
    shell_cmd = f"""ssh -t {host} '$SHELL -lc "tmux attach -t {full}"'"""
    escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    applescript = (
        f'tell application "Terminal"\n'
        f'    set t to do script "{escaped}"\n'
        f'    set custom title of t to "{full}"\n'
        f'end tell'
    )
    subprocess.run(["osascript", "-e", applescript], check=True)


def close_resume_terminal_windows():
    applescript = """
tell application "Terminal"
    -- Send exit to each resume tab so running processes end cleanly
    repeat with i from (count windows) to 1 by -1
        try
            set w to window i
            repeat with t in tabs of w
                if custom title of t starts with "resume-" then
                    do script "exit" in t
                    exit repeat
                end if
            end repeat
        end try
    end repeat

    delay 0.5

    -- Close any remaining resume windows
    repeat with i from (count windows) to 1 by -1
        try
            set w to window i
            repeat with t in tabs of w
                if custom title of t starts with "resume-" then
                    close w saving no
                    exit repeat
                end if
            end repeat
        end try
    end repeat
end tell
"""
    subprocess.run(["osascript", "-e", applescript])


@app.command(epilog="Pass a NAME or an option, not both. Run ./resume --test to run the test suite.")
def main(
    name: Optional[str] = typer.Argument(None, help="Session name to create/attach"),
    setup: bool = typer.Option(False, "--setup", "-s", help="Configure SSH host"),
    list_sessions: bool = typer.Option(False, "--list", "-l", help="List active sessions"),
    remove: Optional[str] = typer.Option(None, "--remove", "-r", help="Remove a session"),
    detach: bool = typer.Option(False, "--detach", "-d", help="Detach all sessions and close resume windows"),
    clear: bool = typer.Option(False, "--clear", "-c", help="Kill all sessions and close resume windows"),
):
    flags = sum([setup, list_sessions, remove is not None, detach, clear])
    if name and flags:
        print("[red]Cannot combine a session name with options.[/red]")
        raise typer.Exit(1)
    if flags > 1:
        print("[red]Only one option may be used at a time.[/red]")
        raise typer.Exit(1)

    if setup:
        config = load_config()
        current = config.get("ssh_host", "")
        prompt = f"SSH host [{current}]: " if current else "SSH host (e.g. user@hostname): "
        host = input(prompt).strip()
        if not host and current:
            host = current
        if not host:
            print("[red]No host provided.[/red]")
            raise typer.Exit(1)
        config["ssh_host"] = host
        save_config(config)
        print(f"[green]Saved SSH host:[/green] {host}")

    elif list_sessions:
        host = require_host()
        sessions = list_remote_sessions(host)
        if not sessions:
            print("[yellow]No sessions.[/yellow]")
            return
        print("[bold]Sessions:[/bold]")
        for s, attached in sessions:
            status = "[green]attached[/green]" if attached else "[dim]detached[/dim]"
            print(f"  [cyan]{s}[/cyan]  {status}")

    elif detach:
        host = require_host()
        sessions = list_remote_sessions(host)
        attached = [s for s, a in sessions if a]
        if attached:
            for s in attached:
                ssh_run(host, f"tmux detach-client -s {PREFIX}{s}")
            print(f"[yellow]Detached {len(attached)} session(s):[/yellow] {', '.join(attached)}")
        else:
            print("[yellow]No attached sessions.[/yellow]")
        close_resume_terminal_windows()

    elif clear:
        host = require_host()
        sessions = list_remote_sessions(host)
        if sessions:
            names = [s for s, _ in sessions]
            for s in names:
                ssh_run(host, f"tmux kill-session -t {PREFIX}{s}")
            print(f"[red]Killed {len(names)} session(s):[/red] {', '.join(names)}")
        else:
            print("[yellow]No sessions.[/yellow]")
        close_resume_terminal_windows()

    elif remove:
        host = require_host()
        validate_session_name(remove)
        ssh_kill_session(host, remove)
        print(f"[red]Removed session:[/red] {remove}")

    elif name:
        host = require_host()
        validate_session_name(name)
        existed, attached = ssh_create_session(host, name)
        if attached:
            print(f"[yellow]Session '{name}' is already attached.[/yellow]")
            return
        open_terminal_window(host, name)
        if existed:
            print(f"[green]Resuming existing session '{name}'.[/green]")
        else:
            print(f"[green]Created and attached session '{name}'.[/green]")

    else:
        host = require_host()
        sessions = list_remote_sessions(host)
        unattached = [s for s, attached in sessions if not attached]
        if not unattached:
            print("[yellow]No detached sessions to resume.[/yellow]")
            return
        for s in unattached:
            open_terminal_window(host, s)
        print(f"[green]Resumed {len(unattached)} session(s):[/green] {', '.join(unattached)}")


if __name__ == "__main__":
    app(prog_name="./resume")
