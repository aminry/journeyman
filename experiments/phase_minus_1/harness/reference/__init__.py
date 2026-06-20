"""Reference CRUD services used to validate the oracle and to back the fake effector.

``service.py`` is intentionally standalone — it imports only stdlib + FastAPI and
**nothing from ``harness``** — so the fake effector can copy it verbatim into a
scaffolded repo (held-out integrity: the effector repo never imports the harness).
The oracle test imports ``build_app`` directly to run correct and deliberately-
broken variants in-process.
"""
