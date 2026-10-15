# Development

## Requirements

- Windows
- Autodesk Fusion
- Python 3.11 or newer for the MCP sidecar

## Tests

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Build and install locally

```powershell
.\scripts\install.ps1
```

The installer copies the add-in into Fusion's per-user add-in directory and
creates an isolated Python environment for the MCP sidecar. It writes, but does
not automatically apply, a Codex configuration snippet under
`%LOCALAPPDATA%\FusionCopilotMCP\codex-config.toml`.

The sidecar normally uses `stdio`. For transport debugging, Streamable HTTP
defaults to `127.0.0.1:27184`; the authenticated Fusion bridge itself uses
`127.0.0.1:27183`.
