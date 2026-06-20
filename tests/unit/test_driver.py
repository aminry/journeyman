"""Unit tests for the driver/orchestrator model layer (ADR-0020 §1-§4; T-1.3).

The driver is the locus of "judgment that compounds". Two implementations behind one
interface:

* :class:`FakeDriver` — deterministic, zero-spend; drives the whole loop in CI so the
  orchestrator/A-B harness is provable without real model calls. It still produces a
  non-zero ``model_cost`` (the driver field must be first-class, ADR-0015).
* :class:`AnthropicDriver` — the real Sonnet 4.6 (temp 0) + Haiku 4.5 fallback driver.
  Tested here with an INJECTED fake client so request construction, structured parsing,
  the project-strip guard, and the fallback path are proven with ZERO spend.

Both share a BYTE-IDENTICAL frozen system prompt (the Run A/B parity invariant).
"""

from __future__ import annotations

from pathlib import Path

from harness.craft import CraftItem, CraftLibrary
from harness.driver import (
    DRIVER_SYSTEM_PROMPT,
    AnthropicDriver,
    FakeDriver,
    GateOutcome,
    verify_incorporated,
)
from harness.reflection import template_for_craft_id
from harness.specschema import load_spec

REPO = Path(__file__).resolve().parents[2]
INSTANCES = REPO / "experiments" / "phase_minus_1" / "instances"
NOTES = INSTANCES / "e01_notes.spec.yaml"
BOOKS = INSTANCES / "example_books.spec.yaml"
ORDERS = INSTANCES / "h01_orders.spec.yaml"

VA = {"models": ["claude-sonnet-4-6"], "effector_version": "claude-code-cli@test"}
PASS = GateOutcome(
    contract_passed=True, dod_passed=True, effector_retries=0, first_pass=True, failing_case_ids=[]
)


def _fake_driver() -> FakeDriver:
    return FakeDriver(validated_against=VA, last_validated="2026-06-20T00:00:00Z")


def _pag_item() -> CraftItem:
    return template_for_craft_id("pagination-contract").to_craft_item(
        validated_against=VA, last_validated="2026-06-20T00:00:00Z"
    )


# --- shared prompt --------------------------------------------------------- #
def test_driver_system_prompt_is_frozen_and_nonempty() -> None:
    assert isinstance(DRIVER_SYSTEM_PROMPT, str) and len(DRIVER_SYSTEM_PROMPT) > 50
    assert _fake_driver().system_prompt == DRIVER_SYSTEM_PROMPT


# --- compose --------------------------------------------------------------- #
def test_compose_with_no_craft_produces_base_spec_only() -> None:
    spec = load_spec(BOOKS)
    res = _fake_driver().compose(spec=spec, retrieved=[])
    assert res.incorporated == []
    assert "<!-- craft:" not in res.taskspec_text
    # the base TaskSpec is still the real spec + conventions (held-out: never tests)
    assert "Specification" in res.taskspec_text
    assert "compile_contract_suite" not in res.taskspec_text
    assert res.tokens_in > 0 and res.tokens_out > 0


def test_compose_incorporates_retrieved_craft_with_verifiable_markers() -> None:
    spec = load_spec(BOOKS)
    item = _pag_item()
    res = _fake_driver().compose(spec=spec, retrieved=[item])
    assert "pagination-contract" in res.incorporated
    assert "<!-- craft:pagination-contract -->" in res.taskspec_text
    # verified-incorporated: the declared ids whose marker actually appears
    assert verify_incorporated(res.taskspec_text, res.incorporated) == ["pagination-contract"]


def test_verify_incorporated_drops_unmarked_claims() -> None:
    # a driver that *claims* incorporation without the guidance present must not count
    assert verify_incorporated("no markers here", ["pagination-contract"]) == []


def test_compose_cost_rises_with_more_craft() -> None:
    spec = load_spec(BOOKS)
    d = _fake_driver()
    base = d.compose(spec=spec, retrieved=[])
    withc = d.compose(spec=spec, retrieved=[_pag_item()])
    assert withc.tokens_in > base.tokens_in


