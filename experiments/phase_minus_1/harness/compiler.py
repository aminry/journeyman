"""Compile an instance spec into a black-box contract suite (domain.md §3).

The compiler is the experiment's *oracle*. Each :class:`ContractCase` is a small
black-box HTTP scenario with a ``run`` method that drives a booted service and
returns pass/fail. The mapping spec-element -> case follows domain.md §3 exactly.

Strictness is the whole point (the prompt's "VALIDATE THE ORACLE"): a lenient
suite that accepts an over-length field or an un-capped page silently invalidates
the gate. So every declared constraint, status code, and envelope shape is
asserted. Correctness of these assertions is proven by the oracle integration
test (a correct reference service passes all; a deliberately-broken one fails on
exactly the right cases).

Every value a test sends to the service is drawn from a single per-suite seed
counter (:func:`run_suite` makes a fresh one per run), so unique fields never
collide by accident — a stray collision would surface as a spurious 409 and a
false failure.

Conventions the spec leaves open are pinned here (and surfaced to the effector via
the TaskSpec, never via the tests — held-out integrity):

* the collection endpoint returns a JSON array of entities;
* filtering is ``?<field>=<value>`` (booleans as ``true``/``false``);
* sorting is ``?sort=<field>`` (ascending) and ``?sort=-<field>`` (descending);
* validation errors return ``422`` with body ``{"errors": [{"field", "message"}]}``.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from typing import Any, Callable

from harness.payloads import boundary_cases, valid_payload_for_resource, valid_value
from harness.specschema import (
    CompositeUniqueRule,
    CrossFieldRule,
    Field,
    InstanceSpec,
    RelationshipRule,
    ResourceSpec,
    StateMachineRule,
    business_rules_of,
)

_MISSING_ID = "00000000-0000-0000-0000-999999999999"
_BOGUS_REF = "00000000-0000-0000-0000-deadbeef0000"

# A function that yields a fresh, never-repeated integer seed.
SeedFn = Callable[[], int]


# --------------------------------------------------------------------------- #
# Result + case model
# --------------------------------------------------------------------------- #
@dataclass
class CaseResult:
    passed: bool
    detail: str = ""


def _ok(detail: str = "") -> CaseResult:
    return CaseResult(True, detail)


def _fail(detail: str) -> CaseResult:
    return CaseResult(False, detail)


@dataclass
class ContractCase:
    id: str
    category: str
    run: Callable[["Api"], CaseResult]
    field: str | None = None
    expected_status: int | None = None


@dataclass
class SuiteResult:
    total: int
    passed: int
    results: list[tuple[str, bool, str]]

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    @property
    def failed_ids(self) -> list[str]:
        return [cid for cid, ok, _ in self.results if not ok]


# --------------------------------------------------------------------------- #
# HTTP convention helper
# --------------------------------------------------------------------------- #
def _id_field_of(resource: ResourceSpec) -> str:
    for f in resource.fields:
        if f.generated and f.type == "uuid":
            return f.name
    for f in resource.fields:
        if f.generated:
            return f.name
    return "id"


def id_field_name(spec: InstanceSpec) -> str:
    return _id_field_of(spec.resource)


def _hi_lo(fa: Field, fb: Field) -> tuple[Any, Any]:
    """A (high, low) value pair valid for both fields, for cross-field comparison."""
    if fa.type == "datetime" or fb.type == "datetime":
        return ("2026-09-15T00:00:00Z", "2026-02-01T00:00:00Z")
    lo = max(fa.min if fa.min is not None else 0, fb.min if fb.min is not None else 0)
    caps = [c for c in (fa.max, fb.max) if c is not None]
    hi = min(lo + 1000, min(caps)) if caps else lo + 1000
    if hi <= lo:
        hi = lo + 1
    if fa.type == "number" or fb.type == "number":
        return (float(hi), float(lo))
    return (int(hi), int(lo))


def cross_field_pair(fa: Field, fb: Field, op: str, *, satisfy: bool) -> tuple[Any, Any]:
    """Values (va, vb) such that ``va op vb`` holds (satisfy) or is violated."""
    hi, lo = _hi_lo(fa, fb)
    if op in ("gt", "gte"):
        return (hi, lo) if satisfy else (lo, hi)
    return (lo, hi) if satisfy else (hi, lo)  # lt | lte


class Api:
    """Black-box HTTP client bound to a spec (pins the conventions).

    Knows the spec's business rules so :meth:`payload` produces create payloads that
    satisfy them — start state-machine fields at ``initial`` (server-set), satisfy
    cross-field constraints, and point ``ref`` fields at a real (lazily-created)
    parent — so the standard CRUD cases never trip a business rule by accident.
    """

    def __init__(self, client, spec: InstanceSpec):
        self.client = client
        self.spec = spec
        self.base = spec.resource.path
        self.id_field = id_field_name(spec)
        self._rules = business_rules_of(spec)
        self._sm_fields = {r.field for r in self._rules if isinstance(r, StateMachineRule)}
        self._cf_rules = [r for r in self._rules if isinstance(r, CrossFieldRule)]
        self._resources: dict[str, tuple[ResourceSpec, Any]] = {
            spec.resource.name: (spec.resource, spec.endpoints)
        }
        if spec.related is not None:
            self._resources[spec.related.resource.name] = (
                spec.related.resource,
                spec.related.endpoints,
            )
        self._parent_cache: dict[str, Any] = {}
        self._aux = itertools.count(900001)  # parent-row seeds, disjoint from suite seeds

    # -- primary-resource verbs (back-compat) --
    def create(self, payload: dict):
        return self.client.post(self.base, json=payload)

    def get(self, ident: Any):
        return self.client.get(f"{self.base}/{ident}")

    def list(self, **params):
        return self.client.get(self.base, params=params)

    def update(self, ident: Any, patch: dict):
        return self.client.patch(f"{self.base}/{ident}", json=patch)

    def delete(self, ident: Any):
        return self.client.delete(f"{self.base}/{ident}")

    # -- generic, resource-addressed verbs (relationships, second resource) --
    def resource(self, name: str) -> ResourceSpec:
        return self._resources[name][0]

    def _endpoints(self, name: str):
        return self._resources[name][1]

    def success_of(self, name: str, kind: str) -> int:
        return getattr(self._endpoints(name), kind).success

    def create_in(self, name: str, payload: dict):
        return self.client.post(self.resource(name).path, json=payload)

    def delete_in(self, name: str, ident: Any):
        return self.client.delete(f"{self.resource(name).path}/{ident}")

    def _owner(self, field_name: str) -> str:
        for rname, (res, _) in self._resources.items():
            if any(f.name == field_name for f in res.fields):
                return rname
        return self.spec.resource.name

    def make_payload(self, name: str, seed: int) -> dict:
        """A valid create payload for resource ``name`` honouring its business rules."""
        res = self.resource(name)
        p = valid_payload_for_resource(res, seed)
        for smf in (f for f in self._sm_fields if self._owner(f) == name):
            p.pop(smf, None)  # state-machine fields are server-initialised to `initial`
        for r in self._cf_rules:
            if self._owner(r.fields[0]) == name:
                a, b = r.fields
                va, vb = cross_field_pair(res.field(a), res.field(b), r.op, satisfy=True)
                p[a], p[b] = va, vb
        for f in res.fields:
            if f.type == "ref" and f.name in p and f.ref is not None:
                p[f.name] = self.ensure_parent_id(f.ref)
        return p

    def payload(self, seed: int) -> dict:
        return self.make_payload(self.spec.resource.name, seed)

    def _create_parent(self, name: str, seed: int) -> Any:
        res = self.resource(name)
        payload = self.make_payload(name, seed)
        body = self.create_in(name, payload).json()
        return body[_id_field_of(res)]

    def ensure_parent_id(self, name: str) -> Any:
        if name not in self._parent_cache:
            self._parent_cache[name] = self._create_parent(name, next(self._aux))
        return self._parent_cache[name]

    def make_parent_fresh(self, name: str) -> Any:
        """A brand-new parent id (not cached) — safe to delete in restrict tests."""
        return self._create_parent(name, next(self._aux))


def _names_field(resp, field_name: str) -> bool:
    """A 422 body names ``field_name`` in the spec's pinned envelope.

    Strict by design: the spec pins the shape ``{"errors": [{"field", "message"}]}``
    (domain.md §2). A loose substring match would accept e.g. ``{"detail": "isbn
    ..."}`` and silently let a non-conforming service pass — so we require an
    ``errors`` list with an item whose ``field`` equals ``field_name``.
    """
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        return False
    if isinstance(body, dict) and isinstance(body.get("errors"), list):
        for e in body["errors"]:
            if isinstance(e, dict) and e.get("field") == field_name:
                return True
    return False


def _bogus_for(field: Field) -> Any:
    if field.type in ("uuid", "ref"):
        return "11111111-1111-1111-1111-111111111111"
    if field.type == "datetime":
        return "1999-12-31T23:59:59Z"
    if field.type == "integer":
        return 424242
    if field.type == "number":
        return 4242.42
    if field.type == "boolean":
        return False
    return "client-supplied-should-be-ignored"


def _distinct_pair(field: Field) -> tuple[Any, Any]:
    if field.type == "boolean":
        return True, False
    if field.type == "enum" and field.values and len(field.values) >= 2:
        return field.values[0], field.values[1]
    return valid_value(field, 1), valid_value(field, 2)


def _query_value(field: Field, value: Any) -> Any:
    if field.type == "boolean":
        return "true" if value else "false"
    return value


def _comparable(field: Field, value: Any) -> bool:
    """True if ``value`` is a non-null value of ``field``'s expected Python type.

    Used by the sort assertion so it ranks only correctly-typed values — wrong-typed
    rows left behind by a constraint-skipping service are caught by the validation
    cases, not the sort case (keeps per-dimension attribution clean)."""
    if value is None:
        return False
    if field.type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if field.type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, str)


# --------------------------------------------------------------------------- #
# Case builders (each receives ``nxt`` -> a fresh unique seed)
# --------------------------------------------------------------------------- #
def _create_valid(spec: InstanceSpec, nxt: SeedFn) -> ContractCase:
    create = spec.endpoints.create

    def run(api: Api) -> CaseResult:
        payload = api.payload(nxt())
        r = api.create(payload)
        if r.status_code != create.success:
            return _fail(f"expected {create.success}, got {r.status_code}: {r.text[:200]}")
        body = r.json()
        for k, v in payload.items():
            if body.get(k) != v:
                return _fail(f"response did not echo {k!r} ({body.get(k)!r} != {v!r})")
        for f in spec.resource.fields:
            if f.server_managed and not body.get(f.name):
                return _fail(f"server-managed field {f.name!r} not populated")
        return _ok()

    return ContractCase("create:valid", "create", run, expected_status=create.success)


def _missing_required(spec: InstanceSpec, nxt: SeedFn, f: Field) -> ContractCase:
    def run(api: Api) -> CaseResult:
        payload = api.payload(nxt())
        payload.pop(f.name, None)
        r = api.create(payload)
        if r.status_code != spec.rules.on_validation_error:
            return _fail(
                f"omitting {f.name!r}: expected {spec.rules.on_validation_error}, got {r.status_code}"
            )
        if not _names_field(r, f.name):
            return _fail(f"422 body does not name missing field {f.name!r}")
        return _ok()

    return ContractCase(
        f"create:missing:{f.name}",
        "create",
        run,
        field=f.name,
        expected_status=spec.rules.on_validation_error,
    )


def _validation_case(spec: InstanceSpec, nxt: SeedFn, f: Field, bc) -> ContractCase:
    create = spec.endpoints.create
    suffix = "valid" if bc.valid else "invalid"

    def run(api: Api) -> CaseResult:
        seed = nxt()
        payload = api.payload(seed)
        if bc.valid and f.unique:
            payload[f.name] = valid_value(f, seed)  # keep unique while honouring the constraint
        else:
            payload[f.name] = bc.value
        r = api.create(payload)
        if bc.valid:
            if r.status_code != create.success:
                return _fail(
                    f"{bc.description}: expected {create.success}, got {r.status_code}: {r.text[:160]}"
                )
            return _ok()
        if r.status_code != spec.rules.on_validation_error:
            return _fail(
                f"{bc.description}: expected {spec.rules.on_validation_error}, got {r.status_code}"
            )
        return _ok()

    return ContractCase(
        f"validation:{bc.kind}:{f.name}:{suffix}",
        "validation",
        run,
        field=f.name,
        expected_status=(create.success if bc.valid else spec.rules.on_validation_error),
    )


def _default_case(spec: InstanceSpec, nxt: SeedFn, f: Field) -> ContractCase:
    create = spec.endpoints.create

    def run(api: Api) -> CaseResult:
        payload = api.payload(nxt())
        payload.pop(f.name, None)
        r = api.create(payload)
        if r.status_code != create.success:
            return _fail(f"expected {create.success}, got {r.status_code}")
        body = r.json()
        if body.get(f.name) != f.default:
            return _fail(
                f"default for {f.name!r}: expected {f.default!r}, got {body.get(f.name)!r}"
            )
        return _ok()

    return ContractCase(
        f"default:{f.name}", "default", run, field=f.name, expected_status=create.success
    )


def _server_managed_case(spec: InstanceSpec, nxt: SeedFn, f: Field) -> ContractCase:
    create = spec.endpoints.create

    def run(api: Api) -> CaseResult:
        payload = api.payload(nxt())
        bogus = _bogus_for(f)
        payload[f.name] = bogus
        r = api.create(payload)
        if r.status_code == spec.rules.on_validation_error:
            return _ok()  # rejecting the client-set value is acceptable
        if r.status_code != create.success:
            return _fail(f"expected {create.success} or 422, got {r.status_code}")
        body = r.json()
        if body.get(f.name) == bogus:
            return _fail(f"server-managed {f.name!r} accepted a client-supplied value")
        if not body.get(f.name):
            return _fail(f"server-managed {f.name!r} not populated")
        return _ok()

    return ContractCase(f"server_managed:{f.name}", "server_managed", run, field=f.name)


def _unique_case(spec: InstanceSpec, nxt: SeedFn, f: Field) -> ContractCase:
    create = spec.endpoints.create

    def run(api: Api) -> CaseResult:
        p1 = api.payload(nxt())
        r1 = api.create(p1)
        if r1.status_code != create.success:
            return _fail(f"setup create failed: {r1.status_code}")
        p2 = api.payload(nxt())
        p2[f.name] = p1[f.name]  # duplicate the unique field
        r2 = api.create(p2)
        if r2.status_code != spec.rules.on_unique_conflict:
            return _fail(
                f"duplicate {f.name!r}: expected {spec.rules.on_unique_conflict}, got {r2.status_code}"
            )
        return _ok()

    return ContractCase(
        f"unique:conflict:{f.name}",
        "unique",
        run,
        field=f.name,
        expected_status=spec.rules.on_unique_conflict,
    )


def _get_cases(spec: InstanceSpec, nxt: SeedFn) -> list[ContractCase]:
    get = spec.endpoints.get
    create = spec.endpoints.create

    def run_found(api: Api) -> CaseResult:
        payload = api.payload(nxt())
        r = api.create(payload)
        if r.status_code != create.success:
            return _fail(f"setup create failed: {r.status_code}")
        ident = r.json()[api.id_field]
        g = api.get(ident)
        if g.status_code != get.success:
            return _fail(f"expected {get.success}, got {g.status_code}")
        gb = g.json()
        if gb.get(api.id_field) != ident:
            return _fail("returned entity has different id")
        for k, v in payload.items():
            if gb.get(k) != v:
                return _fail(f"GET did not return same {k!r}")
        return _ok()

    def run_missing(api: Api) -> CaseResult:
        g = api.get(_MISSING_ID)
        if g.status_code != get.missing:
            return _fail(f"expected {get.missing}, got {g.status_code}")
        return _ok()

    return [
        ContractCase("get:found", "get", run_found, expected_status=get.success),
        ContractCase("get:missing", "get", run_missing, expected_status=get.missing),
    ]


def _governed_fields(spec: InstanceSpec) -> set[str]:
    """Fields a business rule governs — excluded from generic partial-update targets,
    since PATCHing them to an arbitrary value would (correctly) trip the rule."""
    governed: set[str] = set()
    for r in business_rules_of(spec):
        if isinstance(r, StateMachineRule):
            governed.add(r.field)
        elif isinstance(r, CrossFieldRule):
            governed.update(r.fields)
        elif isinstance(r, CompositeUniqueRule):
            governed.update(r.fields)
        elif isinstance(r, RelationshipRule):
            governed.add(r.ref_field)
    return governed


def _update_cases(spec: InstanceSpec, nxt: SeedFn) -> list[ContractCase]:
    up = spec.endpoints.update
    create = spec.endpoints.create
    cases: list[ContractCase] = []
    governed = _governed_fields(spec)
    targets = [
        f
        for f in spec.resource.writable_fields()
        if not f.unique and f.type != "ref" and f.name not in governed
    ][:2]

    def make_partial(f: Field):
        def run(api: Api) -> CaseResult:
            payload = api.payload(nxt())
            r = api.create(payload)
            if r.status_code != create.success:
                return _fail(f"setup create failed: {r.status_code}")
            ident = r.json()[api.id_field]
            newval = valid_value(f, nxt())
            if newval == payload[f.name]:
                newval = valid_value(f, nxt())
            u = api.update(ident, {f.name: newval})
            if u.status_code != up.success:
                return _fail(
                    f"PATCH {f.name!r}: expected {up.success}, got {u.status_code}: {u.text[:160]}"
                )
            ub = u.json()
            if ub.get(f.name) != newval:
                return _fail(f"PATCH did not change {f.name!r}")
            for other_name, orig in payload.items():  # only client-set fields
                if other_name == f.name:
                    continue
                if ub.get(other_name) != orig:
                    return _fail(f"PATCH of {f.name!r} also changed {other_name!r}")
            return _ok()

        return ContractCase(
            f"update:partial:{f.name}", "update", run, field=f.name, expected_status=up.success
        )

    for f in targets:
        cases.append(make_partial(f))

    def run_missing(api: Api) -> CaseResult:
        # PATCH on an unknown id is rejected before any field/rule check, so any
        # writable field works as the probe — fall back if every field is governed.
        writable = spec.resource.writable_fields()
        f = targets[0] if targets else (writable[0] if writable else None)
        patch = {f.name: valid_value(f, nxt())} if f is not None else {}
        u = api.update(_MISSING_ID, patch)
        if u.status_code != up.missing:
            return _fail(f"PATCH unknown id: expected {up.missing}, got {u.status_code}")
        return _ok()

    cases.append(ContractCase("update:missing", "update", run_missing, expected_status=up.missing))

    def make_readonly(f: Field):
        def run(api: Api) -> CaseResult:
            payload = api.payload(nxt())
            r = api.create(payload)
            if r.status_code != create.success:
                return _fail(f"setup create failed: {r.status_code}")
            body = r.json()
            ident = body[api.id_field]
            orig = body.get(f.name)
            bogus = _bogus_for(f)
            u = api.update(ident, {f.name: bogus})
            if u.status_code == spec.rules.on_validation_error:
                return _ok()
            if u.status_code != up.success:
                return _fail(
                    f"PATCH readonly {f.name!r}: expected {up.success} or 422, got {u.status_code}"
                )
            if u.json().get(f.name) == bogus:
                return _fail(f"readonly {f.name!r} was changed via PATCH")
            if u.json().get(f.name) != orig:
                return _fail(f"readonly {f.name!r} mutated unexpectedly")
            return _ok()

        return ContractCase(f"update:readonly:{f.name}", "update", run, field=f.name)

    for f in (f for f in spec.resource.fields if f.server_managed):
        cases.append(make_readonly(f))

    return cases


def _delete_cases(spec: InstanceSpec, nxt: SeedFn) -> list[ContractCase]:
    delete = spec.endpoints.delete
    get = spec.endpoints.get
    create = spec.endpoints.create

    def run_ok(api: Api) -> CaseResult:
        payload = api.payload(nxt())
        r = api.create(payload)
        if r.status_code != create.success:
            return _fail(f"setup create failed: {r.status_code}")
        ident = r.json()[api.id_field]
        d = api.delete(ident)
        if d.status_code != delete.success:
            return _fail(f"DELETE: expected {delete.success}, got {d.status_code}")
        g = api.get(ident)
        if g.status_code != get.missing:
            return _fail(f"after DELETE, GET expected {get.missing}, got {g.status_code}")
        return _ok()

    def run_missing(api: Api) -> CaseResult:
        d = api.delete(_MISSING_ID)
        if d.status_code != delete.missing:
            return _fail(f"DELETE unknown id: expected {delete.missing}, got {d.status_code}")
        return _ok()

    return [
        ContractCase("delete:ok", "delete", run_ok, expected_status=delete.success),
        ContractCase("delete:missing", "delete", run_missing, expected_status=delete.missing),
    ]


def _seed_rows(api: Api, spec: InstanceSpec, nxt: SeedFn, n: int, **overrides) -> None:
    for _ in range(n):
        payload = api.payload(nxt())
        payload.update(overrides)
        api.create(payload)


def _list_cases(spec: InstanceSpec, nxt: SeedFn) -> list[ContractCase]:
    lst = spec.endpoints.list
    pag = lst.pagination
    cases: list[ContractCase] = []

    if pag is None:
        # Easy-tier list has no pagination/filter/sort. Still verify the endpoint
        # exists and returns created rows as a JSON array (otherwise the list
        # endpoint would be wholly untested at the easy tier — a held-out gap).
        def run_basic(api: Api) -> CaseResult:
            payload = api.payload(nxt())
            r = api.create(payload)
            if r.status_code != spec.endpoints.create.success:
                return _fail(f"setup create failed: {r.status_code}")
            ident = r.json()[api.id_field]
            lr = api.list()
            if lr.status_code != lst.success:
                return _fail(f"list: expected {lst.success}, got {lr.status_code}")
            items = lr.json()
            if not isinstance(items, list):
                return _fail("list did not return a JSON array")
            if not any(it.get(api.id_field) == ident for it in items):
                return _fail("list did not include the just-created entity")
            return _ok()

        cases.append(ContractCase("list:basic", "list", run_basic, expected_status=lst.success))

    if pag is not None:
        lp, op = pag.limit_param, pag.offset_param
        dl, ml = pag.default_limit, pag.max_limit

        def run_default(api: Api) -> CaseResult:
            _seed_rows(api, spec, nxt, dl + 5)
            r = api.list()
            if r.status_code != lst.success:
                return _fail(f"list: expected {lst.success}, got {r.status_code}")
            items = r.json()
            if not isinstance(items, list):
                return _fail("list did not return a JSON array")
            if len(items) != dl:
                return _fail(f"default_limit: expected {dl} items, got {len(items)}")
            return _ok()

        def run_limit(api: Api) -> CaseResult:
            _seed_rows(api, spec, nxt, 5)
            items = api.list(**{lp: 3}).json()
            if len(items) != 3:
                return _fail(f"limit=3: expected 3 items, got {len(items)}")
            return _ok()

        def run_offset(api: Api) -> CaseResult:
            _seed_rows(api, spec, nxt, 6)
            p1 = api.list(**{lp: 2, op: 0}).json()
            p2 = api.list(**{lp: 2, op: 2}).json()
            if len(p1) != 2 or len(p2) != 2:
                return _fail(f"offset paging returned {len(p1)}/{len(p2)} items")
            idf = api.id_field
            if {x[idf] for x in p1} & {x[idf] for x in p2}:
                return _fail("offset pages overlap (unstable ordering or offset ignored)")
            return _ok()

        def run_max(api: Api) -> CaseResult:
            _seed_rows(api, spec, nxt, ml + 5)
            items = api.list(**{lp: ml + 50}).json()
            if len(items) > ml:
                return _fail(
                    f"max_limit not enforced: requested {ml + 50}, got {len(items)} > {ml}"
                )
            return _ok()

        cases += [
            ContractCase("list:default_limit", "list", run_default, expected_status=lst.success),
            ContractCase("list:limit", "list", run_limit, expected_status=lst.success),
            ContractCase("list:offset", "list", run_offset, expected_status=lst.success),
            ContractCase("list:max_limit", "list", run_max, expected_status=lst.success),
        ]

    for fname in lst.filters:
        f = spec.resource.field(fname)

        def make_filter(f: Field):
            def run(api: Api) -> CaseResult:
                target, other = _distinct_pair(f)
                _seed_rows(api, spec, nxt, 1, **{f.name: target})
                _seed_rows(api, spec, nxt, 1, **{f.name: other})
                items = api.list(**{f.name: _query_value(f, target)}).json()
                if len(items) < 1:
                    return _fail(f"filter {f.name}={target!r} returned nothing")
                for it in items:
                    if it.get(f.name) != target:
                        return _fail(
                            f"filter {f.name}={target!r} returned non-matching {it.get(f.name)!r}"
                        )
                return _ok()

            return ContractCase(
                f"list:filter:{f.name}", "list", run, field=f.name, expected_status=lst.success
            )

        cases.append(make_filter(f))

    for fname in lst.sort:
        f = spec.resource.field(fname)

        def make_sort(f: Field, ascending: bool):
            direction = "asc" if ascending else "desc"

            def run(api: Api) -> CaseResult:
                # insert deliberately out of sorted order
                for v in (valid_value(f, 9), valid_value(f, 0), valid_value(f, 4)):
                    p = api.payload(nxt())
                    p[f.name] = v
                    api.create(p)
                sort_param = f.name if ascending else f"-{f.name}"
                items = api.list(sort=sort_param).json()
                # Sort tests assert *ordering* over correctly-typed values only. Field
                # completeness is covered by create:valid/get:found echo checks, and
                # type validity by the validation cases — so nulls and wrong-typed
                # values are skipped here. This keeps per-dimension attribution clean
                # (a missing-field or bad-type bug shouldn't also flag the sort case).
                seq = [v for v in (it.get(f.name) for it in items) if _comparable(f, v)]
                ok = all(
                    (seq[i] <= seq[i + 1]) if ascending else (seq[i] >= seq[i + 1])
                    for i in range(len(seq) - 1)
                )
                if not ok:
                    return _fail(f"sort {sort_param} not monotonic ({direction}): {seq[:6]}")
                return _ok()

            return ContractCase(
                f"list:sort:{f.name}:{direction}",
                "list",
                run,
                field=f.name,
                expected_status=lst.success,
            )

        cases.append(make_sort(f, True))
        cases.append(make_sort(f, False))

    # Multi-filter (hard tier): a conjunction of ≥2 filters must AND together.
    if len(lst.filters) >= 2:
        f1 = spec.resource.field(lst.filters[0])
        f2 = spec.resource.field(lst.filters[1])

        def run_multi_filter(api: Api) -> CaseResult:
            a1, _ = _distinct_pair(f1)
            b1, b2 = _distinct_pair(f2)
            _seed_rows(api, spec, nxt, 1, **{f1.name: a1, f2.name: b1})  # matches both
            _seed_rows(api, spec, nxt, 1, **{f1.name: a1, f2.name: b2})  # matches only f1
            params = {f1.name: _query_value(f1, a1), f2.name: _query_value(f2, b1)}
            r = api.list(**params)
            items = r.json()
            if not isinstance(items, list):
                return _fail("multi-filter list did not return an array")
            if not items:
                return _fail(f"multi-filter {params} returned nothing (expected ≥1 match)")
            for it in items:
                if it.get(f1.name) != a1 or it.get(f2.name) != b1:
                    return _fail(
                        f"multi-filter returned a row not matching BOTH "
                        f"({f1.name}={it.get(f1.name)!r}, {f2.name}={it.get(f2.name)!r})"
                    )
            return _ok()

        cases.append(
            ContractCase("list:filter:multi", "list", run_multi_filter, expected_status=lst.success)
        )

    # Multi-sort (hard tier): a composite ``?sort=a,-b`` orders by a asc, then b desc.
    if len(lst.sort) >= 2:
        s1 = spec.resource.field(lst.sort[0])
        s2 = spec.resource.field(lst.sort[1])

        def run_multi_sort(api: Api) -> CaseResult:
            # Two rows tie on s1 (same seed) with ASCENDING s2 in insertion order, so a
            # secondary-sort-ignoring service (stable sort on s1 only) leaves them in the
            # wrong order for "s2 desc"; plus rows with other s1 values.
            for v1seed, v2seed in ((5, 1), (5, 9), (2, 3), (8, 4)):
                p = api.payload(nxt())
                p[s1.name] = valid_value(s1, v1seed)
                p[s2.name] = valid_value(s2, v2seed)
                api.create(p)
            params = {"sort": f"{s1.name},-{s2.name}"}
            if pag is not None:
                params[pag.limit_param] = pag.max_limit  # keep seeded rows on the page
            items = api.list(**params).json()
            seq = [
                (it.get(s1.name), it.get(s2.name))
                for it in items
                if _comparable(s1, it.get(s1.name)) and _comparable(s2, it.get(s2.name))
            ]
            for (a, b), (c, d) in zip(seq, seq[1:]):
                if a > c:
                    return _fail(f"multi-sort primary {s1.name} not ascending: {a!r} > {c!r}")
                if a == c and b < d:
                    return _fail(
                        f"multi-sort tie on {s1.name}={a!r}: {s2.name} not descending "
                        f"({b!r} before {d!r})"
                    )
            return _ok()

        cases.append(
            ContractCase("list:sort:multi", "list", run_multi_sort, expected_status=lst.success)
        )

    return cases


# --------------------------------------------------------------------------- #
# Business-rule cases (hard tier — domain.md §3)
# --------------------------------------------------------------------------- #
def _state_machine_cases(
    spec: InstanceSpec, nxt: SeedFn, rule: StateMachineRule
) -> list[ContractCase]:
    sfield = rule.field
    create = spec.endpoints.create
    up = spec.endpoints.update

    def _new(api: Api) -> Any:
        r = api.create(api.payload(nxt()))
        return r.json()[api.id_field] if r.status_code == create.success else None

    def _walk_to(api: Api, ident: Any, stop_locked: bool) -> str:
        current = rule.initial
        seen: set[str] = set()
        while rule.transitions.get(current) and current not in seen:
            if stop_locked and current in rule.locked_after:
                break
            seen.add(current)
            nxt_state = rule.transitions[current][0]
            api.update(ident, {sfield: nxt_state})
            current = nxt_state
        return current

    def run_create_initial(api: Api) -> CaseResult:
        r = api.create(api.payload(nxt()))
        if r.status_code != create.success:
            return _fail(f"setup create failed: {r.status_code}")
        if r.json().get(sfield) != rule.initial:
            return _fail(f"create did not start at {rule.initial!r}: {r.json().get(sfield)!r}")
        return _ok()

    def run_legal_path(api: Api) -> CaseResult:
        ident = _new(api)
        if ident is None:
            return _fail("setup create failed")
        current = rule.initial
        seen: set[str] = set()
        while (
            rule.transitions.get(current)
            and current not in seen
            and current not in rule.locked_after
        ):
            seen.add(current)
            target = rule.transitions[current][0]
            u = api.update(ident, {sfield: target})
            if u.status_code != up.success:
                return _fail(
                    f"legal {current}->{target}: expected {up.success}, got {u.status_code}"
                )
            if u.json().get(sfield) != target:
                return _fail(f"transition to {target!r} did not stick")
            current = target
        return _ok()

    def run_illegal(api: Api) -> CaseResult:
        ident = _new(api)
        if ident is None:
            return _fail("setup create failed")
        illegal = [
            s
            for s in rule.states
            if s != rule.initial and s not in rule.transitions.get(rule.initial, [])
        ]
        if not illegal:
            return _ok()
        u = api.update(ident, {sfield: illegal[0]})
        if u.status_code != rule.on_illegal:
            return _fail(
                f"illegal {rule.initial}->{illegal[0]}: expected {rule.on_illegal}, got {u.status_code}"
            )
        return _ok()

    def run_terminal(api: Api) -> CaseResult:
        ident = _new(api)
        if ident is None:
            return _fail("setup create failed")
        current = _walk_to(api, ident, stop_locked=False)
        target = next((s for s in rule.states if s != current), None)
        if target is None:
            return _ok()
        u = api.update(ident, {sfield: target})
        if u.status_code != rule.on_illegal:
            return _fail(
                f"terminal {current!r} must reject ->{target!r}: expected {rule.on_illegal}, got {u.status_code}"
            )
        return _ok()

    cases = [
        ContractCase(f"state_machine:create_initial:{sfield}", "state_machine", run_create_initial),
        ContractCase(f"state_machine:legal_path:{sfield}", "state_machine", run_legal_path),
        ContractCase(
            f"state_machine:illegal_transition:{sfield}",
            "state_machine",
            run_illegal,
            expected_status=rule.on_illegal,
        ),
        ContractCase(
            f"state_machine:terminal_rejects:{sfield}",
            "state_machine",
            run_terminal,
            expected_status=rule.on_illegal,
        ),
    ]

    if rule.locked_after:
        other = next(
            (f for f in spec.resource.writable_fields() if f.name != sfield and not f.unique),
            None,
        )

        def run_immutable(api: Api) -> CaseResult:
            ident = _new(api)
            if ident is None:
                return _fail("setup create failed")
            current = _walk_to(api, ident, stop_locked=True)
            if current not in rule.locked_after:
                return _ok()  # could not reach a locked state (degenerate)
            if other is None:
                return _ok()
            u = api.update(ident, {other.name: valid_value(other, nxt())})
            if u.status_code != rule.on_illegal:
                return _fail(
                    f"locked {current!r} must reject editing {other.name!r}: "
                    f"expected {rule.on_illegal}, got {u.status_code}"
                )
            return _ok()

        cases.append(
            ContractCase(
                f"state_machine:immutable:{sfield}",
                "state_machine",
                run_immutable,
                expected_status=rule.on_illegal,
            )
        )
    return cases


def _cross_field_cases(spec: InstanceSpec, nxt: SeedFn, rule: CrossFieldRule) -> list[ContractCase]:
    a, b = rule.fields
    fa, fb = spec.resource.field(a), spec.resource.field(b)
    create = spec.endpoints.create

    def run_violation(api: Api) -> CaseResult:
        p = api.payload(nxt())
        p[a], p[b] = cross_field_pair(fa, fb, rule.op, satisfy=False)
        r = api.create(p)
        if r.status_code != rule.on_violation:
            return _fail(
                f"cross-field {a} {rule.op} {b} violation: expected {rule.on_violation}, "
                f"got {r.status_code}: {r.text[:160]}"
            )
        return _ok()

    def run_valid(api: Api) -> CaseResult:
        p = api.payload(nxt())
        p[a], p[b] = cross_field_pair(fa, fb, rule.op, satisfy=True)
        r = api.create(p)
        if r.status_code != create.success:
            return _fail(
                f"cross-field {a} {rule.op} {b} satisfied: expected {create.success}, "
                f"got {r.status_code}: {r.text[:160]}"
            )
        return _ok()

    return [
        ContractCase(
            f"cross_field:violation:{a}",
            "cross_field",
            run_violation,
            field=a,
            expected_status=rule.on_violation,
        ),
        ContractCase(
            f"cross_field:valid:{a}",
            "cross_field",
            run_valid,
            field=a,
            expected_status=create.success,
        ),
    ]


def _composite_unique_cases(
    spec: InstanceSpec, nxt: SeedFn, rule: CompositeUniqueRule
) -> list[ContractCase]:
    flds = list(rule.fields)
    key = "-".join(flds)
    owner = spec.resource.name
    if spec.related is not None and any(f.name == flds[0] for f in spec.related.resource.fields):
        owner = spec.related.resource.name
    success = spec.endpoints.create.success if owner == spec.resource.name else None

    def _ok_status(api: Api) -> int:
        return success if success is not None else api.success_of(owner, "create")

    def run_conflict(api: Api) -> CaseResult:
        p1 = api.make_payload(owner, nxt())
        r1 = api.create_in(owner, p1)
        if r1.status_code != _ok_status(api):
            return _fail(f"setup create failed: {r1.status_code}: {r1.text[:160]}")
        p2 = api.make_payload(owner, nxt())
        for f in flds:
            p2[f] = p1[f]  # duplicate the whole composite key
        r2 = api.create_in(owner, p2)
        if r2.status_code != rule.on_conflict:
            return _fail(
                f"duplicate composite {flds}: expected {rule.on_conflict}, got {r2.status_code}"
            )
        return _ok()

    def run_partial_overlap(api: Api) -> CaseResult:
        p1 = api.make_payload(owner, nxt())
        r1 = api.create_in(owner, p1)
        if r1.status_code != _ok_status(api):
            return _fail(f"setup create failed: {r1.status_code}")
        p2 = api.make_payload(owner, nxt())
        p2[flds[0]] = p1[flds[0]]  # share only the first component -> still distinct key
        r2 = api.create_in(owner, p2)
        if r2.status_code != _ok_status(api):
            return _fail(
                f"partial composite overlap must be allowed: got {r2.status_code}: {r2.text[:160]}"
            )
        return _ok()

    return [
        ContractCase(
            f"composite_unique:conflict:{key}",
            "composite_unique",
            run_conflict,
            expected_status=rule.on_conflict,
        ),
        ContractCase(
            f"composite_unique:partial_overlap:{key}", "composite_unique", run_partial_overlap
        ),
    ]


def _relationship_cases(
    spec: InstanceSpec, nxt: SeedFn, rule: RelationshipRule
) -> list[ContractCase]:
    child, parent, rf = rule.child, rule.parent, rule.ref_field
    child_success = (
        spec.endpoints.create.success
        if child == spec.resource.name
        else spec.related.endpoints.create.success
    )

    def run_missing_parent(api: Api) -> CaseResult:
        p = api.make_payload(child, nxt())
        p[rf] = _BOGUS_REF  # reference a parent that does not exist
        r = api.create_in(child, p)
        if r.status_code != rule.on_missing_parent:
            return _fail(
                f"child with missing parent: expected {rule.on_missing_parent}, got {r.status_code}"
            )
        return _ok()

    def run_valid_parent(api: Api) -> CaseResult:
        p = api.make_payload(child, nxt())  # make_payload injects a real parent id
        r = api.create_in(child, p)
        if r.status_code != child_success:
            return _fail(
                f"child with valid parent: expected {child_success}, got {r.status_code}: {r.text[:160]}"
            )
        return _ok()

    cases = [
        ContractCase(
            f"relationship:missing_parent:{rf}",
            "relationship",
            run_missing_parent,
            field=rf,
            expected_status=rule.on_missing_parent,
        ),
        ContractCase(
            f"relationship:valid_parent:{rf}",
            "relationship",
            run_valid_parent,
            field=rf,
            expected_status=child_success,
        ),
    ]

    if rule.on_parent_delete == "restrict":
        # Only meaningful if the parent exposes delete.
        parent_eps = spec.endpoints if parent == spec.resource.name else spec.related.endpoints
        if parent_eps.delete is not None:
            conflict = spec.rules.on_unique_conflict

            def run_restrict_delete(api: Api) -> CaseResult:
                pid = api.make_parent_fresh(parent)
                child_payload = api.make_payload(child, nxt())
                child_payload[rf] = pid
                cr = api.create_in(child, child_payload)
                if cr.status_code != child_success:
                    return _fail(f"setup child create failed: {cr.status_code}: {cr.text[:160]}")
                d = api.delete_in(parent, pid)
                if d.status_code != conflict:
                    return _fail(
                        f"deleting a parent with children must be {conflict} (restrict), "
                        f"got {d.status_code}"
                    )
                return _ok()

            cases.append(
                ContractCase(
                    f"relationship:restrict_delete:{parent}",
                    "relationship",
                    run_restrict_delete,
                    expected_status=conflict,
                )
            )
    return cases


def _business_rule_cases(spec: InstanceSpec, nxt: SeedFn) -> list[ContractCase]:
    cases: list[ContractCase] = []
    for rule in business_rules_of(spec):
        if isinstance(rule, StateMachineRule):
            cases += _state_machine_cases(spec, nxt, rule)
        elif isinstance(rule, CrossFieldRule):
            cases += _cross_field_cases(spec, nxt, rule)
        elif isinstance(rule, CompositeUniqueRule):
            cases += _composite_unique_cases(spec, nxt, rule)
        elif isinstance(rule, RelationshipRule):
            cases += _relationship_cases(spec, nxt, rule)
    return cases


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def compile_contract_suite(spec: InstanceSpec) -> list[ContractCase]:
    """Build the full ordered list of contract cases for ``spec``.

    A fresh seed counter is created per call so every value sent during a run is
    unique (no accidental unique-field collisions).
    """
    counter = itertools.count(1)

    def nxt() -> int:
        return next(counter)

    cases: list[ContractCase] = []
    eps = spec.endpoints
    if eps.create:
        cases.append(_create_valid(spec, nxt))
        for f in spec.resource.required_writable_fields():
            cases.append(_missing_required(spec, nxt, f))
        for f in spec.resource.writable_fields():
            for bc in boundary_cases(f):
                cases.append(_validation_case(spec, nxt, f, bc))
        for f in spec.resource.writable_fields():
            if f.has_default and not f.required:
                cases.append(_default_case(spec, nxt, f))
        for f in spec.resource.fields:
            if f.server_managed:
                cases.append(_server_managed_case(spec, nxt, f))
        for f in spec.resource.unique_fields():
            cases.append(_unique_case(spec, nxt, f))
    if eps.get:
        cases += _get_cases(spec, nxt)
    if eps.update:
        cases += _update_cases(spec, nxt)
    if eps.delete:
        cases += _delete_cases(spec, nxt)
    if eps.list:
        cases += _list_cases(spec, nxt)
    cases += _business_rule_cases(spec, nxt)

    return cases


def run_suite(spec: InstanceSpec, client) -> SuiteResult:
    """Run every contract case against a service reachable through ``client``."""
    api = Api(client, spec)
    cases = compile_contract_suite(spec)
    results: list[tuple[str, bool, str]] = []
    passed = 0
    for case in cases:
        try:
            res = case.run(api)
        except Exception as e:  # a thrown case is a failed case, never a crashed run
            res = _fail(f"exception: {type(e).__name__}: {e}")
        results.append((case.id, res.passed, res.detail))
        if res.passed:
            passed += 1
    return SuiteResult(total=len(cases), passed=passed, results=results)
