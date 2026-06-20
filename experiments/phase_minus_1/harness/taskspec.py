"""Build the effector's TaskSpec from the instance spec + retrieved craft.

This is the *only* thing the effector receives: the spec, the pinned API
conventions, the boot/DoD contract, and any retrieved orchestration craft. It
NEVER contains the contract tests or any harness internals — that separation is
what keeps the acceptance suite held-out (domain.md §1, teaching-to-the-test
defense). The real driver/orchestrator (T-1.3) will enrich this from accumulated
craft; the spine composes it deterministically.
"""

from __future__ import annotations

import yaml

from harness.craft import CraftItem
from harness.specschema import (
    CompositeUniqueRule,
    CrossFieldRule,
    InstanceSpec,
    RelationshipRule,
    StateMachineRule,
    business_rules_of,
)


def api_conventions(spec: InstanceSpec) -> str:
    """Human-readable statement of the conventions the spec leaves open.

    These MUST match harness/compiler.py (the suite asserts them) and are conveyed
    to the effector here so it can implement them — without seeing the tests.
    """
    lst = spec.endpoints.list
    lines = [
        "API conventions (implement exactly):",
        f"- Validation errors: HTTP {spec.rules.on_validation_error} with body "
        '{"errors": [{"field": "<name>", "message": "<why>"}]}.',
        f"- Unique-field conflict: HTTP {spec.rules.on_unique_conflict}.",
        "- Unknown id on get/update/delete: HTTP 404.",
        "- Generated/readonly fields are server-managed: ignore client-supplied "
        "values and populate them server-side; reject or ignore attempts to change "
        "them via PATCH.",
        "- The collection endpoint returns a JSON array of entities (not wrapped).",
    ]
    if lst and lst.filters:
        lines.append(
            f"- Filtering: ?<field>=<value> for fields {lst.filters} " "(booleans as true/false)."
        )
    if lst and lst.sort:
        lines.append(
            f"- Sorting: ?sort=<field> ascending, ?sort=-<field> descending, "
            f"for fields {lst.sort}."
        )
    if lst and lst.pagination:
        p = lst.pagination
        lines.append(
            f"- Pagination: ?{p.limit_param}=N&{p.offset_param}=M; default page size "
            f"{p.default_limit}; hard cap page size at {p.max_limit}."
        )
    return "\n".join(lines)


def business_rules_conventions(spec: InstanceSpec) -> str:
    """Prose pinning each business rule's expected status codes (hard tier).

    The structured ``business_rules`` block in the spec carries the data; this
    states the observable contract so the effector knows which code to return.
    Returns ``""`` when the spec has no business rules.
    """
    rules = business_rules_of(spec)
    if not rules:
        return ""
    lines = ["## Business rules (implement exactly)"]
    for r in rules:
        if isinstance(r, StateMachineRule):
            lines.append(
                f"- State machine on `{r.field}`: new entities start at `{r.initial}`; allowed "
                f"transitions {dict(r.transitions)}; an illegal transition (or any transition "
                f"from a terminal state) returns HTTP {r.on_illegal}."
                + (
                    f" Once in {list(r.locked_after)}, the entity is immutable "
                    f"(further changes return HTTP {r.on_illegal})."
                    if r.locked_after
                    else ""
                )
            )
        elif isinstance(r, CrossFieldRule):
            lines.append(
                f"- Cross-field: `{r.fields[0]}` must be {r.op} `{r.fields[1]}`; a violating "
                f"combination returns HTTP {r.on_violation}."
            )
        elif isinstance(r, RelationshipRule):
            lines.append(
                f"- Relationship: `{r.child}.{r.ref_field}` references `{r.parent}`; creating a "
                f"`{r.child}` with a non-existent `{r.parent}` returns HTTP {r.on_missing_parent}; "
                f"deleting a `{r.parent}` that still has `{r.child}` rows is `{r.on_parent_delete}`"
                + (
                    f" (returns HTTP {spec.rules.on_unique_conflict})."
                    if r.on_parent_delete == "restrict"
                    else " (children are removed too)."
                )
            )
        elif isinstance(r, CompositeUniqueRule):
            lines.append(
                f"- Composite uniqueness: the tuple {list(r.fields)} must be unique together; a "
                f"duplicate returns HTTP {r.on_conflict}."
            )
    return "\n".join(lines) + "\n"


def _fields_yaml(resource) -> list[dict]:
    return [
        {
            k: v
            for k, v in {
                "name": f.name,
                "type": f.type,
                "required": f.required,
                "readonly": f.readonly,
                "generated": f.generated,
                "unique": f.unique,
                "default": f.default,
                "min": f.min,
                "max": f.max,
                "min_len": f.min_len,
                "max_len": f.max_len,
                "pattern": f.pattern,
                "values": f.values,
                "ref": f.ref,
            }.items()
            if v not in (None, False)
        }
        for f in resource.fields
    ]


def build_taskspec(spec: InstanceSpec, retrieved_craft: list[CraftItem]) -> str:
    """Compose the effector prompt. Spec + conventions + craft only (never the tests)."""
    spec_obj: dict = {
        "id": spec.id,
        "title": spec.title,
        "tier": spec.tier,
        "resource": {
            "name": spec.resource.name,
            "path": spec.resource.path,
            "fields": _fields_yaml(spec.resource),
        },
        "endpoints": {
            e.kind: {"method": e.method, "path": e.path, "success": e.success}
            for e in spec.endpoints.present()
        },
    }
    # Hard tier: the business rules and the second (related) resource MUST drive the
    # effector — they are part of the spec, not the held-out oracle.
    if spec.business_rules:
        spec_obj["business_rules"] = spec.business_rules
    if spec.related is not None:
        spec_obj["related"] = {
            "name": spec.related.resource.name,
            "path": spec.related.resource.path,
            "fields": _fields_yaml(spec.related.resource),
            "endpoints": {
                e.kind: {"method": e.method, "path": e.path, "success": e.success}
                for e in spec.related.endpoints.present()
            },
        }
    spec_yaml = yaml.safe_dump(spec_obj, sort_keys=False)

    parts = [
        f"# TaskSpec: build the {spec.title} ({spec.id})",
        "",
        "## Intent restatement",
        f"Build a tested {spec.tier}-tier CRUD/REST service for the `{spec.resource.name}` "
        f"resource at `{spec.resource.path}`, exactly matching the specification below. "
        "You are given the SPEC ONLY. There are independent, held-out acceptance tests you "
        "will NOT see; do not try to guess or game them — implement the spec faithfully.",
        "",
        "## Stack (fixed)",
        "Python 3.11 + FastAPI + file-based SQLite. Single worker.",
        "",
        "## Boot contract",
        "- Expose `./run.sh` that starts the service listening on `$PORT`.",
        "- Expose `GET /healthz` returning HTTP 200 once the service is ready.",
        "",
        "## Specification",
        "```yaml",
        spec_yaml.strip(),
        "```",
        "",
        f"## {api_conventions(spec)}",
        "",
        business_rules_conventions(spec),
        "## Definition of Done",
        "- Implement every endpoint and rule above.",
        "- Ship your own unit tests; lint clean; the service must boot via ./run.sh.",
        "- Do NOT weaken or remove tests, and do not hard-code responses.",
        "",
        "## Non-goals",
        "- Do not add authentication, rate limiting, or features not in the spec.",
    ]

    if retrieved_craft:
        parts += ["", "## Reusable craft (retrieved orchestration playbooks)"]
        for c in retrieved_craft:
            parts += [f"### {c.id} — {c.summary}", c.body.strip()]

    return "\n".join(parts)
