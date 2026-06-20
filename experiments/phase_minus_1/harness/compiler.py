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

from harness.payloads import boundary_cases, valid_payload, valid_value
from harness.specschema import Field, InstanceSpec

_MISSING_ID = "00000000-0000-0000-0000-999999999999"

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
def id_field_name(spec: InstanceSpec) -> str:
    for f in spec.resource.fields:
        if f.generated and f.type == "uuid":
            return f.name
    for f in spec.resource.fields:
        if f.generated:
            return f.name
    return "id"


class Api:
    """Black-box HTTP client bound to a spec's resource (pins the conventions)."""

    def __init__(self, client, spec: InstanceSpec):
        self.client = client
        self.spec = spec
        self.base = spec.resource.path
        self.id_field = id_field_name(spec)

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
        payload = valid_payload(spec, nxt())
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
        payload = valid_payload(spec, nxt())
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
        payload = valid_payload(spec, seed)
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
        payload = valid_payload(spec, nxt())
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
        payload = valid_payload(spec, nxt())
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
        p1 = valid_payload(spec, nxt())
        r1 = api.create(p1)
        if r1.status_code != create.success:
            return _fail(f"setup create failed: {r1.status_code}")
        p2 = valid_payload(spec, nxt())
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
        payload = valid_payload(spec, nxt())
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


def _update_cases(spec: InstanceSpec, nxt: SeedFn) -> list[ContractCase]:
    up = spec.endpoints.update
    create = spec.endpoints.create
    cases: list[ContractCase] = []
    targets = [f for f in spec.resource.writable_fields() if not f.unique][:2]

    def make_partial(f: Field):
        def run(api: Api) -> CaseResult:
            payload = valid_payload(spec, nxt())
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
            for other in spec.resource.writable_fields():
                if other.name == f.name:
                    continue
                if ub.get(other.name) != payload[other.name]:
                    return _fail(f"PATCH of {f.name!r} also changed {other.name!r}")
            return _ok()

        return ContractCase(
            f"update:partial:{f.name}", "update", run, field=f.name, expected_status=up.success
        )

    for f in targets:
        cases.append(make_partial(f))

    def run_missing(api: Api) -> CaseResult:
        f = targets[0]
        u = api.update(_MISSING_ID, {f.name: valid_value(f, nxt())})
        if u.status_code != up.missing:
            return _fail(f"PATCH unknown id: expected {up.missing}, got {u.status_code}")
        return _ok()

    cases.append(ContractCase("update:missing", "update", run_missing, expected_status=up.missing))

    def make_readonly(f: Field):
        def run(api: Api) -> CaseResult:
            payload = valid_payload(spec, nxt())
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
        payload = valid_payload(spec, nxt())
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
        payload = valid_payload(spec, nxt())
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
            payload = valid_payload(spec, nxt())
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
                    p = valid_payload(spec, nxt())
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
                p = valid_payload(spec, nxt())
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
