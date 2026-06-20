"""Per-craft impact tracking + harmful-craft quarantine (ADR-0020 §4, gate G3).

The mandatory control run (Run B) estimates whether craft adds value *in aggregate* —
it catches *absent* craft. It does NOT catch *harmful* craft: a bad reflection that
writes a misleading playbook which, when reused, makes the effector worse. So per craft
item we track the outcomes of tasks where it was **reused** (the ``metrics`` block in
``skill-manifest.schema.json``: ``uses``, ``mean_effector_retries``,
``first_pass_gate_rate``) against a running baseline over all tasks, and quarantine an
item whose reuse correlates with worse-than-baseline outcomes (ADR-0013 quarantine →
retrieval already skips non-active items). T-1.4 reports per-craft impact.
"""

from __future__ import annotations

from dataclasses import dataclass

from harness.craft import CraftItem, CraftLibrary


@dataclass
class RunningBaseline:
    """Running mean effector-retries and first-pass rate over ALL tasks (the bar a
    craft item's reuse outcomes are judged against)."""

    mean_retries: float = 0.0
    first_pass_rate: float = 0.0
    n: int = 0

    def update(self, *, first_pass: bool, effector_retries: int) -> None:
        self.mean_retries = (self.mean_retries * self.n + effector_retries) / (self.n + 1)
        self.first_pass_rate = (self.first_pass_rate * self.n + (1.0 if first_pass else 0.0)) / (
            self.n + 1
        )
        self.n += 1


def _with_metrics(item: CraftItem, metrics: dict) -> CraftItem:
    return CraftItem(
        id=item.id,
        kind=item.kind,
        summary=item.summary,
        when_to_use=item.when_to_use,
        body=item.body,
        tags=list(item.tags),
        tests=list(item.tests),
        version=item.version,
        scope=item.scope,
        generic=item.generic,
        status=item.status,
        validated_against=item.validated_against,
        last_validated=item.last_validated,
        metrics=metrics,
    )


def update_craft_metrics(
    library: CraftLibrary, reused_ids: list[str], *, first_pass: bool, effector_retries: int
) -> None:
    """Fold this task's outcome into the running per-item metrics of every reused craft."""
    for cid in reused_ids:
        if cid not in set(library.ids()):
            continue
        item = library.read(cid)
        m = dict(item.metrics)
        uses = int(m.get("uses", 0))
        prev_retries = float(m.get("mean_effector_retries", 0.0))
        prev_fp = float(m.get("first_pass_gate_rate", 0.0))
        m["mean_effector_retries"] = (prev_retries * uses + effector_retries) / (uses + 1)
        m["first_pass_gate_rate"] = (prev_fp * uses + (1.0 if first_pass else 0.0)) / (uses + 1)
        m["uses"] = uses + 1
        library.write(_with_metrics(item, m))


def quarantine_harmful(
    library: CraftLibrary, baseline: RunningBaseline, *, min_uses: int = 3
) -> list[str]:
    """Quarantine active craft whose reuse correlates with worse-than-baseline outcomes.

    Conservative: needs at least ``min_uses`` reuses (enough evidence) AND strictly more
    mean retries than baseline AND a lower first-pass rate than baseline. Returns the
    ids quarantined; quarantined items are no longer retrieved (ADR-0013)."""
    quarantined: list[str] = []
    for cid in library.ids():
        item = library.read(cid)
        if item.status != "active":
            continue
        m = item.metrics
        uses = int(m.get("uses", 0))
        if uses < min_uses:
            continue
        worse_retries = float(m.get("mean_effector_retries", 0.0)) > baseline.mean_retries
        worse_first_pass = float(m.get("first_pass_gate_rate", 0.0)) < baseline.first_pass_rate
        if worse_retries and worse_first_pass:
            library.write(_with_metrics(_as_quarantined(item), dict(m)))
            quarantined.append(cid)
    return quarantined


def _as_quarantined(item: CraftItem) -> CraftItem:
    return CraftItem(
        id=item.id,
        kind=item.kind,
        summary=item.summary,
        when_to_use=item.when_to_use,
        body=item.body,
        tags=list(item.tags),
        tests=list(item.tests),
        version=item.version,
        scope=item.scope,
        generic=item.generic,
        status="quarantined",
        validated_against=item.validated_against,
        last_validated=item.last_validated,
        metrics=dict(item.metrics),
    )
