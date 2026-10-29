import hashlib
import json

import pytest


def test_payload_manifest_rejects_redirects_and_invalid_metadata(tmp_path):
    from gensprite_mcp.setup_gui import load_payload

    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"version": "1.1.0", "sha256": "0" * 64, "file": "../outside.exe"}))
    with pytest.raises(ValueError, match="payload"):
        load_payload(tmp_path)
    path.write_text("invalid")
    with pytest.raises(ValueError, match="payload"):
        load_payload(tmp_path)


def test_payload_manifest_returns_the_bundled_runtime_only(tmp_path):
    from gensprite_mcp.setup_gui import load_payload

    binary = tmp_path / "GenSpriteMCP.exe"
    binary.write_bytes(b"MZ-placeholder")
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    metadata = {"version": "1.1.0", "sha256": digest, "file": "GenSpriteMCP.exe"}
    (tmp_path / "manifest.json").write_text(json.dumps(metadata))
    result, manifest = load_payload(tmp_path)
    assert result == binary
    assert manifest == metadata


@pytest.mark.parametrize("client", ["Codex", "OpenCode"])
def test_project_picker_constructs_and_connects_without_blocking_ui(tmp_path, monkeypatch, client):
    tk = pytest.importorskip("tkinter")
    from gensprite_mcp import setup_gui
    from gensprite_mcp.installer import InstallResult

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("A graphical display is unavailable")
    root.withdraw()
    project = tmp_path / "game"
    project.mkdir()
    try:

        def connected(*args, progress=None, client="codex"):
            progress("Checking the MCP connection...")
            return InstallResult(
                tmp_path / "server.exe",
                project / (".codex/config.toml" if client == "codex" else "opencode.json"),
                project / ".gensprite",
                None,
                63,
            )

        monkeypatch.setattr(setup_gui, "connect_project", connected)
        app = setup_gui.SetupWindow(
            root,
            tmp_path / "server.exe",
            {"version": "1.1.0", "sha256": "0" * 64},
            tmp_path / "install",
        )
        root.update_idletasks()
        assert root.winfo_reqheight() <= 500
        assert str(app.connect_button["state"]) == "disabled"
        app.project.set(str(project))
        app.client.set(client)
        app.connect()
        import time

        deadline = time.monotonic() + 5
        while app.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(0.02)
        assert not app.busy
        assert app.last_result.tool_count == 63
        assert "Connected" in app.status.get()
        assert f"Reopen {client}" in app.details.get()
        assert app.last_result.config_path.name == (
            "config.toml" if client == "Codex" else "opencode.json"
        )
    finally:
        root.destroy()