# --- reflect (fake) -------------------------------------------------------- #
def test_reflect_skips_when_no_signal(tmp_path: Path) -> None:
    """Clean first-pass AND fully covered -> SKIP (the default; no library bloat)."""
    lib = CraftLibrary(tmp_path)
    # pre-cover everything relevant to NOTES so there is no uncovered feature
    spec = load_spec(NOTES)
    from harness.reflection import craft_templates_to_write

    for tpl in craft_templates_to_write(["tier:easy", "crud"], lib):
        lib.write(tpl.to_craft_item(validated_against=VA, last_validated="2026-06-20T00:00:00Z"))
    res = _fake_driver().reflect(
        spec=spec,
        feature_tags=["tier:easy", "crud"],
        retrieved=[],
        incorporated=[],
        gate=PASS,
        library=lib,
    )
    assert res.action == "SKIP"
    assert res.craft_item is None


def test_reflect_writes_generic_craft_for_uncovered_feature(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    spec = load_spec(BOOKS)
    res = _fake_driver().reflect(
        spec=spec,
        feature_tags=["tier:medium", "crud", "pagination", "unique"],
        retrieved=[],
        incorporated=[],
        gate=PASS,
        library=lib,
    )
    assert res.action == "WRITE"
    assert res.craft_item is not None and res.craft_item.generic is True
    # the written craft is project-stripped and schema-valid (library write validates)
    lib.write(res.craft_item)


def test_reflect_updates_existing_craft_when_effector_struggled(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path)
    item = _pag_item()
    lib.write(item)
    spec = load_spec(BOOKS)
    failed = GateOutcome(
        contract_passed=False,
        dod_passed=True,
        effector_retries=2,
        first_pass=False,
        failing_case_ids=["pagination:max_limit"],
    )
    res = _fake_driver().reflect(
        spec=spec,
        feature_tags=["tier:medium", "crud", "pagination"],
        retrieved=[item],
        incorporated=["pagination-contract"],
        gate=failed,
        library=lib,
    )
    assert res.action == "UPDATE"
    assert res.target_id == "pagination-contract"
    # version bumped past the existing 1.0.0
    assert res.craft_item is not None and res.craft_item.version != "1.0.0"


# --- AnthropicDriver with an injected fake client (zero spend) ------------- #
class _ToolUse:
    type = "tool_use"

    def __init__(self, name: str, inp: dict):
        self.name = name
        self.input = inp


class _Usage:
    def __init__(self, i: int, o: int):
        self.input_tokens = i
        self.output_tokens = o


class _Resp:
    def __init__(self, tool_name: str, tool_input: dict, i: int = 1200, o: int = 300):
        self.content = [_ToolUse(tool_name, tool_input)]
        self.usage = _Usage(i, o)
        self.stop_reason = "tool_use"


class _FakeMessages:
    def __init__(self, resp, recorder: dict, fail: bool = False):
        self._resp = resp
        self._recorder = recorder
        self._fail = fail

    def create(self, **kwargs):
        self._recorder.update(kwargs)
        if self._fail:
            raise RuntimeError("overloaded")
        return self._resp


class _FakeClient:
    def __init__(self, resp, recorder: dict, fail: bool = False):
        self.messages = _FakeMessages(resp, recorder, fail)


class RateLimitError(Exception):
    """Name matches anthropic.RateLimitError so the driver treats it as retryable."""


class _FlakyMessages:
    def __init__(self, resp, fail_times: int, exc: Exception):
        self._resp = resp
        self._fail_times = fail_times
        self._exc = exc
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._exc
        return self._resp


class _FlakyClient:
    def __init__(self, resp, fail_times: int, exc: Exception):
        self.messages = _FlakyMessages(resp, fail_times, exc)


def test_anthropic_compose_builds_pinned_request_and_parses_incorporation() -> None:
    spec = load_spec(BOOKS)
    item = _pag_item()
    rec: dict = {}
    resp = _Resp(
        "submit_composition",
        {"incorporated": [{"id": "pagination-contract", "note": "cap page size"}]},
    )
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=_FakeClient(resp, rec),
    )
    res = drv.compose(spec=spec, retrieved=[item])
    # request is pinned: model, temperature, frozen system prompt, a forced tool
    assert rec["model"] == "claude-sonnet-4-6"
    assert rec["temperature"] == 0.0
    assert rec["system"] == DRIVER_SYSTEM_PROMPT
    assert rec["tool_choice"]["type"] == "tool"
    # parsed + rendered with a verifiable marker; cost from usage
    assert res.incorporated == ["pagination-contract"]
    assert "<!-- craft:pagination-contract -->" in res.taskspec_text
    assert res.tokens_in == 1200 and res.tokens_out == 300


