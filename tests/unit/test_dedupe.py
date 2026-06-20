"""Deterministic dedupe/UPDATE proof on the FAKE driver (G1 Option A, condition 2).

The pilot exposed that a free-form-id driver wrote 1 unmerged item per task (0 UPDATEs).
With the driver constrained to the canonical taxonomy + presence-based dedupe, two tasks
that touch the SAME feature must collapse to ONE canonical item (a WRITE then an UPDATE),
never two items. This is proven deterministically here on the fakes — the re-pilot triplet
(E1/M1/H1 are different features) only confirms no regression, it does NOT prove dedupe.

Also enforces the merged-craft acceptance (condition 3): the UPDATEd canonical item stays
canonical, generic/project-stripped, and non-trivial; and G3 impact tracking updates on reuse.
"""

from __future__ import annotations

from pathlib import Path

from harness.craft import CraftLibrary
from harness.craftimpact import update_craft_metrics
from harness.driver import FakeDriver, GateOutcome
from harness.reflection import craft_templates_to_write, is_canonical, project_strip_lint
from harness.specschema import load_spec

REPO = Path(__file__).resolve().parents[2]
ORDERS = REPO / "experiments" / "phase_minus_1" / "instances" / "h01_orders.spec.yaml"
VA = {"models": ["claude-sonnet-4-6"], "effector_version": "fake@test", "embedding_model": "bge"}
TS = "2026-06-20T00:00:00Z"
PASSED = GateOutcome(
    contract_passed=True, dod_passed=True, effector_retries=0, first_pass=True, failing_case_ids=[]
)
FAILED = GateOutcome(
    contract_passed=False,
    dod_passed=True,
    effector_retries=1,
    first_pass=False,
    failing_case_ids=["state_machine:illegal_transition"],
)


def test_two_same_feature_tasks_dedupe_to_one_update(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    spec = load_spec(ORDERS)
    driver = FakeDriver(validated_against=VA, last_validated=TS)
    # Pre-cover the universals so the only uncovered item for this feature is its playbook.
    for tpl in craft_templates_to_write(["tier:hard", "crud"], lib):
        lib.write(tpl.to_craft_item(validated_against=VA, last_validated=TS))
    ft = ["rule:state_machine"]

    # Task 1 (same feature, first encounter) -> WRITE the canonical playbook.
    r1 = driver.reflect(
        spec=spec, feature_tags=ft, retrieved=[], incorporated=[], gate=PASSED, library=lib
    )
    assert r1.action == "WRITE" and r1.craft_item.id == "state-machine-playbook"
    lib.write(r1.craft_item)
    ids_after_first = list(lib.ids())

    # Task 2 (SAME feature, now present, with a failure signal) -> UPDATE, not a 2nd WRITE.
    item = lib.read("state-machine-playbook")
    r2 = driver.reflect(
        spec=spec,
        feature_tags=ft,
        retrieved=[item],
        incorporated=["state-machine-playbook"],
        gate=FAILED,
        library=lib,
    )
    assert r2.action == "UPDATE"
    assert r2.target_id == "state-machine-playbook"
    lib.write(r2.craft_item)

    # Dedupe: the library did NOT grow a duplicate; the canonical item was evolved in place.
    assert list(lib.ids()) == ids_after_first
    assert lib.read("state-machine-playbook").version == "1.0.1"


def _precover_universals(lib: CraftLibrary) -> None:
    for tpl in craft_templates_to_write(["tier:hard", "crud"], lib):
        lib.write(tpl.to_craft_item(validated_against=VA, last_validated=TS))


def test_merged_canonical_item_stays_generic_and_actionable(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    spec = load_spec(ORDERS)
    driver = FakeDriver(validated_against=VA, last_validated=TS)
    _precover_universals(lib)
    item = driver.reflect(
        spec=spec,
        feature_tags=["rule:state_machine"],
        retrieved=[],
        incorporated=[],
        gate=PASSED,
        library=lib,
    ).craft_item
    lib.write(item)
    merged = driver.reflect(
        spec=spec,
        feature_tags=["rule:state_machine"],
        retrieved=[item],
        incorporated=["state-machine-playbook"],
        gate=FAILED,
        library=lib,
    ).craft_item
    # canonical id, no instance-identifier leak (generic), non-trivial guidance
    assert is_canonical(merged.id)
    assert merged.generic is True
    assert project_strip_lint(merged.body, spec) == []
    assert len(merged.body) > 40


def test_g3_impact_updates_when_canonical_item_reused(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    spec = load_spec(ORDERS)
    driver = FakeDriver(validated_against=VA, last_validated=TS)
    _precover_universals(lib)
    item = driver.reflect(
        spec=spec,
        feature_tags=["rule:state_machine"],
        retrieved=[],
        incorporated=[],
        gate=PASSED,
        library=lib,
    ).craft_item
    lib.write(item)
    # two reuses with mixed outcomes -> running metrics reflect them (harmful-craft guard)
    update_craft_metrics(lib, ["state-machine-playbook"], first_pass=True, effector_retries=0)
    update_craft_metrics(lib, ["state-machine-playbook"], first_pass=False, effector_retries=2)
    m = lib.read("state-machine-playbook").metrics
    assert m["uses"] == 2
    assert m["mean_effector_retries"] == 1.0
    assert m["first_pass_gate_rate"] == 0.5
