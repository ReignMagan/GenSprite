"""A local project picker for the self-contained Windows GenSprite setup."""

import argparse
import json
import os
import queue
import re
import sys
import tempfile
import threading
import time
import tomllib
from pathlib import Path

from .installer import InstallResult, connect_project


def load_payload(folder: Path) -> tuple[Path, dict]:
    try:
        path = folder / "manifest.json"
        if path.stat().st_size > 4096:
            raise ValueError("manifest is too large")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("file") != "GenSpriteMCP.exe"
            or not isinstance(manifest.get("version"), str)
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest["version"])
            or not isinstance(manifest.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"])
        ):
            raise ValueError("invalid manifest")
        executable = folder / "GenSpriteMCP.exe"
        if not executable.is_file():
            raise ValueError("missing executable")
        return executable, manifest
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(
            "Setup payload is missing or invalid. Open the complete GenSprite-Setup.exe."
        ) from exc


class SetupWindow:
    def __init__(self, root, payload: Path, manifest: dict, install_root: Path):
        import tkinter as tk
        from tkinter import filedialog, ttk

        self.root, self.payload, self.manifest = root, payload, manifest
        self.install_root = install_root
        self.dialog = filedialog
        self.busy = False
        self.last_result: InstallResult | None = None
        self.events: queue.Queue = queue.Queue()
        self.project = tk.StringVar()
        self.status = tk.StringVar(value="Choose a folder to get started.")
        self.details = tk.StringVar(value="Your sprites and history will stay with that project.")
        root.title("GenSprite - Connect to Codex")
        root.geometry("700x440")
        root.minsize(640, 420)
        root.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(root, padding=28)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="GENSPRITE", font=("Segoe UI", 10, "bold")).grid(sticky="w")
        ttk.Label(
            frame, text="Your sprites. On your computer.", font=("Segoe UI", 22, "bold")
        ).grid(sticky="w", pady=(12, 8))
        ttk.Label(
            frame,
            text="Connect a game project to GenSprite in Codex.\n"
            "Python and the MCP runtime are included.",
            font=("Segoe UI", 11),
        ).grid(sticky="w", pady=(0, 24))
        ttk.Label(frame, text="Game project folder", font=("Segoe UI", 10, "bold")).grid(sticky="w")
        folders = ttk.Frame(frame)
        folders.grid(sticky="ew", pady=(8, 16))
        folders.columnconfigure(0, weight=1)
        self.entry = ttk.Entry(folders, textvariable=self.project, font=("Segoe UI", 10))
        self.entry.grid(row=0, column=0, sticky="ew", ipady=5)
        self.browse_button = ttk.Button(folders, text="Choose folder...", command=self.browse)
        self.browse_button.grid(row=0, column=1, padx=(10, 0), ipady=4)
        self.connect_button = ttk.Button(
            frame, text="Connect to Codex", command=self.connect, state="disabled"
        )
        self.connect_button.grid(sticky="w", ipady=6)
        ttk.Separator(frame).grid(sticky="ew", pady=20)
        self.status_label = ttk.Label(
            frame, textvariable=self.status, font=("Segoe UI", 11, "bold"), wraplength=620
        )
        self.status_label.grid(sticky="w")
        ttk.Label(frame, textvariable=self.details, font=("Segoe UI", 10), wraplength=620).grid(
            sticky="w", pady=(8, 0)
        )
        self.project.trace_add("write", self._selection_changed)
        root.after(100, self._poll)

    def _selection_changed(self, *_args) -> None:
        if not self.busy:
            self.connect_button.configure(
                state="normal" if self.project.get().strip() else "disabled"
            )

    def browse(self) -> None:
        selected = self.dialog.askdirectory(
            parent=self.root, title="Choose your game project", mustexist=True
        )
        if selected:
            self.project.set(selected)

    def connect(self) -> None:
        if self.busy:
            return
        selected = self.project.get().strip()
        if not selected:
            return
        self.busy = True
        self.last_result = None
        for widget in (self.entry, self.browse_button, self.connect_button):
            widget.configure(state="disabled")
        self.status.set("Connecting your project...")
        self.details.set("Setup will preserve other Codex settings and check the local MCP.")

        def worker() -> None:
            try:
                result = connect_project(
                    Path(selected),
                    self.payload,
                    self.manifest["sha256"],
                    self.manifest["version"],
                    self.install_root,
                    progress=lambda message: self.events.put(("progress", message)),
                )
                self.events.put(("success", result))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == "progress":
                self.status.set(value)
                continue
            self.busy = False
            for widget in (self.entry, self.browse_button):
                widget.configure(state="normal")
            self._selection_changed()
            if kind == "success":
                self.last_result = value
                self.status.set(f"Connected. GenSprite is ready with {value.tool_count} tools.")
                self.details.set(
                    "Reopen Codex in this project and trust the folder if asked.\n"
                    "You can reopen Setup to connect another project."
                )
            else:
                self.status.set("Could not connect this project.")
                self.details.set(str(value))
        self.root.after(100, self._poll)

    def close(self) -> None:
        if self.busy:
            self.status.set("Finishing setup. Please keep this window open for a moment.")
        else:
            self.root.destroy()