def test_reflect_tool_constrains_craft_id_to_taxonomy_enum() -> None:
    from harness.driver import _REFLECT_TOOL
    from harness.reflection import TAXONOMY

    props = _REFLECT_TOOL["input_schema"]["properties"]
    assert set(props["craft_id"]["enum"]) == set(TAXONOMY)
    assert set(props["target_id"]["enum"]) == set(TAXONOMY)


def test_anthropic_reflect_remaps_noncanonical_write_to_canonical(tmp_path: Path) -> None:
    """The driver must never persist a free-form id: a non-canonical WRITE is remapped to
    the nearest canonical taxonomy id (never dropped), restoring ADR-0020 §4 + G2 grading."""
    out = {
        "action": "WRITE",
        "craft_id": "crud-medium-integer-validation-min",  # free-form, non-canonical
        "summary": "generic pagination guidance",
        "when_to_use": "list endpoints with paging",
        "body": "Honor the window params and cap the page size.",
        "tags": ["pagination"],  # the tag maps to the canonical pagination item
        "rationale": "x",
    }
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=_FakeClient(_Resp("submit_reflection", out), {}),
    )
    res = drv.reflect(
        spec=load_spec(BOOKS),
        feature_tags=["pagination"],
        retrieved=[],
        incorporated=[],
        gate=PASS,
        library=CraftLibrary(tmp_path / "lib"),
    )
    assert res.action == "WRITE"
    assert res.craft_item is not None and res.craft_item.id == "pagination-contract"  # remapped


def test_anthropic_reflect_dedupes_to_update_when_canonical_present(tmp_path: Path) -> None:
    """Presence-based dedupe: if the (canonicalized) id already exists, it's an UPDATE,
    not a duplicate WRITE — re-arming the inert dedupe guardrail the pilot exposed."""
    lib = CraftLibrary(tmp_path / "lib")
    lib.write(_pag_item())  # pagination-contract @ 1.0.0 already present
    out = {
        "action": "WRITE",  # the model says WRITE, but the canonical id already exists
        "craft_id": "novel-paging-thing",
        "summary": "refined paging",
        "when_to_use": "paging",
        "body": "Cap the page size at the configured maximum.",
        "tags": ["pagination"],
        "rationale": "x",
    }
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=_FakeClient(_Resp("submit_reflection", out), {}),
    )
    res = drv.reflect(
        spec=load_spec(BOOKS),
        feature_tags=["pagination"],
        retrieved=[_pag_item()],
        incorporated=["pagination-contract"],
        gate=PASS,
        library=lib,
    )
    assert res.action == "UPDATE"
    assert res.target_id == "pagination-contract"
    assert res.craft_item is not None and res.craft_item.version == "1.0.1"


def test_anthropic_reflect_rejects_leaky_craft_as_skip() -> None:
    """A reflection that leaks an instance identifier is forced to SKIP (lint guard),
    so harmful non-generic craft never reaches the library."""
    spec = load_spec(ORDERS)
    rec: dict = {}
    leaky = {
        "action": "WRITE",
        "craft_id": "bad-recipe",
        "summary": "orders lifecycle",
        "when_to_use": "for orders",
        "body": "Drive the orders service: pending to paid to shipped.",
        "tags": ["rule:state_machine"],
        "rationale": "x",
    }
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=_FakeClient(_Resp("submit_reflection", leaky), rec),
    )
    res = drv.reflect(
        spec=spec,
        feature_tags=["rule:state_machine"],
        retrieved=[],
        incorporated=[],
        gate=PASS,
        library=CraftLibrary(REPO / ".context" / "nonexistent_ignore"),
    )
    assert res.action == "SKIP"
    assert res.craft_item is None
    assert "leak" in res.rationale.lower()


