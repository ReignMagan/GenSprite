# GenSprite Windows one-click setup design

Date: 2026-10-24

The user selected Codex on Windows as the first supported client/platform. The goal is to connect an existing game project without commands, Python installation, or hand-edited configuration.

## Approaches

- Recommended: a self-contained Windows Setup.exe with a bundled MCP runtime. It works locally and requires no separately installed Python.
- A setup script is smaller but leaves runtime installation and script-launch friction.
- A hosted MCP install link adds hosting and remote asset handling, outside the current local-server scope.

The user selected the Windows setup approach. The user approved the self-contained executable design on 2026-10-24.

## User flow and scope

Open GenSprite-Setup.exe, select an existing game project folder, then click Connect to Codex. Setup installs GenSprite under the user's local application-data folder, preserves unrelated Codex configuration, backs up an existing config before updates, and adds a project-scoped GenSprite entry. Each project gets its own .gensprite asset/history directory. Reopening Setup connects another project.

Setup checks the actual bundled MCP process automatically and shows a clear success or actionable error. Failed setup must preserve the previous configuration. No administrator permissions, external image provider, credentials, demo assets, or human art-review gate are required. Users reopen Codex afterward and accept Codex's own project-trust prompt if necessary; setup must not bypass that trust.

## Verification and delivery

Build a standalone Windows installer plus the normal Python release. Automated checks cover safe paths, configuration preservation/backups/idempotency, failure handling, and a real MCP handshake from the packaged executable. Keep checks in source; exclude tests and sample outputs from delivered artifacts. Update deployment docs and the Windows CI build.

macOS/Linux installers, other clients, hosting, automatic updates and marketplace publication are excluded from this first installer. Public code signing needs a publisher certificate; an unsigned build may show Windows security prompts. No certificate is currently configured.
