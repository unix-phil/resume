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
        agent_fwd = load_config().get("ssh_agent_forwarding")
        env_opt = " -e SSH_AUTH_SOCK=/tmp/resume/agent.sock" if agent_fwd else ""
        ssh_run(host, f"tmux new-session -d -s {full}{env_opt}", check=True)
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
    agent_fwd = load_config().get("ssh_agent_forwarding")
    agent_flag = " -A" if agent_fwd else ""
    if agent_fwd:
        # Single shared symlink — every new connection refreshes it so all
        # sessions automatically get a working agent socket.
        sock = "/tmp/resume/agent.sock"
        setup = (
            f'mkdir -p /tmp/resume && '
            f'ln -sf $SSH_AUTH_SOCK {sock} && '
            f'export SSH_AUTH_SOCK={sock} && '
            f'tmux set-environment -t {full} SSH_AUTH_SOCK {sock} && '
        )
    else:
        setup = ""
    shell_cmd = f"""ssh -t{agent_flag} {host} '$SHELL -lc "{setup}tmux attach -t {full}"'"""
    escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    applescript = (
        f'tell application "Terminal"\n'
        f'    do script "{escaped}"\n'
        f'    set custom title of selected tab of front window to "{full}"\n'
        f'end tell'
    )
    subprocess.run(["osascript", "-e", applescript], check=True)


def close_terminal_windows(name=None):
    """Close Terminal windows for resume sessions.

    If name is given, close only that session's window (exact match).
    Otherwise close all resume-* windows (prefix match).
    """
    if name:
        condition = f'custom title of t is "{PREFIX}{name}"'
    else:
        condition = f'custom title of t starts with "{PREFIX}"'
    applescript = f"""
tell application "Terminal"
    repeat with i from (count windows) to 1 by -1
        try
            set w to window i
            repeat with t in tabs of w
                if {condition} then
                    do script "exit" in t
                    exit repeat
                end if
            end repeat
        end try
    end repeat

    delay 0.5

    repeat with i from (count windows) to 1 by -1
        try
            set w to window i
            repeat with t in tabs of w
                if {condition} then
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

        current_agent = config.get("ssh_agent_forwarding", False)
        default = "Y/n" if current_agent else "y/N"
        agent_input = input(f"Enable SSH agent forwarding (-A)? [{default}]: ").strip().lower()
        if agent_input in ("y", "yes"):
            agent_fwd = True
        elif agent_input in ("n", "no"):
            agent_fwd = False
        else:
            agent_fwd = current_agent
        config["ssh_agent_forwarding"] = agent_fwd

        save_config(config)
        print(f"[green]Saved SSH host:[/green] {host}")
        status = "enabled" if agent_fwd else "disabled"
        print(f"[green]SSH agent forwarding:[/green] {status}")

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
        close_terminal_windows()

    elif clear:
        host = require_host()
        sessions = list_remote_sessions(host)
        if sessions:
            names = [s for s, _ in sessions]
            for s in names:
                ssh_run(host, f"tmux kill-session -t {PREFIX}{s}")
            ssh_run(host, "rm -rf /tmp/resume")
            print(f"[red]Killed {len(names)} session(s):[/red] {', '.join(names)}")
        else:
            print("[yellow]No sessions.[/yellow]")
        close_terminal_windows()

    elif remove:
        host = require_host()
        validate_session_name(remove)
        ssh_kill_session(host, remove)
        close_terminal_windows(remove)
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
