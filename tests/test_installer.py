import hashlib
import sys
import tomllib

import pytest


def test_config_preserves_other_settings_comments_and_unicode_paths(tmp_path):
    from gensprite_mcp.installer import prepare_config

    original = (
        b'# Keep this comment\nmodel = "existing-model"\n'
        b'[mcp_servers.other]\ncommand = "other.exe"\n'
    )
    project = tmp_path / "Game's folder [one]"
    project.mkdir()
    executable = tmp_path / "installed runtime" / "GenSpriteMCP.exe"
    updated = prepare_config(original, executable, project)
    data = tomllib.loads(updated.decode())
    assert b"# Keep this comment" in updated
    assert data["model"] == "existing-model"
    assert data["mcp_servers"]["other"]["command"] == "other.exe"
    server = data["mcp_servers"]["gensprite"]
    assert server["command"] == str(executable)
    assert server["args"] == ["--output-dir", str(project / ".gensprite")]
    assert server["cwd"] == str(project)
    assert "trust_level" not in updated.decode()
    assert prepare_config(updated, executable, project) == updated


@pytest.mark.parametrize(
    "raw", [b"invalid = [", b"mcp_servers = 12", b"[mcp_servers]\ngensprite = 1"]
)
def test_invalid_config_is_rejected(raw, tmp_path):
    from gensprite_mcp.installer import prepare_config

    with pytest.raises(ValueError, match="configuration"):
        prepare_config(raw, tmp_path / "server.exe", tmp_path)


def test_config_limit_and_bom(tmp_path):
    from gensprite_mcp.installer import prepare_config

    with pytest.raises(ValueError, match="1 MiB"):
        prepare_config(b"#" * (1048576 + 1), tmp_path / "server.exe", tmp_path)
    result = prepare_config(b'\xef\xbb\xbfmodel = "keep"\n', tmp_path / "server.exe", tmp_path)
    assert tomllib.loads(result.decode())["model"] == "keep"


def test_updating_existing_connection_preserves_policy_but_changes_transport(tmp_path):
    from gensprite_mcp.installer import prepare_config

    raw = (
        b'[mcp_servers.gensprite]\nurl = "https://old.invalid/mcp"\nenabled = false\n'
        b'experimental_environment = "remote"\ndisabled_tools = ["integrate_asset"]\n'
    )
    updated = tomllib.loads(prepare_config(raw, tmp_path / "server.exe", tmp_path).decode())
    server = updated["mcp_servers"]["gensprite"]
    assert "url" not in server
    assert "experimental_environment" not in server
    assert server["enabled"] is True
    assert server["disabled_tools"] == ["integrate_asset"]


def source(tmp_path):
    path = tmp_path / "payload.exe"
    path.write_bytes(b"MZ-verified-test-payload")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_install_backup_idempotency_and_project_isolation(tmp_path, monkeypatch):
    from gensprite_mcp import installer

    monkeypatch.setattr(installer, "check_connection", lambda command: {"tool_count": 63})
    payload, digest = source(tmp_path)
    project = tmp_path / "game one"
    (project / ".codex").mkdir(parents=True)
    config = project / ".codex" / "config.toml"
    original = b'model = "keep" # important\n'
    config.write_bytes(original)
    result = installer.connect_project(project, payload, digest, "1.1.0", tmp_path / "installed")
    assert result.backup_path.read_bytes() == original
    assert result.executable.read_bytes() == payload.read_bytes()
    assert result.tool_count == 63
    updated = config.read_bytes()
    again = installer.connect_project(project, payload, digest, "1.1.0", tmp_path / "installed")
    assert again.backup_path is None
    assert config.read_bytes() == updated
    second = tmp_path / "game two"
    second.mkdir()
    other = installer.connect_project(second, payload, digest, "1.1.0", tmp_path / "installed")
    assert result.output_dir != other.output_dir
    assert other.executable == result.executable
    assert tomllib.loads(config.read_text())["model"] == "keep"


