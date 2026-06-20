"""Flat, on-disk craft library + per-task reuse counter (T-1.1 scope).

A craft item is a Plane-B artifact (orchestration playbook or utility) stored as
``<root>/<id>/manifest.json`` + ``<root>/<id>/body.md``. Manifests are validated
against ``memory/skill-manifest.schema.json`` on write AND read, fail-closed — a
tampered or malformed manifest is never silently used.

Retrieval is keyword/tag based for the spine (deterministic, zero cost), behind a
small interface so the protocol's "simple vector retrieval" can be swapped in for
the real 30-task runs (T-1.3) without touching the runner. The reuse counter
records, per task, which craft ids were *retrieved* and which were actually
*reused* — the decisive Phase -1 signal (domain.md §6).

Flat only: NO promotion gate, NO dream, NO graph.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "memory" / "skill-manifest.schema.json"

# Manifest keys that are part of the executable skill-manifest contract.
_MANIFEST_KEYS = {
    "id",
    "kind",
    "summary",
    "when_to_use",
    "tests",
    "version",
    "scope",
    "generic",
    "status",
    "validated_against",
    "last_validated",
    "tags",
    "metrics",
}


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


@dataclass
class CraftItem:
    id: str
    kind: str  # orchestration | code
    summary: str
    when_to_use: str
    body: str
    tags: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=lambda: ["manual-seed"])
    version: str = "1.0.0"
    scope: str = "local"
    generic: bool = True
    status: str = "active"
    validated_against: dict[str, Any] = field(
        default_factory=lambda: {"models": ["unknown"], "effector_version": "unknown"}
    )
    last_validated: str = "1970-01-01T00:00:00Z"
    metrics: dict[str, Any] = field(default_factory=dict)

    def manifest(self) -> dict:
        """The schema-governed manifest (everything except the free-form body)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "summary": self.summary,
            "when_to_use": self.when_to_use,
            "tests": list(self.tests),
            "version": self.version,
            "scope": self.scope,
            "generic": self.generic,
            "status": self.status,
            "validated_against": self.validated_against,
            "last_validated": self.last_validated,
            "tags": list(self.tags),
            "metrics": self.metrics,
        }


@dataclass
class CraftUsage:
    task_id: str
    retrieved: list[str]
    reused: list[str]


