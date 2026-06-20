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

Pinned conventions (must match harness/compiler.py):
* collection GET returns a JSON array;
* filtering ``?<field>=<value>`` (booleans ``true``/``false``);
* sorting ``?sort=<field>`` asc, ``?sort=-<field>`` desc;
* validation errors -> 422 ``{"errors": [{"field", "message"}]}``;
* unique conflict -> 409; unknown id -> 404.
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


def build_app(spec: dict, bugs: frozenset[str] = frozenset(), db_path: str = ":memory:") -> FastAPI:
    resource = spec["resource"]
    base = resource["path"]
    fields: list[dict] = resource["fields"]
    rules = spec.get("rules", {}) or {}
    err_status = int(rules.get("on_validation_error", 422))
    conflict_status = int(rules.get("on_unique_conflict", 409))
    endpoints = spec["endpoints"]

    def field(name: str) -> dict | None:
        return next((f for f in fields if f["name"] == name), None)

    id_field = next(
        (f["name"] for f in fields if f.get("generated") and f.get("type") == "uuid"),
        next((f["name"] for f in fields if f.get("generated")), "id"),
    )
    server_managed = {f["name"] for f in fields if f.get("generated") or f.get("readonly")}
    unique_fields = [f["name"] for f in fields if f.get("unique")]
    writable = [f for f in fields if not (f.get("generated") or f.get("readonly"))]

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS rows (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, data TEXT)"
    )
    conn.commit()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        conn.close()

    app = FastAPI(lifespan=lifespan)

    # ---- storage helpers -------------------------------------------------- #
    def _all_rows() -> list[dict]:
        cur = conn.execute("SELECT data FROM rows ORDER BY seq ASC")
        return [json.loads(r[0]) for r in cur.fetchall()]

    def _get_row(ident: str) -> dict | None:
        cur = conn.execute("SELECT data FROM rows WHERE id = ?", (ident,))
        row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def _insert(entity: dict) -> None:
        conn.execute(
            "INSERT INTO rows (id, data) VALUES (?, ?)", (entity[id_field], json.dumps(entity))
        )
        conn.commit()

    def _update(ident: str, entity: dict) -> None:
        conn.execute("UPDATE rows SET data = ? WHERE id = ?", (json.dumps(entity), ident))
        conn.commit()

    def _delete(ident: str) -> None:
        conn.execute("DELETE FROM rows WHERE id = ?", (ident,))
        conn.commit()

    # ---- validation ------------------------------------------------------- #
    def _validate(payload: dict, *, partial: bool) -> list[dict]:
        errors: list[dict] = []
        for f in writable:
            name = f["name"]
            present = name in payload
            if not present:
                if (not partial) and f.get("required") and BUG_SKIP_REQUIRED not in bugs:
                    errors.append({"field": name, "message": "field is required"})
                continue
            v = payload[name]
            if BUG_SKIP_CONSTRAINTS in bugs:
                continue  # broken variant: no value validation (type or constraint)
            t = f.get("type")
            # bool is a subclass of int — check it first so True/False isn't an int.
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

    def _unique_conflict(payload: dict, *, exclude_id: str | None = None) -> str | None:
        if BUG_SKIP_UNIQUE in bugs:
            return None
        rows = _all_rows()
        for uf in unique_fields:
            if uf not in payload:
                continue
            for row in rows:
                if exclude_id is not None and row.get(id_field) == exclude_id:
                    continue
                if row.get(uf) == payload[uf]:
                    return uf
        return None

    def _populate(entity: dict) -> dict:
        out = dict(entity)
        for f in fields:
            name = f["name"]
            if name in server_managed:
                # broken variant: keep a client-supplied value instead of generating
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

    def _strip_server_managed(payload: dict) -> dict:
        if BUG_ACCEPT_CLIENT_FIELDS in bugs:
            return dict(payload)  # broken variant: do not strip client-set server fields
        return {k: v for k, v in payload.items() if k not in server_managed}

    def _err(errors: list[dict]) -> JSONResponse:
        if BUG_WRONG_ENVELOPE in bugs:
            # broken variant: still 422, but not the pinned {"errors":[{field,message}]}
            detail = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
            return JSONResponse(status_code=err_status, content={"detail": detail})
        return JSONResponse(status_code=err_status, content={"errors": errors})

    # ---- routes ----------------------------------------------------------- #
    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    if "create" in endpoints:
        success = int(endpoints["create"].get("success", 201))

        @app.post(base)
        async def create(request: Request):
            try:
                payload = await request.json()
            except json.JSONDecodeError:
                return _err([{"field": "_body", "message": "invalid JSON"}])
            if not isinstance(payload, dict):
                return _err([{"field": "_body", "message": "expected an object"}])
            errors = _validate(payload, partial=False)
            if errors:
                return _err(errors)
            clean = _strip_server_managed(payload)
            conflict = _unique_conflict(clean)
            if conflict:
                return JSONResponse(
                    status_code=conflict_status,
                    content={"errors": [{"field": conflict, "message": "must be unique"}]},
                )
            entity = _populate(clean)
            _insert(entity)
            return JSONResponse(status_code=success, content=entity)

    if "list" in endpoints:
        lst = endpoints["list"]
        lsuccess = int(lst.get("success", 200))
        pagination = lst.get("pagination") or {}
        limit_param = pagination.get("limit_param", "limit")
        offset_param = pagination.get("offset_param", "offset")
        default_limit = int(pagination.get("default_limit", 20)) if pagination else None
        max_limit = int(pagination.get("max_limit", 100)) if pagination else None
        filters = lst.get("filters", []) or []
        sortable = set(lst.get("sort", []) or [])

        @app.get(base)
        async def list_(request: Request):
            rows = _all_rows()
            qp = request.query_params
            if BUG_IGNORE_FILTER not in bugs:
                applied_one = False
                for fname in filters:  # spec order; single-filter cases have exactly one present
                    if fname in qp:
                        if BUG_IGNORE_SECONDARY_FILTER in bugs and applied_one:
                            continue  # broken variant: only the first filter present is honoured
                        f = field(fname)
                        want = _coerce(f, qp[fname])
                        rows = [r for r in rows if r.get(fname) == want]
                        applied_one = True
            sort_param = qp.get("sort")
            if sort_param:
                # Composite sort: comma-separated keys, "-" prefix = descending. Applied
                # stably, least-significant key first, so the first key is primary.
                keys = []
                for raw_key in sort_param.split(","):
                    raw_key = raw_key.strip()
                    desc = raw_key.startswith("-")
                    name = raw_key[1:] if desc else raw_key
                    if name in sortable:
                        keys.append((name, desc))
                if BUG_IGNORE_SECONDARY_SORT in bugs:
                    keys = keys[:1]  # broken variant: no tie-break by later sort keys
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
            if BUG_LIST_NOT_ARRAY in bugs:
                return JSONResponse(status_code=lsuccess, content={"items": rows})
            return JSONResponse(status_code=lsuccess, content=rows)

    if "get" in endpoints:
        gsuccess = int(endpoints["get"].get("success", 200))
        gmissing = int(endpoints["get"].get("missing", 404))

        @app.get(base + "/{ident}")
        async def get_one(ident: str):
            row = _get_row(ident)
            if row is None:
                if BUG_NO_404 in bugs:
                    return JSONResponse(status_code=gsuccess, content={})
                return JSONResponse(
                    status_code=gmissing,
                    content={"errors": [{"field": id_field, "message": "not found"}]},
                )
            return JSONResponse(status_code=gsuccess, content=row)

    if "update" in endpoints:
        usuccess = int(endpoints["update"].get("success", 200))
        umissing = int(endpoints["update"].get("missing", 404))

        @app.patch(base + "/{ident}")
        async def update_one(ident: str, request: Request):
            row = _get_row(ident)
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
            clean = _strip_server_managed(patch)  # readonly/generated attempts are ignored
            errors = _validate(clean, partial=True)
            if errors:
                return _err(errors)
            conflict = _unique_conflict(clean, exclude_id=ident)
            if conflict:
                return JSONResponse(
                    status_code=conflict_status,
                    content={"errors": [{"field": conflict, "message": "must be unique"}]},
                )
            updated = dict(row)
            updated.update(clean)
            _update(ident, updated)
            return JSONResponse(status_code=usuccess, content=updated)

    if "delete" in endpoints:
        dsuccess = int(endpoints["delete"].get("success", 204))
        dmissing = int(endpoints["delete"].get("missing", 404))

        @app.delete(base + "/{ident}")
        async def delete_one(ident: str):
            row = _get_row(ident)
            if row is None:
                if BUG_NO_404 in bugs:
                    return Response(status_code=dsuccess)
                return JSONResponse(
                    status_code=dmissing,
                    content={"errors": [{"field": id_field, "message": "not found"}]},
                )
            _delete(ident)
            return Response(status_code=dsuccess)

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