def test_anthropic_reflect_write_builds_generic_schema_valid_craft(tmp_path: Path) -> None:
    spec = load_spec(BOOKS)
    clean = {
        "action": "WRITE",
        "craft_id": "pagination-contract",  # a canonical taxonomy id
        "summary": "Apply the default page window when none is supplied.",
        "when_to_use": "When the list endpoint declares a default window.",
        "body": "Return the configured default window when no window is requested; cap it.",
        "tags": ["pagination"],
        "rationale": "new generic lesson",
    }
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=_FakeClient(_Resp("submit_reflection", clean), {}),
    )
    res = drv.reflect(
        spec=spec,
        feature_tags=["pagination"],
        retrieved=[],
        incorporated=[],
        gate=PASS,
        library=CraftLibrary(tmp_path / "lib"),
    )
    assert res.action == "WRITE"
    assert res.craft_item is not None and res.craft_item.id == "pagination-contract"
    assert res.craft_item.generic is True
    assert "claude-sonnet-4-6" in res.craft_item.validated_against["models"]
    CraftLibrary(tmp_path / "lib2").write(res.craft_item)  # schema-valid + writable


def test_anthropic_reflect_update_bumps_existing_version(tmp_path: Path) -> None:
    lib = CraftLibrary(tmp_path / "lib")
    lib.write(_pag_item())  # pagination-contract @ 1.0.0
    spec = load_spec(BOOKS)
    upd = {
        "action": "UPDATE",
        "target_id": "pagination-contract",
        "summary": "Refined pagination contract.",
        "when_to_use": "When the list endpoint declares pagination.",
        "body": "Honor the window params; cap the page size; keep a stable total ordering.",
        "tags": ["pagination"],
        "rationale": "effector still missed the cap",
    }
    failed = GateOutcome(
        contract_passed=False,
        dod_passed=True,
        effector_retries=1,
        first_pass=False,
        failing_case_ids=["pagination:max_limit"],
    )
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=_FakeClient(_Resp("submit_reflection", upd), {}),
    )
    res = drv.reflect(
        spec=spec,
        feature_tags=["pagination"],
        retrieved=[_pag_item()],
        incorporated=["pagination-contract"],
        gate=failed,
        library=lib,
    )
    assert res.action == "UPDATE"
    assert res.target_id == "pagination-contract"
    assert res.craft_item is not None and res.craft_item.version == "1.0.1"


def test_anthropic_falls_back_to_haiku_and_records_it(tmp_path: Path) -> None:
    spec = load_spec(BOOKS)
    rec: dict = {}
    resp = _Resp("submit_composition", {"incorporated": []})
    # primary client always fails; fallback client succeeds
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=_FakeClient(resp, {}, fail=True),
        fallback_client=_FakeClient(resp, rec),
        max_retries=0,
    )
    res = drv.compose(spec=spec, retrieved=[])
    assert rec["model"] == "claude-haiku-4-5"
    assert res.model == "claude-haiku-4-5"


def test_anthropic_retries_transient_rate_limit_then_succeeds() -> None:
    """A transient 429 must not crash the run: retry the SAME model with backoff before
    falling back, so a 30-task run survives bursts after real spend has started."""
    sleeps: list[float] = []
    resp = _Resp("submit_composition", {"incorporated": []})
    client = _FlakyClient(resp, fail_times=2, exc=RateLimitError("429 rate_limit_error"))
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=client,
        max_retries=3,
        sleep=lambda d: sleeps.append(d),
    )
    res = drv.compose(spec=load_spec(BOOKS), retrieved=[])
    assert res.model == "claude-sonnet-4-6"  # recovered on the primary, no fallback
    assert client.messages.calls == 3  # 2 failures + 1 success
    assert len(sleeps) == 2  # backed off before each retry


def test_anthropic_exhausts_primary_retries_then_falls_back() -> None:
    resp = _Resp("submit_composition", {"incorporated": []})
    primary = _FlakyClient(resp, fail_times=99, exc=RateLimitError("429 rate_limit_error"))
    rec: dict = {}
    drv = AnthropicDriver(
        model="claude-sonnet-4-6",
        fallback_model="claude-haiku-4-5",
        temperature=0.0,
        validated_against=VA,
        last_validated="2026-06-20T00:00:00Z",
        client=primary,
        fallback_client=_FakeClient(resp, rec),
        max_retries=2,
        sleep=lambda d: None,
    )
    res = drv.compose(spec=load_spec(BOOKS), retrieved=[])
    assert primary.messages.calls == 3  # max_retries + 1 attempts on primary
    assert res.model == "claude-haiku-4-5"
    assert rec["model"] == "claude-haiku-4-5"
