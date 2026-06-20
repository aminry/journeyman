"""Spec-driven FastAPI + SQLite reference CRUD service (standalone).

This single module has two jobs:

1. **Oracle validation** — ``build_app(spec, bugs=...)`` builds a service whose
   behaviour is correct (``bugs=frozenset()``) or carries specific, surgical bugs
   so the harness can prove its contract suite catches exactly those bugs.
2. **Fake effector body** — the fake effector copies this file verbatim into a
   scaffolded repo as the "implementation" the spec asked for, so the end-to-end
   pipeline (scaffold -> build -> boot -> contract suite -> DoD -> teardown) runs
   with zero model spend.

It imports ONLY stdlib + FastAPI — never ``harness`` — so the copied file is
self-contained inside the effector's repo (held-out integrity, domain.md §1).

It serves the primary resource and, for relationship rules, an optional second
``related`` resource over shared storage (a single table keyed by resource name).

Pinned conventions (must match harness/compiler.py):
* collection GET returns a JSON array;
* filtering ``?<field>=<value>`` (booleans ``true``/``false``); multiple filters AND;
* sorting ``?sort=<field>`` asc, ``?sort=-<field>`` desc; composite ``?sort=a,-b``;
* validation / cross-field errors -> 422 ``{"errors": [{"field", "message"}]}``;
* unique / composite-unique conflict -> 409; unknown id -> 404;
* state-machine illegal transition -> on_illegal (409); missing parent -> on_missing_parent.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

# Recognised bug flags (used only by the oracle test to prove the suite is strict).
BUG_SKIP_REQUIRED = "skip_required_validation"  # accept missing required fields (not 422)
BUG_IGNORE_MAX_LIMIT = "ignore_max_limit"  # do not cap page size at max_limit
BUG_SKIP_CONSTRAINTS = "skip_constraint_validation"  # ignore min/max/len/pattern/enum
BUG_ACCEPT_CLIENT_FIELDS = "accept_client_server_fields"  # keep client-set id/created_at
BUG_IGNORE_FILTER = "ignore_filter"  # list ignores ?<field>= filters
BUG_NO_404 = "no_404_on_missing"  # unknown id returns success instead of 404
BUG_SKIP_UNIQUE = "skip_unique_check"  # do not enforce unique fields
BUG_IGNORE_DEFAULT = "ignore_default"  # do not apply field defaults
BUG_WRONG_ENVELOPE = "wrong_error_envelope"  # 422 body not {"errors":[{field,message}]}
# List-dimension bugs (T-1.2 (b)).
BUG_LIST_NOT_ARRAY = "list_not_array"  # wrap the collection in an object, not a bare array
BUG_IGNORE_SECONDARY_FILTER = "ignore_secondary_filter"  # apply only the first filter present
BUG_IGNORE_SECONDARY_SORT = "ignore_secondary_sort"  # apply only the first sort key (no tie-break)
# Business-rule bugs (T-1.2 (b), hard tier).
BUG_ALLOW_ILLEGAL_TRANSITION = "allow_illegal_transition"  # state machine accepts any transition
BUG_SKIP_CROSS_FIELD = "skip_cross_field"  # accept cross-field-violating combinations
BUG_SKIP_PARENT_CHECK = (
    "skip_parent_check"  # child may ref a missing parent; parent delete unguarded
)
BUG_SKIP_COMPOSITE_UNIQUE = "skip_composite_unique"  # accept a duplicate composite key
BUG_WRONG_COMPUTED = "wrong_computed"  # server-computed field returns a wrong/stale value


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sort_key(v: Any):
    """A total order that never raises on mixed/None values.

    Groups by type rank, then by a within-rank-comparable value — so a list whose
    rows have inconsistent types (e.g. left by a constraint-skipping service) sorts
    deterministically instead of crashing the endpoint with a 500.
    """
    if v is None:
        return (2, "")
    if isinstance(v, bool):
        return (1, str(v))
    if isinstance(v, (int, float)):
        return (0, v)
    return (1, str(v))


def _coerce(field: dict, raw: Any) -> Any:
    """Coerce a query-string value to the field's type for filtering.

    Defensive: a malformed query value falls back to the raw string rather than
    raising (which would surface as a 500 instead of a no-match).
    """
    t = field.get("type")
    try:
        if t == "boolean":
            return str(raw).lower() == "true"
        if t == "integer":
            return int(raw)
        if t == "number":
            return float(raw)
    except (ValueError, TypeError):
        return raw
    return raw


def _compare(op: str, a: Any, b: Any) -> bool:
    """Evaluate a cross-field comparison ``a op b`` (gt|gte|lt|lte)."""
    try:
        if op == "gt":
            return a > b
        if op == "gte":
            return a >= b
        if op == "lt":
            return a < b
        if op == "lte":
            return a <= b
    except TypeError:
        return True  # incomparable types are caught by per-field type validation, not here
    return True


def _resource_cfg(res: dict, endpoints: dict) -> dict:
    fields = res["fields"]
    id_field = next(
        (f["name"] for f in fields if f.get("generated") and f.get("type") == "uuid"),
        next((f["name"] for f in fields if f.get("generated")), "id"),
    )
    return {
        "name": res["name"],
        "path": res["path"],
        "fields": fields,
        "endpoints": endpoints,
        "id_field": id_field,
        "server_managed": {f["name"] for f in fields if f.get("generated") or f.get("readonly")},
        "unique_fields": [f["name"] for f in fields if f.get("unique")],
        "writable": [f for f in fields if not (f.get("generated") or f.get("readonly"))],
    }


def build_app(spec: dict, bugs: frozenset[str] = frozenset(), db_path: str = ":memory:") -> FastAPI:
    rules = spec.get("rules", {}) or {}
    err_status = int(rules.get("on_validation_error", 422))
    conflict_status = int(rules.get("on_unique_conflict", 409))
    business_rules = spec.get("business_rules", []) or []

    primary = _resource_cfg(spec["resource"], spec["endpoints"])
    resources: dict[str, dict] = {primary["name"]: primary}
    if spec.get("related"):
        rel = spec["related"]
        resources[rel["name"]] = _resource_cfg(rel, rel["endpoints"])
    primary_name = primary["name"]

    sm_rules = [r for r in business_rules if r.get("kind") == "state_machine"]
    cf_rules = [r for r in business_rules if r.get("kind") == "cross_field"]
    cu_rules = [r for r in business_rules if r.get("kind") == "composite_unique"]
    rel_rules = [r for r in business_rules if r.get("kind") == "relationship"]
    computed_rules = [r for r in business_rules if r.get("kind") == "computed_field"]

    def _owner(fname: str) -> str:
        """Which resource owns ``fname`` (field-based rules apply to that resource)."""
        for rn, c in resources.items():
            if any(f["name"] == fname for f in c["fields"]):
                return rn
        return primary_name

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rows "
        "(seq INTEGER PRIMARY KEY AUTOINCREMENT, resource TEXT, id TEXT, data TEXT)"
    )
    conn.commit()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        conn.close()

    app = FastAPI(lifespan=lifespan)

    # ---- storage helpers (keyed by resource) ----------------------------- #
    def _all_rows(rname: str) -> list[dict]:
        cur = conn.execute("SELECT data FROM rows WHERE resource = ? ORDER BY seq ASC", (rname,))
        return [json.loads(r[0]) for r in cur.fetchall()]

    def _get_row(rname: str, ident: str) -> dict | None:
        cur = conn.execute("SELECT data FROM rows WHERE resource = ? AND id = ?", (rname, ident))
        row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def _insert(rname: str, entity: dict, id_field: str) -> None:
        conn.execute(
            "INSERT INTO rows (resource, id, data) VALUES (?, ?, ?)",
            (rname, entity[id_field], json.dumps(entity)),
        )
        conn.commit()

    def _save(rname: str, ident: str, entity: dict) -> None:
        conn.execute(
            "UPDATE rows SET data = ? WHERE resource = ? AND id = ?",
            (json.dumps(entity), rname, ident),
        )
        conn.commit()

    def _remove(rname: str, ident: str) -> None:
        conn.execute("DELETE FROM rows WHERE resource = ? AND id = ?", (rname, ident))
        conn.commit()

    def _err(errors: list[dict]) -> JSONResponse:
        if BUG_WRONG_ENVELOPE in bugs:
            detail = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
            return JSONResponse(status_code=err_status, content={"detail": detail})
        return JSONResponse(status_code=err_status, content={"errors": errors})

    def _conflict(field_name: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=conflict_status,
            content={"errors": [{"field": field_name, "message": message}]},
        )

    # ---- business-rule checks (operate across resources) ------------------ #
    def _cross_field_errors(rname: str, entity: dict) -> list[dict]:
        if BUG_SKIP_CROSS_FIELD in bugs:
            return []
        errs: list[dict] = []
        for r in cf_rules:
            a, b = r["fields"]
            if _owner(a) != rname:
                continue
            if entity.get(a) is not None and entity.get(b) is not None:
                if not _compare(r["op"], entity[a], entity[b]):
                    errs.append(
                        {"field": a, "message": r.get("message") or f"{a} must be {r['op']} {b}"}
                    )
        return errs

    def _composite_conflict(rname: str, entity: dict, exclude_id: str | None) -> dict | None:
        if BUG_SKIP_COMPOSITE_UNIQUE in bugs:
            return None
        id_field = resources[rname]["id_field"]
        for r in cu_rules:
            flds = r["fields"]
            if _owner(flds[0]) != rname:
                continue
            if any(entity.get(f) is None for f in flds):
                continue
            key = tuple(entity[f] for f in flds)
            for row in _all_rows(rname):
                if exclude_id is not None and row.get(id_field) == exclude_id:
                    continue
                if tuple(row.get(f) for f in flds) == key:
                    return r
        return None

    def _missing_parent_status(rname: str, entity: dict) -> int | None:
        if BUG_SKIP_PARENT_CHECK in bugs:
            return None
        for r in rel_rules:
            if r["child"] != rname:
                continue
            rf = r["ref_field"]
            if entity.get(rf) is not None and _get_row(r["parent"], entity[rf]) is None:
                return int(r.get("on_missing_parent", err_status))
        return None

    def _delete_blocked(rname: str, ident: str) -> bool:
        """Restrict: refuse to delete a parent that still has children."""
        if BUG_SKIP_PARENT_CHECK in bugs:
            return False
        for r in rel_rules:
            if r["parent"] != rname or r.get("on_parent_delete", "restrict") != "restrict":
                continue
            if any(row.get(r["ref_field"]) == ident for row in _all_rows(r["child"])):
                return True
        return False

    def _cascade_children(rname: str, ident: str) -> None:
        for r in rel_rules:
            if r["parent"] != rname or r.get("on_parent_delete") != "cascade":
                continue
            child = resources.get(r["child"])
            if not child:
                continue
            for row in _all_rows(r["child"]):
                if row.get(r["ref_field"]) == ident:
                    _remove(r["child"], row[child["id_field"]])

    def _child_ref_to(parent_name: str, child_name: str) -> str | None:
        for f in resources[child_name]["fields"]:
            if f.get("type") == "ref" and f.get("ref") == parent_name:
                return f["name"]
        return None

    def _apply_computed(rname: str, entity: dict) -> dict:
        """Derive read-only computed fields live (never stored) so they are never stale."""
        out = dict(entity)
        for r in computed_rules:
            if _owner(r["field"]) != rname:
                continue
            if r["compute"] == "subtract":
                a, b = r["operands"]
                value = (out.get(a) or 0) - (out.get(b) or 0)
            elif r["compute"] == "sum_children":
                child, child_fields = r["child"], r["child_fields"]
                ref_field = _child_ref_to(rname, child)
                ident = out.get(resources[rname]["id_field"])
                value = 0
                for row in _all_rows(child):
                    if ref_field is not None and row.get(ref_field) == ident:
                        prod = 1
                        for cf in child_fields:
                            prod *= row.get(cf) or 0
                        value += prod
            else:
                continue
            if BUG_WRONG_COMPUTED in bugs:
                value += 1  # broken variant: a wrong/stale value
            out[r["field"]] = value
        return out

    def _sm_initial(rname: str, entity: dict) -> dict:
        for r in sm_rules:
            if _owner(r["field"]) == rname:
                entity[r["field"]] = r["initial"]  # creates always start at the initial state
        return entity

    # ---- per-resource validation/populate -------------------------------- #
    def _validate(cfg: dict, payload: dict, *, partial: bool) -> list[dict]:
        errors: list[dict] = []
        for f in cfg["writable"]:
            name = f["name"]
            if name not in payload:
                if (not partial) and f.get("required") and BUG_SKIP_REQUIRED not in bugs:
                    errors.append({"field": name, "message": "field is required"})
                continue
            v = payload[name]
            if v is None:
                # An explicit null for a required field clears it — reject (even on PATCH),
                # else a cross-field/required constraint could be escaped by nulling a side.
                if f.get("required") and BUG_SKIP_REQUIRED not in bugs:
                    errors.append({"field": name, "message": "must not be null"})
                continue
            if BUG_SKIP_CONSTRAINTS in bugs:
                continue
            t = f.get("type")
            if t == "boolean" and not isinstance(v, bool):
                errors.append({"field": name, "message": "must be a boolean"})
                continue
            if t == "integer" and (not isinstance(v, int) or isinstance(v, bool)):
                errors.append({"field": name, "message": "must be an integer"})
                continue
            if t == "number" and (not isinstance(v, (int, float)) or isinstance(v, bool)):
                errors.append({"field": name, "message": "must be a number"})
                continue
            if t == "enum" and f.get("values") and v not in f["values"]:
                errors.append({"field": name, "message": "not an allowed value"})
                continue
            if isinstance(v, str) and f.get("pattern") and not re.match(f["pattern"], v):
                errors.append({"field": name, "message": "does not match required pattern"})
                continue
            if f.get("min") is not None and isinstance(v, (int, float)) and v < f["min"]:
                errors.append({"field": name, "message": f"must be >= {f['min']}"})
            if f.get("max") is not None and isinstance(v, (int, float)) and v > f["max"]:
                errors.append({"field": name, "message": f"must be <= {f['max']}"})
            if f.get("min_len") is not None and isinstance(v, str) and len(v) < f["min_len"]:
                errors.append({"field": name, "message": f"must be at least {f['min_len']} chars"})
            if f.get("max_len") is not None and isinstance(v, str) and len(v) > f["max_len"]:
                errors.append({"field": name, "message": f"must be at most {f['max_len']} chars"})
        return errors

    def _unique_field_conflict(cfg: dict, payload: dict, *, exclude_id: str | None) -> str | None:
        if BUG_SKIP_UNIQUE in bugs:
            return None
        id_field = cfg["id_field"]
        rows = _all_rows(cfg["name"])
        for uf in cfg["unique_fields"]:
            if uf not in payload:
                continue
            for row in rows:
                if exclude_id is not None and row.get(id_field) == exclude_id:
                    continue
                if row.get(uf) == payload[uf]:
                    return uf
        return None

    def _populate(cfg: dict, entity: dict) -> dict:
        out = dict(entity)
        for f in cfg["fields"]:
            name = f["name"]
            if name in cfg["server_managed"]:
                if BUG_ACCEPT_CLIENT_FIELDS in bugs and name in entity:
                    continue
                if f.get("type") == "uuid":
                    out[name] = str(uuid.uuid4())
                elif f.get("type") == "datetime":
                    out[name] = _now_iso()
            elif (
                name not in out and f.get("default") is not None and BUG_IGNORE_DEFAULT not in bugs
            ):
                out[name] = f["default"]
        return out

    def _strip_server_managed(cfg: dict, payload: dict) -> dict:
        if BUG_ACCEPT_CLIENT_FIELDS in bugs:
            return dict(payload)
        return {k: v for k, v in payload.items() if k not in cfg["server_managed"]}

    # ---- route registration (per resource) ------------------------------- #
    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    def _register(rname: str) -> None:
        cfg = resources[rname]
        base = cfg["path"]
        eps = cfg["endpoints"]
        id_field = cfg["id_field"]

        def field(name: str) -> dict | None:
            return next((f for f in cfg["fields"] if f["name"] == name), None)

        if "create" in eps:
            success = int(eps["create"].get("success", 201))

            @app.post(base, name=f"create_{rname}")
            async def create(request: Request):
                try:
                    payload = await request.json()
                except json.JSONDecodeError:
                    return _err([{"field": "_body", "message": "invalid JSON"}])
                if not isinstance(payload, dict):
                    return _err([{"field": "_body", "message": "expected an object"}])
                errors = _validate(cfg, payload, partial=False)
                if errors:
                    return _err(errors)
                clean = _strip_server_managed(cfg, payload)
                miss = _missing_parent_status(rname, clean)
                if miss is not None:
                    return JSONResponse(
                        status_code=miss,
                        content={"errors": [{"field": "_parent", "message": "parent not found"}]},
                    )
                cf_errs = _cross_field_errors(rname, clean)
                if cf_errs:
                    return _err(cf_errs)
                uconf = _unique_field_conflict(cfg, clean, exclude_id=None)
                if uconf:
                    return _conflict(uconf, "must be unique")
                cconf = _composite_conflict(rname, clean, exclude_id=None)
                if cconf:
                    return _conflict(cconf["fields"][0], "composite key must be unique")
                entity = _sm_initial(rname, _populate(cfg, clean))
                _insert(rname, entity, id_field)
                return JSONResponse(status_code=success, content=_apply_computed(rname, entity))

        if "list" in eps:
            lst = eps["list"]
            lsuccess = int(lst.get("success", 200))
            pagination = lst.get("pagination") or {}
            limit_param = pagination.get("limit_param", "limit")
            offset_param = pagination.get("offset_param", "offset")
            default_limit = int(pagination.get("default_limit", 20)) if pagination else None
            max_limit = int(pagination.get("max_limit", 100)) if pagination else None
            filters = lst.get("filters", []) or []
            sortable = set(lst.get("sort", []) or [])

            @app.get(base, name=f"list_{rname}")
            async def list_(request: Request):
                rows = _all_rows(rname)
                qp = request.query_params
                if BUG_IGNORE_FILTER not in bugs:
                    applied_one = False
                    for fname in filters:
                        if fname in qp:
                            if BUG_IGNORE_SECONDARY_FILTER in bugs and applied_one:
                                continue
                            want = _coerce(field(fname), qp[fname])
                            rows = [r for r in rows if r.get(fname) == want]
                            applied_one = True
                sort_param = qp.get("sort")
                if sort_param:
                    keys = []
                    for raw_key in sort_param.split(","):
                        raw_key = raw_key.strip()
                        desc = raw_key.startswith("-")
                        name = raw_key[1:] if desc else raw_key
                        if name in sortable:
                            keys.append((name, desc))
                    if BUG_IGNORE_SECONDARY_SORT in bugs:
                        keys = keys[:1]
                    for name, desc in reversed(keys):
                        rows = sorted(rows, key=lambda r, n=name: _sort_key(r.get(n)), reverse=desc)
                if default_limit is not None:
                    try:
                        limit = int(qp.get(limit_param, default_limit))
                    except ValueError:
                        limit = default_limit
                    if max_limit is not None and BUG_IGNORE_MAX_LIMIT not in bugs:
                        limit = min(limit, max_limit)
                    try:
                        offset = int(qp.get(offset_param, 0))
                    except ValueError:
                        offset = 0
                    rows = rows[offset : offset + limit]
                rows = [_apply_computed(rname, r) for r in rows]  # computed fields live per row
                if BUG_LIST_NOT_ARRAY in bugs:
                    return JSONResponse(status_code=lsuccess, content={"items": rows})
                return JSONResponse(status_code=lsuccess, content=rows)

        if "get" in eps:
            gsuccess = int(eps["get"].get("success", 200))
            gmissing = int(eps["get"].get("missing", 404))

            @app.get(base + "/{ident}", name=f"get_{rname}")
            async def get_one(ident: str):
                row = _get_row(rname, ident)
                if row is None:
                    if BUG_NO_404 in bugs:
                        return JSONResponse(status_code=gsuccess, content={})
                    return JSONResponse(
                        status_code=gmissing,
                        content={"errors": [{"field": id_field, "message": "not found"}]},
                    )
                return JSONResponse(status_code=gsuccess, content=_apply_computed(rname, row))

        if "update" in eps:
            usuccess = int(eps["update"].get("success", 200))
            umissing = int(eps["update"].get("missing", 404))

            @app.patch(base + "/{ident}", name=f"update_{rname}")
            async def update_one(ident: str, request: Request):
                row = _get_row(rname, ident)
                if row is None:
                    if BUG_NO_404 in bugs:
                        return JSONResponse(status_code=usuccess, content={})
                    return JSONResponse(
                        status_code=umissing,
                        content={"errors": [{"field": id_field, "message": "not found"}]},
                    )
                try:
                    patch = await request.json()
                except json.JSONDecodeError:
                    return _err([{"field": "_body", "message": "invalid JSON"}])
                if not isinstance(patch, dict):
                    return _err([{"field": "_body", "message": "expected an object"}])
                clean = _strip_server_managed(cfg, patch)
                # State-machine transition + immutability guards (owning resource).
                if BUG_ALLOW_ILLEGAL_TRANSITION not in bugs:
                    for r in sm_rules:
                        sfield = r["field"]
                        if _owner(sfield) != rname:
                            continue
                        current = row.get(sfield)
                        illegal = int(r.get("on_illegal", 409))
                        if current in r.get("locked_after", []):
                            return JSONResponse(
                                status_code=illegal,
                                content={"errors": [{"field": sfield, "message": "immutable"}]},
                            )
                        if sfield in clean and clean[sfield] != current:
                            if clean[sfield] not in r["transitions"].get(current, []):
                                return JSONResponse(
                                    status_code=illegal,
                                    content={
                                        "errors": [
                                            {"field": sfield, "message": "illegal state transition"}
                                        ]
                                    },
                                )
                errors = _validate(cfg, clean, partial=True)
                if errors:
                    return _err(errors)
                merged = dict(row)
                merged.update(clean)
                miss = _missing_parent_status(rname, merged)
                if miss is not None:
                    return JSONResponse(
                        status_code=miss,
                        content={"errors": [{"field": "_parent", "message": "parent not found"}]},
                    )
                cf_errs = _cross_field_errors(rname, merged)
                if cf_errs:
                    return _err(cf_errs)
                uconf = _unique_field_conflict(cfg, clean, exclude_id=ident)
                if uconf:
                    return _conflict(uconf, "must be unique")
                cconf = _composite_conflict(rname, merged, exclude_id=ident)
                if cconf:
                    return _conflict(cconf["fields"][0], "composite key must be unique")
                _save(rname, ident, merged)
                return JSONResponse(status_code=usuccess, content=_apply_computed(rname, merged))

        if "delete" in eps:
            dsuccess = int(eps["delete"].get("success", 204))
            dmissing = int(eps["delete"].get("missing", 404))

            @app.delete(base + "/{ident}", name=f"delete_{rname}")
            async def delete_one(ident: str):
                row = _get_row(rname, ident)
                if row is None:
                    if BUG_NO_404 in bugs:
                        return Response(status_code=dsuccess)
                    return JSONResponse(
                        status_code=dmissing,
                        content={"errors": [{"field": id_field, "message": "not found"}]},
                    )
                if _delete_blocked(rname, ident):
                    return _conflict("_children", "cannot delete: dependent children exist")
                _cascade_children(rname, ident)
                _remove(rname, ident)
                return Response(status_code=dsuccess)

    for name in resources:
        _register(name)

    return app


def _load_spec_beside() -> dict:
    """Load ``spec.json`` next to this file (used by the standalone entrypoint)."""
    from pathlib import Path

    return json.loads((Path(__file__).resolve().parent / "spec.json").read_text())


if __name__ == "__main__":  # pragma: no cover - exercised only as a booted service
    import os

    import uvicorn

    spec_dict = _load_spec_beside()
    application = build_app(spec_dict, db_path=os.environ.get("SERVICE_DB", "service.db"))
    uvicorn.run(
        application, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")), log_level="warning"
    )
