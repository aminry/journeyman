"""Load and model a Phase -1 instance spec (domain.md §2).

The instance ``*.spec.yaml`` is the single source of truth: it drives the
effector's task AND generates the held-out contract suite. This module parses it
into typed objects the compiler can walk. It is intentionally strict about
structure so a malformed spec fails loudly here rather than silently producing a
lenient contract suite (which would invalidate the gate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SCALAR_TYPES = {
    "uuid",
    "string",
    "integer",
    "number",
    "boolean",
    "enum",
    "datetime",
    "ref",
}


class SpecError(ValueError):
    """Raised when an instance spec is missing or structurally invalid."""


@dataclass(frozen=True)
class Field:
    """One resource field and its constraints (domain.md §2)."""

    name: str
    type: str
    required: bool = False
    readonly: bool = False
    generated: bool = False
    unique: bool = False
    default: Any = None
    min: int | float | None = None
    max: int | float | None = None
    min_len: int | None = None
    max_len: int | None = None
    pattern: str | None = None
    values: list[Any] | None = None
    ref: str | None = None

    @property
    def has_default(self) -> bool:
        return self.default is not None

    @property
    def server_managed(self) -> bool:
        """Server populates it; clients must not send it."""
        return self.generated or self.readonly


@dataclass(frozen=True)
class Pagination:
    limit_param: str = "limit"
    offset_param: str = "offset"
    default_limit: int = 20
    max_limit: int = 100


@dataclass(frozen=True)
class Endpoint:
    kind: str  # create | get | list | update | delete
    method: str
    path: str
    success: int
    missing: int | None = None
    partial: bool = False
    pagination: Pagination | None = None
    filters: list[str] = field(default_factory=list)
    sort: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EndpointSet:
    create: Endpoint | None = None
    get: Endpoint | None = None
    list: Endpoint | None = None
    update: Endpoint | None = None
    delete: Endpoint | None = None

    def present(self) -> list[Endpoint]:
        return [e for e in (self.create, self.get, self.list, self.update, self.delete) if e]


@dataclass(frozen=True)
class Rules:
    on_validation_error: int = 422
    on_unique_conflict: int = 409
    timestamps_immutable: bool = False


@dataclass(frozen=True)
class ResourceSpec:
    name: str
    path: str
    fields: list[Field]

    def field(self, name: str) -> Field:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    def writable_fields(self) -> list[Field]:
        """Fields a client may send (excludes generated/readonly)."""
        return [f for f in self.fields if not f.server_managed]

    def required_writable_fields(self) -> list[Field]:
        return [f for f in self.writable_fields() if f.required]

    def unique_fields(self) -> list[Field]:
        return [f for f in self.fields if f.unique]


@dataclass(frozen=True)
class InstanceSpec:
    id: str
    title: str
    tier: str
    resource: ResourceSpec
    endpoints: EndpointSet
    rules: Rules
    business_rules: list[Any] = field(default_factory=list)


def _require(d: dict, key: str, where: str) -> Any:
    if key not in d:
        raise SpecError(f"{where}: missing required key '{key}'")
    return d[key]


def _parse_field(raw: dict, where: str) -> Field:
    name = _require(raw, "name", where)
    ftype = _require(raw, "type", f"{where}.{name}")
    if ftype not in SCALAR_TYPES:
        raise SpecError(f"{where}.{name}: unknown type '{ftype}'")
    return Field(
        name=name,
        type=ftype,
        required=bool(raw.get("required", False)),
        readonly=bool(raw.get("readonly", False)),
        generated=bool(raw.get("generated", False)),
        unique=bool(raw.get("unique", False)),
        default=raw.get("default"),
        min=raw.get("min"),
        max=raw.get("max"),
        min_len=raw.get("min_len"),
        max_len=raw.get("max_len"),
        pattern=raw.get("pattern"),
        values=list(raw["values"]) if raw.get("values") is not None else None,
        ref=raw.get("ref"),
    )


def _parse_endpoint(kind: str, raw: dict) -> Endpoint:
    where = f"endpoints.{kind}"
    pagination = None
    if "pagination" in raw and raw["pagination"]:
        p = raw["pagination"]
        pagination = Pagination(
            limit_param=p.get("limit_param", "limit"),
            offset_param=p.get("offset_param", "offset"),
            default_limit=int(_require(p, "default_limit", f"{where}.pagination")),
            max_limit=int(_require(p, "max_limit", f"{where}.pagination")),
        )
    return Endpoint(
        kind=kind,
        method=_require(raw, "method", where),
        path=_require(raw, "path", where),
        success=int(_require(raw, "success", where)),
        missing=int(raw["missing"]) if raw.get("missing") is not None else None,
        partial=bool(raw.get("partial", False)),
        pagination=pagination,
        filters=list(raw.get("filters", []) or []),
        sort=list(raw.get("sort", []) or []),
    )


def parse_spec(data: dict) -> InstanceSpec:
    """Build an :class:`InstanceSpec` from a parsed YAML mapping."""
    if not isinstance(data, dict):
        raise SpecError("spec root must be a mapping")

    res_raw = _require(data, "resource", "spec")
    fields_raw = _require(res_raw, "fields", "resource")
    if not fields_raw:
        raise SpecError("resource.fields must be non-empty")
    fields = [_parse_field(f, "resource.fields") for f in fields_raw]

    resource = ResourceSpec(
        name=_require(res_raw, "name", "resource"),
        path=_require(res_raw, "path", "resource"),
        fields=fields,
    )

    eps_raw = _require(data, "endpoints", "spec")
    endpoints = EndpointSet(
        **{
            kind: _parse_endpoint(kind, eps_raw[kind])
            for kind in eps_raw
            if kind in EndpointSet.__annotations__
        }
    )

    rules_raw = data.get("rules") or {}
    rules = Rules(
        on_validation_error=int(rules_raw.get("on_validation_error", 422)),
        on_unique_conflict=int(rules_raw.get("on_unique_conflict", 409)),
        timestamps_immutable=bool(rules_raw.get("timestamps_immutable", False)),
    )

    return InstanceSpec(
        id=_require(data, "id", "spec"),
        title=data.get("title", data["id"]),
        tier=_require(data, "tier", "spec"),
        resource=resource,
        endpoints=endpoints,
        rules=rules,
        business_rules=list(data.get("business_rules") or []),
    )


def load_spec(path: str | Path) -> InstanceSpec:
    """Read and parse an instance spec file."""
    p = Path(path)
    if not p.exists():
        raise SpecError(f"spec file not found: {p}")
    try:
        data = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:  # pragma: no cover - defensive
        raise SpecError(f"could not parse YAML in {p}: {e}") from e
    return parse_spec(data)