class CraftLibrary:
    """Read/write/retrieve craft items with a usage log under ``root``."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._schema = _load_schema()

    # -- persistence -------------------------------------------------------- #
    def _dir(self, craft_id: str) -> Path:
        return self.root / craft_id

    def write(self, item: CraftItem) -> Path:
        manifest = item.manifest()
        jsonschema.validate(manifest, self._schema)  # fail-closed
        d = self._dir(item.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        (d / "body.md").write_text(item.body)
        return d

    def read(self, craft_id: str) -> CraftItem:
        d = self._dir(craft_id)
        manifest = json.loads((d / "manifest.json").read_text())
        jsonschema.validate(manifest, self._schema)  # fail-closed on tampering
        body = (d / "body.md").read_text() if (d / "body.md").exists() else ""
        return CraftItem(
            id=manifest["id"],
            kind=manifest["kind"],
            summary=manifest["summary"],
            when_to_use=manifest["when_to_use"],
            body=body,
            tags=list(manifest.get("tags", [])),
            tests=list(manifest.get("tests", [])),
            version=manifest["version"],
            scope=manifest["scope"],
            generic=manifest["generic"],
            status=manifest["status"],
            validated_against=manifest["validated_against"],
            last_validated=manifest["last_validated"],
            metrics=manifest.get("metrics", {}),
        )

    def ids(self) -> list[str]:
        return sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and (p / "manifest.json").exists()
        )

    # -- retrieval (keyword/tag; swappable for vectors at T-1.3) ------------- #
    def retrieve(
        self,
        *,
        tags: list[str] | None = None,
        text: str | None = None,
        limit: int | None = None,
    ) -> list[CraftItem]:
        """Return active craft items matching ``tags`` (any) and/or ``text``.

        Deterministic: scored, then ordered by (-score, id). Quarantined and
        deprecated items are never returned (ADR-0013 retrieval discipline).
        """
        tagset = {t.lower() for t in (tags or [])}
        needle = (text or "").lower()
        scored: list[tuple[int, str, CraftItem]] = []
        for cid in self.ids():
            item = self.read(cid)
            if item.status != "active":
                continue
            score = 0
            item_tags = {t.lower() for t in item.tags}
            score += len(tagset & item_tags)
            if needle:
                haystack = f"{item.summary} {item.when_to_use} {item.body}".lower()
                if needle in haystack:
                    score += 1
            if score > 0 or (not tagset and not needle):
                scored.append((score, cid, item))
        scored.sort(key=lambda t: (-t[0], t[1]))
        items = [it for _, _, it in scored]
        return items[:limit] if limit is not None else items

    # -- reuse counter ------------------------------------------------------ #
    def _usage_path(self) -> Path:
        return self.root / "usage.jsonl"

    def record_usage(self, task_id: str, retrieved: list[str], reused: list[str]) -> CraftUsage:
        if not set(reused) <= set(retrieved):
            raise ValueError("reused craft ids must be a subset of retrieved ids")
        usage = CraftUsage(task_id=task_id, retrieved=list(retrieved), reused=list(reused))
        with self._usage_path().open("a") as fh:
            fh.write(json.dumps(asdict(usage)) + "\n")
        return usage

    def usage_for(self, task_id: str) -> CraftUsage | None:
        path = self._usage_path()
        if not path.exists():
            return None
        last: CraftUsage | None = None
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec["task_id"] == task_id:
                last = CraftUsage(
                    task_id=rec["task_id"], retrieved=rec["retrieved"], reused=rec["reused"]
                )
        return last


# --------------------------------------------------------------------------- #
# Spine seed
# --------------------------------------------------------------------------- #
_FASTAPI_SQLITE_BODY = """# Craft: fastapi-sqlite-scaffold

Reusable orchestration playbook for the spec -> CRUD-service domain.

When driving the coding effector to build a spec-described CRUD service on the
fixed Phase -1 stack (Python 3.11 + FastAPI + SQLite), the TaskSpec should:

- expose `./run.sh` that starts the service on `$PORT` and a `GET /healthz`
  returning 200 when ready (boot contract, domain.md §1);
- use **file-based** SQLite with a single worker (in-memory + multiple
  connections loses rows under black-box testing);
- return validation errors as `422 {"errors": [{"field", "message"}]}`;
- return `409` on a unique-field conflict and `404` for unknown ids;
- treat generated/readonly fields as server-managed (ignore client-supplied
  values; populate them server-side);
- implement list filtering as `?<field>=<value>` and sorting as
  `?sort=<field>` / `?sort=-<field>`, capped at `max_limit`.

These are the failure modes the effector most often gets subtly wrong; stating
them up front reduces effector retries.
"""


def seed_default_craft(
    lib: CraftLibrary,
    *,
    validated_against: dict | None = None,
    last_validated: str = "2026-06-19T00:00:00Z",
) -> list[str]:
    """Hand-seed the spine's single craft item so retrieve->reuse is exercised.

    The real orchestrator (T-1.3) will *write* craft after each passed task; for
    the spine we seed one item so the reuse counter is non-trivially exercised
    end-to-end (per the operator's orchestrator-seam note).
    """
    item = CraftItem(
        id="fastapi-sqlite-scaffold",
        kind="orchestration",
        summary="Playbook for driving the effector to build a FastAPI+SQLite CRUD service.",
        when_to_use="When building a spec-described CRUD/REST service on the Phase -1 stack.",
        body=_FASTAPI_SQLITE_BODY,
        tags=["crud", "fastapi", "sqlite", "scaffold", "rest"],
        tests=["spine-seed"],
        version="1.0.0",
        scope="local",
        generic=True,
        status="active",
        validated_against=validated_against
        or {"models": ["claude-opus-4-8"], "effector_version": "claude-code-cli"},
        last_validated=last_validated,
    )
    lib.write(item)
    return ["fastapi-sqlite-scaffold"]
