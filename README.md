# Fusion Copilot MCP

Fusion Copilot MCP is a local bridge that lets an MCP-compatible coding agent
inspect and automate Autodesk Fusion through a Fusion add-in.

Project home: https://github.com/TheJoker19851/fusion-copilot-mcp

The project is an independent experiment and is not affiliated with or endorsed
by Autodesk or Microsoft. It uses Autodesk Fusion's public add-in interface; it
does not reverse engineer or replace Fusion.

## Safety model

- **Safety ON:** Fusion shows one approval for the complete task. It does not
  interrupt each modeling operation.
- **Safety OFF:** the initial user request authorizes the complete task, with no
  additional approval dialogs.
- **Always active:** local-only transport, recovery checkpoint, one undoable
  transaction, final validation, and an audit log.

The safety switch can only be changed inside Fusion. It is intentionally not
exposed as an MCP tool.

## MVP capabilities

- Inspect the active design, components, B-Rep bodies, meshes, parameters, and
  current selection.
- Create boxes and cylinders, cut cylindrical holes, fillet a body's edges,
  rename bodies, and create or update user parameters.
- Execute a complete modeling request as one task and one Fusion transaction.
- Validate solid B-Rep bodies and closed, consistently oriented meshes.
- Communicate through an authenticated loopback-only bridge.

The Python controller, bridge, task contract, and MCP surface have automated
tests. Live Fusion validation is still required for each supported Fusion
release before calling a release production-ready.

## Install for local testing

Requirements: Windows, Autodesk Fusion, and Python 3.11 or newer.

```powershell
.\scripts\install.ps1
```

The installer copies the add-in to Fusion's per-user add-in directory and
creates an isolated sidecar environment under `%LOCALAPPDATA%`. It writes a
Codex configuration snippet to
`%LOCALAPPDATA%\FusionCopilotMCP\codex-config.toml`; it never edits the active
Codex configuration automatically.

Restart Fusion or load `FusionCopilotMCP` from **Utilities > Scripts and
Add-Ins**. The palette is the only place where Safety ON/OFF can be changed.

## Development

Run the tests with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the module boundaries and local
workflow.
