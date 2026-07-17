# Bundled deterministic engine

The deterministic scripts the skill calls live here (migrated in plan T1).
**Python 3.11+ required** (the engine dependency `pyrewire` needs 3.11+; see `requires-python` in `pyproject.toml`).

## Scripts (8 files)

| Script | Purpose |
|---|---|
| `compile_facts.py` | confirmed facts → `facts/accepted.dl` |
| `run_logic_check.py` | wirelog/pyrewire logic check → `facts/logic_report.txt` |
| `generate_logic_policy.py` | validated policy JSON → `policy/logic-policy.dl` |
| `merge_candidates.py` | merge/dedup/stale-detect candidate facts into `facts/candidates.csv` |
| `review_candidates.py` | review candidate facts |
| `validate.py` | schema and referential validation |
| `resolve_stale_refs.py` | stale-reference resolution |
| `common.py` | shared helpers, `decode_wirelog_value`, `validate_candidate_query` |

The skill invokes these via `${CLAUDE_PLUGIN_ROOT}/tools/<script>.py`. They are the
verifiable anchor — never replaced by model judgment.

## Intentionally absent scripts

`02_translate_question.py` and `04_self_correct.py` from the workshop source
(`llmwiki-ops`) are **not migrated** as runnable scripts.  Their LLM loops
(subprocess calls to the Claude CLI) are inherently Claude-native and are
implemented directly in the skill (`skills/factlog/SKILL.md`).  The deterministic
core of `04_self_correct.py` (`validate_candidate_query`) was promoted into
`common.py` in u1 so all deterministic steps remain in this directory.

## Engine decoding note

`common.decode_wirelog_value` no longer touches `session._intern`; it passes an
already-decoded value through (#323).  Reading a value cannot tell a symbol id
from a genuine `int64` scalar, and guessing rewrote small scalars into unrelated
symbols.

Decoding is the engine's job, but it only works because we feed it:
`run_wirelog` pre-interns every policy literal, accepted-fact value and canonical
atom through the public `session.intern()`, and pyrewire's `_decode_row` resolves
each STRING column against that table.  A lookup miss does **not** raise — it
falls back silently to the raw `int`, so an un-interned symbol renders as a bare
number instead of text.  That makes the pre-interning load-bearing rather than
dead code: measured on pyrewire 1.0.3, the same program yields
`[('int', 0), ('int', 3)]` without pre-interning and
`[('str', 'alpha'), ('str', 'needs review')]` with it.

The dependency stays pinned `pyrewire>=1.0.3,<2.0` in `pyproject.toml` to guard
against silent breakage if that decoding contract (or its raw-int fallback)
changes in a future major release.
