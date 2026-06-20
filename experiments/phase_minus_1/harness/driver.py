"""The Phase −1 driver/orchestrator model layer (ADR-0020 §1-§4; T-1.3).

The driver is the agent that, per task, turns the instance spec + retrieved craft into
the effector's TaskSpec (Step B: **compose**) and afterward decides whether to grow the
craft library (Step E: **reflect**). These are the only driver MODEL calls, so their
spend is ``model_cost_usd``, accounted separately from the effector (ADR-0015).

Invariants enforced here:

* **Fresh context per task** — drivers are STATELESS: ``compose``/``reflect`` build a
  fresh ``messages=[system, user]`` from the call's inputs only; no conversation, no
  scratchpad, nothing persists on the instance across tasks. The only cross-task state
  is the on-disk craft library (the orchestrator owns it).
* **Byte-identical prompt across Run A/B** — the system prompt is the frozen
  :data:`DRIVER_SYSTEM_PROMPT`; both runs use the same driver with the same decoding.
* **Verified-incorporated reuse** — compose emits a ``<!-- craft:<id> -->`` marker for
  each incorporated item; :func:`verify_incorporated` confirms the guidance actually
  appears, so reuse is not a gameable self-report (ADR-0020 §5).
* **Held-out integrity** — the base TaskSpec is the deterministic spec+conventions
  (``build_taskspec``); the driver only *adds* generic craft. It never sees the tests.
* **Project-stripped craft** — a reflection that leaks an instance identifier is forced
  to SKIP (the lint guard), so non-generic craft never reaches the library.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from harness.craft import CraftItem
from harness.reflection import (
    TAXONOMY,
    canonical_for_feature,
    craft_templates_to_write,
    is_canonical,
    nearest_canonical_id,
    project_strip_lint,
    reflect_on_signal,
    taxonomy_catalog,
    uncovered_relevant_craft_ids,
)
from harness.specschema import InstanceSpec
from harness.taskspec import build_taskspec, spec_digest

# --------------------------------------------------------------------------- #
# Frozen driver prompt — BYTE-IDENTICAL across Run A and Run B (parity invariant).
# Edit only by re-pinning the run; the orchestrator asserts A and B share it exactly.
# --------------------------------------------------------------------------- #
DRIVER_SYSTEM_PROMPT = (
    "You are the orchestration driver for a spec→CRUD-service experiment. Per task you "
    "do two things and nothing else. COMPOSE: given an instance spec and a set of "
    "retrieved orchestration playbooks (craft), select ONLY the craft that is genuinely "
    "relevant to THIS spec and will reduce the coding effector's mistakes; do not pad. "
    "REFLECT: after the effector is graded, decide whether to WRITE a new generic "
    "playbook, UPDATE an existing one, or SKIP. Craft MUST be portable and "
    "project-stripped: never name a resource, path, or field from the instance; state "
    "only generic, reusable orchestration judgment (TaskSpec patterns, known effector "
    "failure modes, contract recipes). Prefer SKIP over writing vague or duplicate "
    "craft. Always answer by calling the provided tool."
)

_CRAFT_MARKER = "<!-- craft:{id} -->"


def craft_marker(craft_id: str) -> str:
    return _CRAFT_MARKER.format(id=craft_id)


def verify_incorporated(taskspec_text: str, declared: list[str]) -> list[str]:
    """The declared-incorporated ids whose guidance marker actually appears (reuse=this)."""
    return [cid for cid in declared if craft_marker(cid) in taskspec_text]


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GateOutcome:
    contract_passed: bool
    dod_passed: bool
    effector_retries: int
    first_pass: bool
    failing_case_ids: list[str] = field(default_factory=list)


@dataclass
class ComposeResult:
    taskspec_text: str
    incorporated: list[str]
    tokens_in: int
    tokens_out: int
    model: str


@dataclass
class ReflectResult:
    action: str  # WRITE | UPDATE | SKIP
    craft_item: CraftItem | None
    target_id: str | None
    tokens_in: int
    tokens_out: int
    model: str
    rationale: str


class Driver(Protocol):
    system_prompt: str

    def compose(self, *, spec: InstanceSpec, retrieved: list[CraftItem]) -> ComposeResult: ...

    def reflect(
        self,
        *,
        spec: InstanceSpec,
        feature_tags: list[str],
        retrieved: list[CraftItem],
        incorporated: list[str],
        gate: GateOutcome,
        library,
    ) -> ReflectResult: ...


# --------------------------------------------------------------------------- #
# Shared rendering / cost helpers
# --------------------------------------------------------------------------- #
def render_taskspec(spec: InstanceSpec, incorporated: list[tuple[CraftItem, str]]) -> str:
    """Base TaskSpec (spec + conventions + boot/DoD, as today) + incorporated craft.

    Each incorporated item is rendered with a verifiable marker so reuse is auditable.
    The base never contains the contract tests (held-out integrity)."""
    base = build_taskspec(spec, [])
    if not incorporated:
        return base
    parts = [base, "", "## Reusable craft (incorporated orchestration playbooks)"]
    for item, note in incorporated:
        parts.append(craft_marker(item.id))
        parts.append(f"### {item.id} — {item.summary}")
        if note:
            parts.append(f"_Apply here:_ {note}")
        parts.append(item.body.strip())
    return "\n".join(parts)


def _toklen(text: str) -> int:
    """Deterministic synthetic token count (~4 chars/token) for zero-spend accounting."""
    return max(1, len(text) // 4)


# --------------------------------------------------------------------------- #
# Fake driver (deterministic, zero spend) — drives the loop in CI
# --------------------------------------------------------------------------- #
class FakeDriver:
    """Deterministic stand-in for the real driver. Composes by incorporating ALL
    retrieved craft and reflects by the locked reflect-on-signal policy over the
    taxonomy. Reports a non-zero (synthetic) ``model_cost`` so the driver-cost field is
    exercised end-to-end. Stateless: holds only run-level constants."""

    def __init__(self, *, validated_against: dict, last_validated: str):
        self.system_prompt = DRIVER_SYSTEM_PROMPT
        self._validated_against = dict(validated_against)
        self._last_validated = last_validated

    def _va(self) -> dict:
        return dict(self._validated_against)

    def compose(self, *, spec: InstanceSpec, retrieved: list[CraftItem]) -> ComposeResult:
        incorporated = [(it, "") for it in retrieved]
        taskspec_text = render_taskspec(spec, incorporated)
        prompt_chars = len(DRIVER_SYSTEM_PROMPT) + len(spec_digest(spec))
        prompt_chars += sum(len(it.body) + len(it.summary) for it in retrieved)
        return ComposeResult(
            taskspec_text=taskspec_text,
            incorporated=[it.id for it in retrieved],
            tokens_in=_toklen("x" * prompt_chars),
            tokens_out=_toklen(taskspec_text),
            model=self._validated_against["models"][0],
        )

    def reflect(
        self,
        *,
        spec: InstanceSpec,
        feature_tags: list[str],
        retrieved: list[CraftItem],
        incorporated: list[str],
        gate: GateOutcome,
        library,
    ) -> ReflectResult:
        uncovered = uncovered_relevant_craft_ids(feature_tags, library)
        tokens_in = _toklen(DRIVER_SYSTEM_PROMPT + spec_digest(spec) + " ".join(feature_tags))
        model = self._validated_against["models"][0]
        if not reflect_on_signal(
            effector_retries=gate.effector_retries,
            first_pass=gate.first_pass,
            uncovered_tags=uncovered,
        ):
            return ReflectResult("SKIP", None, None, tokens_in, 4, model, "no learning signal")

        # UPDATE first when the effector STRUGGLED despite craft it used -> refine the
        # canonical item (a refinement the failure revealed, ADR-0020 §4).
        failure = gate.effector_retries > 0 or not gate.first_pass
        if failure:
            target = _update_target(feature_tags, incorporated, library)
            if target is not None:
                updated = _bump(target, self._va(), self._last_validated)
                return ReflectResult(
                    "UPDATE",
                    updated,
                    target.id,
                    tokens_in,
                    _toklen(updated.body),
                    model,
                    f"effector struggled despite {target.id}; bumped to {updated.version}",
                )

        # WRITE the highest-priority relevant-but-missing playbook.
        templates = craft_templates_to_write(feature_tags, library)
        if templates:
            tpl = templates[0]
            item = tpl.to_craft_item(
                validated_against=self._va(), last_validated=self._last_validated
            )
            return ReflectResult(
                "WRITE",
                item,
                None,
                tokens_in,
                _toklen(item.body),
                model,
                f"covered new feature -> wrote {tpl.craft_id}",
            )

        # Fall back to refining a covered item if there is nothing new to write.
        target = _update_target(feature_tags, incorporated, library)
        if target is not None:
            updated = _bump(target, self._va(), self._last_validated)
            return ReflectResult(
                "UPDATE",
                updated,
                target.id,
                tokens_in,
                _toklen(updated.body),
                model,
                f"refined {target.id} to {updated.version}",
            )
        return ReflectResult("SKIP", None, None, tokens_in, 4, model, "nothing to refine")


def _update_target(feature_tags, incorporated, library) -> CraftItem | None:
    """Pick the canonical item to UPDATE: a reused item first, else any covered feature."""
    for cid in incorporated:
        if cid in set(library.ids()):
            return library.read(cid)
    for tag in feature_tags:
        existing = canonical_for_feature(tag, library)
        if existing is not None:
            return existing
    return None


def _bump(item: CraftItem, validated_against: dict, last_validated: str) -> CraftItem:
    major, minor, patch = item.version.split(".")
    new_version = f"{major}.{minor}.{int(patch) + 1}"
    return CraftItem(
        id=item.id,
        kind=item.kind,
        summary=item.summary,
        when_to_use=item.when_to_use,
        body=item.body,
        tags=list(item.tags),
        tests=list(item.tests),
        version=new_version,
        scope=item.scope,
        generic=item.generic,
        status=item.status,
        validated_against=validated_against,
        last_validated=last_validated,
        metrics=dict(item.metrics),
    )


# --------------------------------------------------------------------------- #
# Real driver: Anthropic SDK (Sonnet 4.6 + Haiku 4.5 fallback). Tested with an
# injected fake client; never makes real calls under test/CI.
# --------------------------------------------------------------------------- #
_COMPOSE_TOOL = {
    "name": "submit_composition",
    "description": "Submit which retrieved craft to incorporate into the effector TaskSpec.",
    "input_schema": {
        "type": "object",
        "properties": {
            "incorporated": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "note": {"type": "string", "description": "one-line application note"},
                    },
                    "required": ["id"],
                },
            }
        },
        "required": ["incorporated"],
    },
}

_CANONICAL_IDS = sorted(TAXONOMY)

_REFLECT_TOOL = {
    "name": "submit_reflection",
    "description": (
        "Decide WRITE a new / UPDATE an existing / SKIP a generic, project-stripped craft "
        "item. craft_id and target_id MUST be one of the canonical taxonomy ids (one "
        "canonical item per feature; evolve via UPDATE, do not invent new ids)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"enum": ["WRITE", "UPDATE", "SKIP"]},
            "craft_id": {"enum": _CANONICAL_IDS},
            "target_id": {"enum": _CANONICAL_IDS},
            "summary": {"type": "string"},
            "when_to_use": {"type": "string"},
            "body": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
        "required": ["action", "rationale"],
    },
}


class AnthropicDriver:
    """Drives the real Sonnet 4.6 (temp 0) driver with a Haiku 4.5 fallback. The client
    is injectable so request construction + parsing are testable with zero spend."""

    def __init__(
        self,
        *,
        model: str,
        fallback_model: str,
        temperature: float,
        validated_against: dict,
        last_validated: str,
        max_tokens: int = 8000,
        client: Any = None,
        fallback_client: Any = None,
        max_retries: int = 5,
        backoff_base: float = 1.5,
        sleep: Any = None,
    ):
        self.system_prompt = DRIVER_SYSTEM_PROMPT
        self.model = model
        self.fallback_model = fallback_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._validated_against = dict(validated_against)
        self._last_validated = last_validated
        self._client = client
        self._fallback_client = fallback_client
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep if sleep is not None else time.sleep

    # -- transport --------------------------------------------------------- #
    def _client_for(self, primary: bool) -> Any:
        if primary:
            if self._client is None:  # pragma: no cover - real-network path
                import anthropic

                self._client = anthropic.Anthropic()
            return self._client
        if self._fallback_client is None:  # pragma: no cover - real-network path
            import anthropic

            self._fallback_client = anthropic.Anthropic()
        return self._fallback_client

    def _call(self, tool: dict, user: str) -> tuple[dict, int, int, str]:
        """Forced-tool call with bounded retry/backoff per model, then a Sonnet→Haiku
        fallback. Returns (tool_input, tin, tout, model). A transient 429/overload retries
        the SAME model with exponential backoff before falling back, so a long run survives
        rate-limit bursts after real spend has started; a non-retryable error falls back
        immediately; exhausting both raises the last error (compose runs before the effector,
        so a hard rate-limit fails fast with no wasted effector spend)."""
        kwargs = dict(
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=self.system_prompt,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user}],
        )
        last_exc: Exception | None = None
        for model, primary in ((self.model, True), (self.fallback_model, False)):
            client = self._client_for(primary)
            for attempt in range(self.max_retries + 1):
                try:
                    resp = client.messages.create(model=model, **kwargs)
                    tin, tout = int(resp.usage.input_tokens), int(resp.usage.output_tokens)
                    return _first_tool_input(resp), tin, tout, model
                except Exception as exc:  # noqa: BLE001 - classified by _is_retryable
                    last_exc = exc
                    if attempt < self.max_retries and _is_retryable(exc):
                        self._sleep(self.backoff_base**attempt)
                        continue
                    break  # non-retryable or retries exhausted -> try the fallback model
        raise last_exc  # type: ignore[misc]

    def _va(self, model: str) -> dict:
        """validated_against records the driver model that actually produced the craft
        (the Haiku fallback is recorded if it fired — operator's parity note)."""
        va = dict(self._validated_against)
        va["models"] = sorted({*va.get("models", []), model})
        return va

    # -- compose ----------------------------------------------------------- #
    def compose(self, *, spec: InstanceSpec, retrieved: list[CraftItem]) -> ComposeResult:
        user = _compose_user_message(spec, retrieved)
        tool_input, tin, tout, model = self._call(_COMPOSE_TOOL, user)
        by_id = {it.id: it for it in retrieved}
        incorporated: list[tuple[CraftItem, str]] = []
        for entry in tool_input.get("incorporated", []):
            cid = entry.get("id")
            if cid in by_id:  # only genuinely-retrieved craft can be incorporated
                incorporated.append((by_id[cid], entry.get("note", "")))
        taskspec_text = render_taskspec(spec, incorporated)
        return ComposeResult(
            taskspec_text=taskspec_text,
            incorporated=[it.id for it, _ in incorporated],
            tokens_in=tin,
            tokens_out=tout,
            model=model,
        )

    # -- reflect ----------------------------------------------------------- #
    def reflect(
        self,
        *,
        spec: InstanceSpec,
        feature_tags: list[str],
        retrieved: list[CraftItem],
        incorporated: list[str],
        gate: GateOutcome,
        library,
    ) -> ReflectResult:
        user = _reflect_user_message(spec, feature_tags, retrieved, incorporated, gate, library)
        ti, tin, tout, model = self._call(_REFLECT_TOOL, user)
        action = ti.get("action", "SKIP")
        rationale = ti.get("rationale", "")
        if action == "SKIP":
            return ReflectResult("SKIP", None, None, tin, tout, model, rationale or "skip")

        body = ti.get("body", "")
        # Lint guard: a reflection that leaks an instance identifier is forced to SKIP,
        # so non-generic (potentially harmful) craft never reaches the library.
        leaks = project_strip_lint(
            f"{ti.get('summary', '')} {ti.get('when_to_use', '')} {body}", spec
        )
        if leaks:
            return ReflectResult(
                "SKIP",
                None,
                None,
                tin,
                tout,
                model,
                f"reflection rejected: craft would leak instance identifiers {leaks}",
            )
        # Canonicalize the id to the taxonomy (G1 Option A): never persist a free-form id
        # and never drop the lesson — remap to the nearest canonical item (ADR-0020 §4).
        tags = list(ti.get("tags", []))
        raw_id = ti.get("target_id") or ti.get("craft_id") or ""
        craft_id = nearest_canonical_id(
            raw_id, tags, ti.get("summary", ""), ti.get("when_to_use", "")
        )
        if not is_canonical(raw_id) and raw_id:
            rationale = f"{rationale} [remapped {raw_id!r}->{craft_id!r}]"
        # Presence-based dedupe: an id that already exists is an UPDATE (bump), not a
        # duplicate WRITE — one canonical item per feature, evolved over time.
        present_active = {cid for cid in library.ids() if library.read(cid).status == "active"}
        if craft_id in present_active:
            existing = library.read(craft_id)
            major, minor, patch = existing.version.split(".")
            version = f"{major}.{minor}.{int(patch) + 1}"
            final_action, target_id = "UPDATE", craft_id
        else:
            version, final_action, target_id = "1.0.0", "WRITE", None
        item = CraftItem(
            id=craft_id,
            kind="orchestration",
            summary=ti.get("summary", craft_id),
            when_to_use=ti.get("when_to_use", ""),
            body=body,
            tags=tags,
            tests=["driver-reflection"],
            version=version,
            scope="local",
            generic=True,
            status="active",
            validated_against=self._va(model),
            last_validated=self._last_validated,
        )
        return ReflectResult(final_action, item, target_id, tin, tout, model, rationale)


_RETRYABLE_EXC_NAMES = {
    "RateLimitError",
    "InternalServerError",
    "APIConnectionError",
    "APITimeoutError",
    "APIStatusError",
    "OverloadedError",
}
_RETRYABLE_SUBSTRINGS = ("rate_limit", "overloaded", "429", "529", "timeout", "connection")


def _is_retryable(exc: Exception) -> bool:
    """Transient API errors worth retrying the same model for (anthropic exception type
    names + message heuristics, so we needn't import anthropic to classify)."""
    if type(exc).__name__ in _RETRYABLE_EXC_NAMES:
        return True
    msg = str(exc).lower()
    return any(s in msg for s in _RETRYABLE_SUBSTRINGS)


def _first_tool_input(resp: Any) -> dict:
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            return dict(block.input)
    return {}


def _compose_user_message(spec: InstanceSpec, retrieved: list[CraftItem]) -> str:
    cands = [
        {"id": it.id, "summary": it.summary, "when_to_use": it.when_to_use, "body": it.body}
        for it in retrieved
    ]
    return (
        "Instance (spec digest, NOT the tests):\n"
        f"{spec_digest(spec)}\n\n"
        "Retrieved craft candidates (incorporate only the relevant ones):\n"
        f"{json.dumps(cands, indent=2)}\n\n"
        "Call submit_composition with the ids to incorporate (and a one-line note each)."
    )


def _reflect_user_message(spec, feature_tags, retrieved, incorporated, gate, library) -> str:
    return (
        "Instance (spec digest):\n"
        f"{spec_digest(spec)}\n"
        f"feature_tags: {feature_tags}\n"
        f"retrieved craft: {[it.id for it in retrieved]}\n"
        f"incorporated craft: {incorporated}\n"
        f"gate: contract_passed={gate.contract_passed} dod_passed={gate.dod_passed} "
        f"retries={gate.effector_retries} first_pass={gate.first_pass} "
        f"failing_cases={gate.failing_case_ids}\n"
        f"existing library craft ids: {library.ids()}\n\n"
        "Canonical craft taxonomy — choose craft_id/target_id from THESE ids only (WRITE a "
        "not-yet-present one, UPDATE a present one; do not invent new ids):\n"
        f"{json.dumps(taxonomy_catalog(), indent=2)}\n\n"
        "Decide WRITE a new generic playbook, UPDATE an existing one, or SKIP. "
        "Craft MUST be project-stripped (no resource/path/field names). Call submit_reflection."
    )
