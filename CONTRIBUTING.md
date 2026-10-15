# Contributing

Keep changes small, testable, and compatible with the security boundaries in
`SECURITY.md`.

1. Add or update a behavioral test for controller, contract, bridge, or MCP
   changes.
2. Run `python -m unittest discover -s tests -v`.
3. For Fusion adapter changes, test in a new blank document with Safety ON and
   Safety OFF, verify the checkpoint, and verify that one Undo reverts the task.
4. Never add arbitrary-code execution or a remote network bind to the bridge.

Pull requests should state which Fusion version was tested and which live
modeling operations were exercised.
