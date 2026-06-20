"""Validate the assembled taskset.json (T-1.2 (d)).

The taskset is the pre-registered run manifest: exactly 30 tasks in the fixed
interleaved [E, M, H] order (domain.md §4 "Ordering matters"), each pointing at a
real spec whose id/tier/feature-tags match, and validating taskset.schema.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from harness.compiler import compile_contract_suite
from harness.specschema import load_spec

REPO = Path(__file__).resolve().parents[2]
P1 = REPO / "experiments" / "phase_minus_1"
TASKSET = P1 / "taskset.json"
SCHEMA = P1 / "taskset.schema.json"


def _taskset() -> dict:
    return json.loads(TASKSET.read_text())


def test_taskset_validates_against_schema() -> None:
    jsonschema.validate(_taskset(), json.loads(SCHEMA.read_text()))


def test_thirty_tasks_positions_1_to_30() -> None:
    tasks = _taskset()["task_order"]
    assert len(tasks) == 30
    assert [t["position"] for t in tasks] == list(range(1, 31))


def test_fixed_interleaved_order() -> None:
    # domain.md §4: repeating triplets [Easy_k, Medium_k, Hard_k] keep difficulty stationary.
    tiers = [t["tier"] for t in _taskset()["task_order"]]
    assert tiers == ["easy", "medium", "hard"] * 10


def test_protocol_version_and_domain() -> None:
    ts = _taskset()
    assert ts["protocol_version"] == "v2"  # CHANGELOG: results.schema run_kind amendment
    assert ts["domain"] == "spec-to-crud-service"


def test_each_entry_matches_its_spec() -> None:
    for t in _taskset()["task_order"]:
        spec_path = REPO / t["spec_path"]
        assert spec_path.exists(), f"missing spec file: {t['spec_path']}"
        spec = load_spec(spec_path)
        assert spec.id == t["id"]
        assert spec.tier == t["tier"]
        # expected_contract_tests_min is a real lower bound on the compiled suite size
        n = len(compile_contract_suite(spec))
        assert t["expected_contract_tests_min"] <= n


def test_ids_unique_and_feature_tags_reflect_tier() -> None:
    tasks = _taskset()["task_order"]
    ids = [t["id"] for t in tasks]
    assert len(ids) == len(set(ids))  # all 30 ids distinct
    for t in tasks:
        assert f"tier:{t['tier']}" in t["feature_tags"]
        if t["tier"] == "hard":
            # every hard task carries at least one oracle-tested business rule tag
            assert any(tag.startswith("rule:") for tag in t["feature_tags"])
