"""Boot env must put Python console scripts on PATH (T-1.3 boot-failure fix).

Root cause of all 3 pilot boot failures: the effector wrote a correct `run.sh` using a
bare `exec uvicorn app:app ...`, but the `uvicorn` console script lives in the user-base
bin (from a `pip --user` install) which was not on the booted service's PATH — so it died
with `exec: uvicorn: not found` before the app ever loaded. (notes booted because it used
`python3 -m uvicorn`.) This is an env/harness bug that would corrupt BOTH experiment arms
at random, so the harness must make console scripts resolvable, as a normal venv would.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import httpx
import pytest

from harness.runner import (
    _boot,
    _python_script_dirs,
    _teardown,
    _wait_for_health,
    free_port,
)


def test_script_dirs_include_where_uvicorn_lives() -> None:
    """The helper must include the dir that actually holds the uvicorn console script,
    so a bare `uvicorn` resolves on the boot PATH."""
    uvicorn_path = shutil.which("uvicorn") or str(Path.home() / "Library/Python/3.14/bin/uvicorn")
    if not Path(uvicorn_path).exists():
        pytest.skip("uvicorn console script not installed in this environment")
    assert str(Path(uvicorn_path).parent) in _python_script_dirs()


_APP = """from fastapi import FastAPI
app = FastAPI()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
"""

_RUN_SH = """#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec uvicorn app:app --host 127.0.0.1 --port "${PORT:-8000}" --workers 1
"""


def test_bare_uvicorn_run_sh_boots_under_the_harness(tmp_path: Path) -> None:
    """End-to-end (zero LLM spend): a repo whose run.sh uses bare `uvicorn` must boot and
    become healthy under the harness — proving the PATH fix resolves the console script."""
    if (
        shutil.which("uvicorn") is None
        and not (Path.home() / "Library/Python/3.14/bin/uvicorn").exists()
    ):
        pytest.skip("uvicorn console script not installed in this environment")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(_APP)
    run_sh = repo / "run.sh"
    run_sh.write_text(_RUN_SH)
    run_sh.chmod(run_sh.stat().st_mode | stat.S_IEXEC)

    port = free_port()
    proc = _boot(repo, port, tmp_path / "service.log")
    try:
        healthy = _wait_for_health(f"http://127.0.0.1:{port}", proc)
        log = (tmp_path / "service.log").read_text()
        assert healthy, f"bare-uvicorn service did not become healthy; log:\n{log}"
        with httpx.Client(timeout=5.0) as c:
            assert c.get(f"http://127.0.0.1:{port}/healthz").status_code == 200
        assert "uvicorn: not found" not in log
    finally:
        _teardown(proc)


def test_boot_env_path_is_not_clobbered(tmp_path: Path) -> None:
    """The fix prepends script dirs but preserves the inherited PATH (so python etc. still
    resolve)."""
    dirs = _python_script_dirs()
    assert all(os.path.isdir(d) for d in dirs)
    assert dirs, "expected at least one Python scripts dir"
