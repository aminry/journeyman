"""Pytest bootstrap for the Phase -1 harness.

The harness lives under ``experiments/phase_minus_1/harness`` (it is experiment
code, intentionally NOT part of the shipped ``journeyman`` package — see
ARCHITECTURE.md and docs/adr/0019). Tests import it as the top-level ``harness``
package; add its parent to ``sys.path`` so they can.

Held-out integrity (domain.md §1): the harness and the generated contract tests
must never live inside the effector's repo. Keeping the harness importable only
via this path keeps those trees separate.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HARNESS_PARENT = Path(__file__).resolve().parent / "experiments" / "phase_minus_1"
if str(_HARNESS_PARENT) not in sys.path:
    sys.path.insert(0, str(_HARNESS_PARENT))
