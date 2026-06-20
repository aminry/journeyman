"""Phase -1 validation harness (T-1.1 measurement spine).

Experiment code that executes the pre-registered Phase -1 protocol
(``experiments/phase_minus_1/protocol.md``). It is deliberately NOT part of the
shipped ``journeyman`` package: it scaffolds a fresh repo per instance, drives the
coding effector with the SPEC ONLY, boots the service, runs an independent
black-box contract suite plus the project Definition-of-Done gate, and writes a
per-task metrics record validated against ``results.schema.json``.

Held-out integrity (domain.md §1): this package and the generated contract tests
never enter the effector's repo.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
