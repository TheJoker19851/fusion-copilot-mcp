# Architecture

Fusion Copilot MCP has three deep modules separated at explicit seams.

## MCP module

The MCP module exposes a small set of user-goal tools to Codex. It never owns
the safety mode and cannot disable it. A complete modeling request is forwarded
as one batch so the user is never asked to approve every low-level change.

## Local bridge module

The sidecar authenticates to a loopback-only HTTP bridge using a random token
stored under the current Windows profile. The HTTP handler never calls the
Fusion interface directly. It queues work and fires a Fusion custom event.

## Fusion task module

Fusion receives the request on its main thread. Mutating tasks run inside one
Fusion command transaction:

1. Safety ON asks once for the complete task; Safety OFF skips this dialog.
2. A local `.f3d` recovery checkpoint is exported.
3. Every declared modeling operation runs in order.
4. The resulting B-Rep and mesh bodies are validated.
5. Fusion commits one undoable transaction, or aborts the whole transaction.

The palette is the only interface that can change the persistent safety mode.
