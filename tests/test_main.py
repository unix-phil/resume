import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from typer import Exit
from typer.testing import CliRunner

from resume import main
from resume.main import (
    PREFIX,
    app,
    list_remote_sessions,
    load_config,
    require_host,
    save_config,
    ssh_create_session,
    validate_session_name,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """Point CONFIG_DIR / CONFIG_FILE at a temp directory for every test."""
    config_dir = str(tmp_path / ".config" / "resume")
    config_file = str(tmp_path / ".config" / "resume" / "config.json")
    monkeypatch.setattr(main, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(main, "CONFIG_FILE", config_file)
    return config_file


@pytest.fixture
def with_host(isolate_config):
    """Pre-populate config with an SSH host."""
    import os
    os.makedirs(os.path.dirname(isolate_config), exist_ok=True)
    with open(isolate_config, "w") as f:
        json.dump({"ssh_host": "user@host"}, f)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

class TestSaveLoadConfig:
    def test_round_trip(self):
        save_config({"ssh_host": "me@box"})
        assert load_config() == {"ssh_host": "me@box"}

    def test_load_missing_file(self):
        assert load_config() == {}

    def test_overwrite(self):
        save_config({"ssh_host": "a"})
        save_config({"ssh_host": "b"})
        assert load_config()["ssh_host"] == "b"


class TestRequireHost:
    def test_exits_when_no_config(self):
        with pytest.raises(Exit):
            require_host()

    def test_exits_when_empty_host(self):
        save_config({"ssh_host": ""})
        with pytest.raises(Exit):
            require_host()

    def test_returns_host(self):
        save_config({"ssh_host": "me@box"})
        assert require_host() == "me@box"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidateSessionName:
    @pytest.mark.parametrize("name", ["foo", "my-app", "test_1", "CamelCase", "a123"])
    def test_valid_names(self, name):
        validate_session_name(name)  # should not raise

    @pytest.mark.parametrize("name", ["foo bar", "a;b", "", "hello\nworld", "x&y", "$(cmd)"])
    def test_invalid_names(self, name):
        with pytest.raises(Exit):
            validate_session_name(name)


# ---------------------------------------------------------------------------
# list_remote_sessions
# ---------------------------------------------------------------------------

class TestListRemoteSessions:
    def _mock_ssh(self, stdout):
        return patch("resume.main.ssh_run", return_value=MagicMock(stdout=stdout))

    def test_parses_sessions(self):
        tmux_out = "resume-web:0\nresume-api:1\nother:0\n"
        with self._mock_ssh(tmux_out):
            result = list_remote_sessions("h")
        assert result == [("api", True), ("web", False)]

    def test_empty_output(self):
        with self._mock_ssh(""):
            assert list_remote_sessions("h") == []

    def test_no_resume_sessions(self):
        with self._mock_ssh("myapp:0\nother:1\n"):
            assert list_remote_sessions("h") == []

    def test_malformed_lines_skipped(self):
        with self._mock_ssh("badline\nresume-ok:0\n"):
            assert list_remote_sessions("h") == [("ok", False)]


# ---------------------------------------------------------------------------
# ssh_create_session
# ---------------------------------------------------------------------------

class TestSshCreateSession:
    def test_creates_new_session(self):
        mock_list = MagicMock(stdout="")
        mock_create = MagicMock(returncode=0)
        mock_color = MagicMock(returncode=0)
        with patch("resume.main.ssh_run", side_effect=[mock_list, mock_create, mock_color]) as mock:
            existed, attached = ssh_create_session("h", "web")
        assert (existed, attached) == (False, False)
        # Verify new-session and set color calls were made
        assert mock.call_count == 3
        create_cmd = mock.call_args_list[1][0][1]
        assert "new-session" in create_cmd
        assert f"{PREFIX}web" in create_cmd
        color_cmd = mock.call_args_list[2][0][1]
        assert "set" in color_cmd

    def test_existing_detached_session(self):
        mock_list = MagicMock(stdout=f"{PREFIX}web:0\n")
        with patch("resume.main.ssh_run", return_value=mock_list) as mock:
            existed, attached = ssh_create_session("h", "web")
        assert (existed, attached) == (True, False)
        assert mock.call_count == 1  # no create call

    def test_existing_attached_session(self):
        mock_list = MagicMock(stdout=f"{PREFIX}web:1\n")
        with patch("resume.main.ssh_run", return_value=mock_list) as mock:
            existed, attached = ssh_create_session("h", "web")
        assert (existed, attached) == (True, True)
        assert mock.call_count == 1


# ---------------------------------------------------------------------------
# CLI commands via CliRunner
# ---------------------------------------------------------------------------

class TestCliSetup:
    def test_saves_host(self):
        result = runner.invoke(app, ["--setup"], input="me@box\n\n")
        assert result.exit_code == 0
        assert "Saved" in result.output
        assert load_config()["ssh_host"] == "me@box"

    def test_enables_agent_forwarding(self):
        result = runner.invoke(app, ["--setup"], input="me@box\ny\n")
        assert result.exit_code == 0
        assert load_config()["ssh_agent_forwarding"] is True
        assert "enabled" in result.output

    def test_disables_agent_forwarding(self):
        save_config({"ssh_host": "old@host", "ssh_agent_forwarding": True})
        result = runner.invoke(app, ["--setup"], input="\nn\n")
        assert result.exit_code == 0
        assert load_config()["ssh_agent_forwarding"] is False
        assert "disabled" in result.output

    def test_keeps_existing_agent_forwarding_on_empty_input(self):
        save_config({"ssh_host": "old@host", "ssh_agent_forwarding": True})
        result = runner.invoke(app, ["--setup"], input="\n\n")
        assert result.exit_code == 0
        assert load_config()["ssh_agent_forwarding"] is True

    def test_defaults_to_disabled(self):
        result = runner.invoke(app, ["--setup"], input="me@box\n\n")
        assert result.exit_code == 0
        assert load_config()["ssh_agent_forwarding"] is False

    def test_keeps_existing_host_on_empty_input(self):
        save_config({"ssh_host": "old@host"})
        result = runner.invoke(app, ["--setup"], input="\n\n")
        assert result.exit_code == 0
        assert load_config()["ssh_host"] == "old@host"

    def test_exits_on_no_host(self):
        result = runner.invoke(app, ["--setup"], input="\n")
        assert result.exit_code != 0


class TestCliList:
    def test_shows_sessions(self, with_host):
        with patch("resume.main.list_remote_sessions", return_value=[("api", True), ("web", False)]):
            result = runner.invoke(app, ["--list"])
        assert result.exit_code == 0
        assert "api" in result.output
        assert "web" in result.output
        assert "attached" in result.output
        assert "detached" in result.output

    def test_empty_message(self, with_host):
        with patch("resume.main.list_remote_sessions", return_value=[]):
            result = runner.invoke(app, ["--list"])
        assert result.exit_code == 0
        assert "No sessions" in result.output


class TestCliRemove:
    def test_kills_session(self, with_host):
        mock_result = MagicMock(returncode=0)
        with patch("resume.main.ssh_run", return_value=mock_result) as mock_ssh, \
             patch("resume.main.close_terminal_windows") as mock_close:
            result = runner.invoke(app, ["--remove", "web"])
        assert result.exit_code == 0
        assert "Removed" in result.output
        mock_close.assert_called_once_with("web")
        # Verify symlink cleanup call
        cleanup_cmd = mock_ssh.call_args_list[-1][0][1]
        assert "rm -f /tmp/resume/resume-web.sock" in cleanup_cmd

    def test_error_not_found(self, with_host):
        mock_result = MagicMock(returncode=1)
        with patch("resume.main.ssh_run", return_value=mock_result):
            result = runner.invoke(app, ["--remove", "nope"])
        assert result.exit_code != 0
        assert "not found" in result.output

    def test_rejects_invalid_name(self, with_host):
        result = runner.invoke(app, ["--remove", "bad name"])
        assert result.exit_code != 0


class TestOpenTerminalAgentForwarding:
    def test_includes_agent_flag_and_symlink(self, with_host):
        save_config({"ssh_host": "user@host", "ssh_agent_forwarding": True})
        with patch("resume.main.subprocess.run") as mock_run:
            from resume.main import open_terminal_window
            open_terminal_window("user@host", "web")
        script = mock_run.call_args[0][0][2]  # osascript -e <script>
        assert "ssh -t -A user@host" in script
        assert "ln -sf $SSH_AUTH_SOCK /tmp/resume/resume-web.sock" in script
        assert "tmux set-environment" in script

    def test_no_agent_flag_when_disabled(self, with_host):
        with patch("resume.main.subprocess.run") as mock_run:
            from resume.main import open_terminal_window
            open_terminal_window("user@host", "web")
        script = mock_run.call_args[0][0][2]
        assert "ssh -t user@host" in script
        assert "ln -sf" not in script


class TestCliName:
    def test_new_session(self, with_host):
        with patch("resume.main.ssh_create_session", return_value=(False, False)) as mock_create, \
             patch("resume.main.open_terminal_window") as mock_term:
            result = runner.invoke(app, ["web"])
        assert result.exit_code == 0
        assert "Created" in result.output
        mock_term.assert_called_once()

    def test_existing_detached(self, with_host):
        with patch("resume.main.ssh_create_session", return_value=(True, False)), \
             patch("resume.main.open_terminal_window") as mock_term:
            result = runner.invoke(app, ["web"])
        assert result.exit_code == 0
        assert "Resuming" in result.output
        mock_term.assert_called_once()

    def test_existing_attached_skips_terminal(self, with_host):
        with patch("resume.main.ssh_create_session", return_value=(True, True)), \
             patch("resume.main.open_terminal_window") as mock_term:
            result = runner.invoke(app, ["web"])
        assert result.exit_code == 0
        assert "already attached" in result.output
        mock_term.assert_not_called()

    def test_rejects_invalid_name(self, with_host):
        result = runner.invoke(app, ["bad name"])
        assert result.exit_code != 0


class TestCliNoArgs:
    def test_opens_unattached(self, with_host):
        sessions = [("api", True), ("web", False), ("bg", False)]
        with patch("resume.main.list_remote_sessions", return_value=sessions), \
             patch("resume.main.open_terminal_window") as mock_term:
            result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "Resumed 2" in result.output
        assert mock_term.call_count == 2

    def test_empty_message(self, with_host):
        with patch("resume.main.list_remote_sessions", return_value=[("x", True)]), \
             patch("resume.main.open_terminal_window") as mock_term:
            result = runner.invoke(app, [])
        assert result.exit_code == 0
        assert "No detached" in result.output
        mock_term.assert_not_called()


class TestCliClear:
    def test_kills_all_and_closes(self, with_host):
        sessions = [("api", False), ("web", True)]
        with patch("resume.main.list_remote_sessions", return_value=sessions), \
             patch("resume.main.ssh_run") as mock_ssh, \
             patch("resume.main.close_terminal_windows") as mock_close:
            result = runner.invoke(app, ["--clear"])
        assert result.exit_code == 0
        assert "Killed 2" in result.output
        assert mock_ssh.call_count == 3  # 2 kill-session + 1 rm cleanup
        cleanup_cmd = mock_ssh.call_args_list[-1][0][1]
        assert "rm -rf /tmp/resume" in cleanup_cmd
        mock_close.assert_called_once()

    def test_empty_case(self, with_host):
        with patch("resume.main.list_remote_sessions", return_value=[]), \
             patch("resume.main.close_terminal_windows") as mock_close:
            result = runner.invoke(app, ["--clear"])
        assert result.exit_code == 0
        assert "No sessions" in result.output
        mock_close.assert_called_once()


class TestCliDetach:
    def test_detaches_attached_and_closes(self, with_host):
        sessions = [("api", True), ("web", False), ("bg", True)]
        with patch("resume.main.list_remote_sessions", return_value=sessions), \
             patch("resume.main.ssh_run") as mock_ssh, \
             patch("resume.main.close_terminal_windows") as mock_close:
            result = runner.invoke(app, ["--detach"])
        assert result.exit_code == 0
        assert "Detached 2" in result.output
        assert "api" in result.output
        assert "bg" in result.output
        assert mock_ssh.call_count == 2
        mock_close.assert_called_once()

    def test_no_attached_sessions(self, with_host):
        sessions = [("web", False)]
        with patch("resume.main.list_remote_sessions", return_value=sessions), \
             patch("resume.main.close_terminal_windows") as mock_close:
            result = runner.invoke(app, ["--detach"])
        assert result.exit_code == 0
        assert "No attached sessions" in result.output
        mock_close.assert_called_once()

    def test_empty_sessions(self, with_host):
        with patch("resume.main.list_remote_sessions", return_value=[]), \
             patch("resume.main.close_terminal_windows") as mock_close:
            result = runner.invoke(app, ["--detach"])
        assert result.exit_code == 0
        assert "No attached sessions" in result.output
        mock_close.assert_called_once()


class TestMutualExclusivity:
    def test_name_with_flag_rejected(self, with_host):
        result = runner.invoke(app, ["web", "--list"])
        assert result.exit_code != 0
        assert "Cannot combine" in result.output

    def test_name_with_clear_rejected(self, with_host):
        result = runner.invoke(app, ["web", "--clear"])
        assert result.exit_code != 0
        assert "Cannot combine" in result.output

    def test_two_flags_rejected(self, with_host):
        result = runner.invoke(app, ["--list", "--clear"])
        assert result.exit_code != 0
        assert "Only one option" in result.output

    def test_remove_with_flag_rejected(self, with_host):
        result = runner.invoke(app, ["--remove", "web", "--list"])
        assert result.exit_code != 0
        assert "Only one option" in result.output