@pytest.mark.parametrize("failure", ["digest", "connection", "modified"])
def test_failed_setup_preserves_existing_config(tmp_path, monkeypatch, failure):
    from gensprite_mcp import installer

    payload, digest = source(tmp_path)
    project = tmp_path / "game"
    (project / ".codex").mkdir(parents=True)
    config = project / ".codex" / "config.toml"
    original = b'model = "keep"\n'
    config.write_bytes(original)

    def check(command):
        if failure == "connection":
            raise ValueError("Connection check failed")
        if failure == "modified":
            config.write_bytes(b'model = "changed elsewhere"\n')
        return {"tool_count": 63}

    monkeypatch.setattr(installer, "check_connection", check)
    with pytest.raises(ValueError):
        installer.connect_project(
            project,
            payload,
            "0" * 64 if failure == "digest" else digest,
            "1.1.0",
            tmp_path / "installed",
        )
    assert config.read_bytes() == (
        b'model = "changed elsewhere"\n' if failure == "modified" else original
    )


def test_linked_codex_directory_is_rejected(tmp_path):
    from gensprite_mcp import installer

    project, outside = tmp_path / "game", tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    try:
        (project / ".codex").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable")
    payload, digest = source(tmp_path)
    with pytest.raises(ValueError, match="link|reparse"):
        installer.connect_project(project, payload, digest, "1.1.0", tmp_path / "installed")
    assert not list(outside.iterdir())


def test_real_stdio_connection_check_uses_temporary_assets_only():
    from gensprite_mcp.installer import check_connection

    result = check_connection([sys.executable, "-m", "gensprite_mcp"], timeout=20)
    assert result["server_name"] == "GenSprite"
    assert result["tool_count"] >= 63


def test_non_mcp_program_is_rejected_and_timeout_is_bounded():
    from gensprite_mcp.installer import check_connection

    with pytest.raises(ValueError, match="closed|response|JSON"):
        check_connection([sys.executable, "-c", "print('invalid')"], timeout=3)
    with pytest.raises(ValueError, match="timed out"):
        check_connection([sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.2)


def test_failed_atomic_update_preserves_config_and_creates_recoverable_backup(
    tmp_path, monkeypatch
):
    from gensprite_mcp import installer

    payload, digest = source(tmp_path)
    project = tmp_path / "game"
    (project / ".codex").mkdir(parents=True)
    config = project / ".codex/config.toml"
    original = b'model = "keep"\n'
    config.write_bytes(original)
    monkeypatch.setattr(installer, "check_connection", lambda command: {"tool_count": 63})

    def cannot_replace(*args):
        raise OSError("File is in use")

    monkeypatch.setattr(installer, "_replace_config", cannot_replace)
    with pytest.raises(OSError, match="in use"):
        installer.connect_project(project, payload, digest, "1.1.0", tmp_path / "installed")
    assert config.read_bytes() == original
    backups = list((tmp_path / "installed/backups").rglob("*.toml"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert not list(config.parent.glob("*.tmp"))


@pytest.mark.parametrize("location", [".gensprite", "install"])
def test_linked_store_or_install_root_cannot_redirect_setup(tmp_path, location):
    from gensprite_mcp import installer

    project = tmp_path / "game"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    install = tmp_path / "installed"
    link = project / ".gensprite" if location == ".gensprite" else install
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable")
    payload, digest = source(tmp_path)
    with pytest.raises(ValueError, match="link|reparse"):
        installer.connect_project(project, payload, digest, "1.1.0", install)
    assert not list(outside.iterdir())


@pytest.mark.parametrize("created_during_check", [False, True])
def test_existing_asset_store_file_cannot_produce_a_false_connection(
    tmp_path, monkeypatch, created_during_check
):
    from gensprite_mcp import installer

    payload, digest = source(tmp_path)
    project = tmp_path / "game"
    (project / ".codex").mkdir(parents=True)
    config = project / ".codex/config.toml"
    original = b'model = "preserved"\n'
    config.write_bytes(original)
    output = project / ".gensprite"
    if not created_during_check:
        output.write_text("user data")

    def check(command):
        if not created_during_check:
            raise AssertionError("Invalid output must fail before running the executable")
        output.write_text("user data")
        return {"tool_count": 63}

    monkeypatch.setattr(installer, "check_connection", check)
    with pytest.raises(ValueError, match="directory"):
        installer.connect_project(project, payload, digest, "1.1.0", tmp_path / "installed")
    assert config.read_bytes() == original
    assert output.read_text() == "user data"
