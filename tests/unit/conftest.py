# SPDX-License-Identifier: Apache-2.0
"""Shared fixtures for the Python unit-test layer.

The bundled engine scripts live in ``tools/`` (not an installed package), so we
put that directory on ``sys.path`` to import ``common`` and friends directly.
We also pin ``FACTLOG_ROOT`` to a throwaway temp dir *before* ``common`` is
imported, so the module-level path globals never resolve to the developer's cwd
or a real knowledge base — the pure helpers under test never touch the filesystem.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# Bind FACTLOG_ROOT to an isolated empty dir before any tool module is imported.
os.environ.setdefault("FACTLOG_ROOT", tempfile.mkdtemp(prefix="factlog-unit-"))

# The developer's real home, captured before any test relocates it. Only for
# tests that must assert a sandboxed subprocess never resolved back here.
REAL_HOME = os.environ.get("HOME")
REAL_XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME")


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path_factory):
    """Point ``$HOME``/``$XDG_CONFIG_HOME`` at a per-test sandbox (#454).

    Tests that scaffold a KB run ``factlog init`` in a subprocess, and `init`
    adopts its target as the active KB whenever the configured one is not a live
    directory (`init_adopts_target`). Without isolation that write lands in the
    developer's real ``~/.config/factlog/config.json``, retargeting every later
    sync/accept/import at a pytest temp dir that is about to be deleted — and
    because the recorded root is then dead, the next run adopts again.

    Patching ``os.environ`` (rather than each call site) covers both subprocess
    conventions in the suite: the ones that omit ``env`` and inherit, and the
    ones that pass ``env={**os.environ, ...}``. Autouse so a new test file
    cannot forget it.

    Yields the sandbox home; ``sandbox / ".config" / "factlog"`` is where the
    config under test lives.
    """
    sandbox = tmp_path_factory.mktemp("home")
    (sandbox / ".config").mkdir(exist_ok=True)
    previous = {k: os.environ.get(k) for k in ("HOME", "XDG_CONFIG_HOME")}
    os.environ["HOME"] = str(sandbox)
    os.environ["XDG_CONFIG_HOME"] = str(sandbox / ".config")
    try:
        yield sandbox
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def vocabulary(constants: set[str]) -> "QueryVocabulary":  # noqa: F821
    """A ``QueryVocabulary`` that licenses `constants` in every query position.

    For the tests that vary something other than the position axis. The empty
    hierarchy and alias map keep them off the filesystem; a test that means to
    exercise a single position (subject vs relation object vs policy entity)
    builds the vocabulary itself with the sets it wants to tell apart.
    """
    from common import QueryVocabulary

    return QueryVocabulary(constants, constants, constants, hierarchy={}, aliases={})