def self_check(payload: Path, manifest: dict) -> dict:
    """Exercise the packaged GUI and installed runtime without touching user configuration."""
    import tkinter as tk

    with tempfile.TemporaryDirectory(prefix="gensprite-setup-check-") as temporary:
        temporary_path = Path(temporary)
        project = temporary_path / "Game's folder \u2605"
        (project / ".codex").mkdir(parents=True)
        config = project / ".codex" / "config.toml"
        original = b'model = "preserved" # keep\n[mcp_servers.other]\ncommand = "other.exe"\n'
        config.write_bytes(original)
        install_root = temporary_path / "installed"
        root = tk.Tk()
        root.withdraw()
        try:
            app = SetupWindow(root, payload, manifest, install_root)
            app.project.set(str(project))
            app.connect()
            deadline = time.monotonic() + 120
            while app.busy and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            if app.busy or app.last_result is None:
                raise ValueError(f"Packaged GUI connection failed: {app.details.get()}")
            result = app.last_result
        finally:
            root.destroy()
        saved = tomllib.loads(config.read_text(encoding="utf-8"))
        if saved.get("model") != "preserved" or result.backup_path.read_bytes() != original:
            raise ValueError("Setup did not preserve configuration and backup")
        if saved["mcp_servers"]["gensprite"]["command"] != str(result.executable):
            raise ValueError("Setup recorded the wrong executable")
        again = connect_project(
            project, payload, manifest["sha256"], manifest["version"], install_root
        )
        if again.backup_path is not None:
            raise ValueError("Repeated setup is not idempotent")
        second = temporary_path / "second game"
        second.mkdir()
        other = connect_project(
            second, payload, manifest["sha256"], manifest["version"], install_root
        )
        if other.output_dir == result.output_dir:
            raise ValueError("Different projects share an asset store")
        count = result.tool_count
    if temporary_path.exists():
        raise ValueError("Temporary setup data was not removed")
    return {
        "status": "passed",
        "version": manifest["version"],
        "tool_count": count,
        "gui_checked": True,
        "configuration_preserved": True,
        "backup_verified": True,
        "idempotent": True,
        "separate_projects": True,
        "temporary_outputs_removed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="GenSprite local Windows setup")
    parser.add_argument("--self-check", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--report", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        payload, manifest = load_payload(Path(getattr(sys, "_MEIPASS", "")) / "payload")
        if args.self_check:
            report = self_check(payload, manifest)
        else:
            if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
                raise ValueError("This installer supports Codex on Windows only")
            import tkinter as tk

            root = tk.Tk()
            SetupWindow(root, payload, manifest, Path(os.environ["LOCALAPPDATA"]) / "GenSprite")
            root.mainloop()
            return 0
    except Exception as exc:
        report = {"status": "failed", "error": str(exc)}
        if not args.self_check:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("GenSprite Setup", str(exc), parent=root)
            root.destroy()
            return 1
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if sys.stdout is not None:
        print(json.dumps(report))
    return 0 if report["status"] == "passed" else 1
