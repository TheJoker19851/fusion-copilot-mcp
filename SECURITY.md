# Security

## Supported versions

Until the first stable release, only the latest commit is supported.

## Design boundaries

- The Fusion bridge binds only to `127.0.0.1`.
- Requests require a random bearer token stored in the current Windows profile.
- The MCP sidecar cannot change Safety ON/OFF.
- Safety OFF removes the task-approval dialog, but not checkpoints, transaction
  rollback, final validation, or audit logging.
- The bridge accepts only a small allowlist of typed modeling operations; it
  does not execute arbitrary Python supplied by an MCP client.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability that could expose local
files or permit unauthorized Fusion changes. Use the repository owner's private
security reporting channel when one is configured. Include the affected
version, reproduction steps, and expected impact.
