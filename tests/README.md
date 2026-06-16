# tests

- Skill smoke: install into a sample KB, run the bridge, assert the four contract
  artifacts and that the deterministic logic check ran (plan T11).
- Deterministic golden regression for the engine steps (plan T12).
- `setup.sh` — one-shot `factlog setup` orchestration (u18): on an env where
  pyrewire is already present, asserts `setup` performs doctor + init, exits 0,
  creates the KB layout, and is idempotent on re-run. Network/pip-independent;
  run with the venv python (`/tmp/factlog-venv`) so the engine check passes.
