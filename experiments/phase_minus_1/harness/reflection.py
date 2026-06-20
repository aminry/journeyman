"""Reflection guardrails + the per-feature craft taxonomy (ADR-0020 §4; T-1.3).

Reflection (Step E of the driver loop) is the linchpin of the experiment: a bad
reflection that writes vague/over-fit craft mis-states compounding. Phase −1 has no
promotion gate, so the anti-rot guardrails are harness-enforced here:

* **reflect-on-signal** — reflect only when the effector retried, failed first-pass,
  or the task introduced an uncovered feature (locked decision 1);
* **project-stripping lint** — reject instance identifiers (resource/related names,
  path segments, field names) in craft bodies, so only generic craft is written
  (the two-plane knowledge boundary, ADR-0006);
* **dedupe** — one canonical item per feature tag, evolved via UPDATE not proliferated;
* **the taxonomy** — the ~13 per-feature orchestration items ADR-0020 §4 names. Each
  template is generic by construction (proven by the lint test against all 30 specs).

The real (Anthropic) driver writes craft by its own judgment, subject to these same
guardrails; the FakeDriver writes from this taxonomy deterministically so the whole
loop is provable with zero spend.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from harness.craft import CraftItem
from harness.specschema import InstanceSpec

# Ultra-generic tokens that are common English even when they happen to be field or
# resource names; generic craft legitimately uses them, so they are never flagged.
GENERIC_TOKENS = {
    "id",
    "name",
    "status",
    "state",
    "type",
    "types",
    "active",
    "title",
    "value",
    "values",
    "text",
    "body",
    "url",
    "label",
    "color",
    "kind",
    "date",
    "time",
    "count",
    "order",
    "sort",
    "tag",
    "tags",
    "field",
    "fields",
    "code",
    "data",
    "item",
    "items",
    "list",
    "page",
    "size",
    "key",
    "keys",
    "row",
    "rows",
    "unit",
    "price",
    "rate",
    "total",
    "amount",
    "number",
    "entry",
    "record",
    "default",
    "event",
    "events",
    "link",
    "links",
    "note",
    "notes",
}


# --------------------------------------------------------------------------- #
# reflect-on-signal (locked decision 1)
# --------------------------------------------------------------------------- #
def reflect_on_signal(
    *, effector_retries: int, first_pass: bool, uncovered_tags: list[str]
) -> bool:
    """Reflect only on a learning signal: a retry, a first-pass failure, or a new
    (uncovered) feature. The default is SKIP, to keep the library from bloating."""
    return effector_retries > 0 or not first_pass or bool(uncovered_tags)


# --------------------------------------------------------------------------- #
# project-stripping lint
# --------------------------------------------------------------------------- #
def _instance_identifiers(spec: InstanceSpec) -> set[str]:
    ids: set[str] = set()

    def add_resource(name: str, path: str, fields) -> None:
        ids.add(name)
        for seg in path.strip("/").split("/"):
            ids.add(seg)
        for f in fields:
            ids.add(f.name)

    add_resource(spec.resource.name, spec.resource.path, spec.resource.fields)
    if spec.related is not None:
        add_resource(
            spec.related.resource.name,
            spec.related.resource.path,
            spec.related.resource.fields,
        )
    return {i.lower() for i in ids if len(i) >= 3 and i.lower() not in GENERIC_TOKENS}


def project_strip_lint(text: str, spec: InstanceSpec) -> list[str]:
    """Return the instance identifiers that leak into ``text`` (empty list = clean).

    Whole-word, case-insensitive. Catches distinctive domain identifiers (``orders``,
    ``isbn``, ``discount_cents``, ``warehouse``) without over-flagging generic English."""
    found: set[str] = set()
    low = text.lower()
    for ident in _instance_identifiers(spec):
        if re.search(rf"\b{re.escape(ident)}\b", low):
            found.add(ident)
    return sorted(found)


# --------------------------------------------------------------------------- #
# The per-feature craft taxonomy (ADR-0020 §4)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CraftTemplate:
    craft_id: str
    summary: str
    when_to_use: str
    body: str
    tags: tuple[str, ...]
    feature_keys: tuple[str, ...] = ()  # instance feature tags that make this relevant
    universal: bool = False  # relevant to every instance (no distinguishing tag names it)

    def to_craft_item(
        self, *, validated_against: dict, last_validated: str, version: str = "1.0.0"
    ) -> CraftItem:
        return CraftItem(
            id=self.craft_id,
            kind="orchestration",
            summary=self.summary,
            when_to_use=self.when_to_use,
            body=self.body,
            tags=list(self.tags),
            tests=["reflection-template"],
            version=version,
            scope="local",
            generic=True,
            status="active",
            validated_against=validated_against,
            last_validated=last_validated,
        )


def _t(craft_id, summary, when_to_use, body, tags, feature_keys=(), universal=False):
    return CraftTemplate(
        craft_id=craft_id,
        summary=summary,
        when_to_use=when_to_use,
        body=body.strip(),
        tags=tuple(tags),
        feature_keys=tuple(feature_keys),
        universal=universal,
    )


TAXONOMY: dict[str, CraftTemplate] = {
    t.craft_id: t
    for t in [
        _t(
            "crud-spec-template",
            "Skeleton for composing a spec-described CRUD/REST TaskSpec.",
            "When building any spec-described CRUD/REST service.",
            """
Restate intent, then drive the effector resource-by-resource: declare every endpoint,
its success and not-found codes, and each field's type and constraints. Implement the
collection endpoint as a bare JSON array. Keep one source of truth for the schema and
echo created entities back verbatim plus any server-populated fields.
""",
            ["crud", "rest", "spec"],
            feature_keys=["crud"],
            universal=True,
        ),
        _t(
            "fastapi-sqlite-scaffold",
            "Playbook for the fixed Python+FastAPI+file-SQLite stack.",
            "When building a CRUD service on the fixed Phase-1 stack.",
            """
Expose run.sh that starts the service on $PORT and a health endpoint returning 200 when
ready. Use file-based SQLite with a single worker (in-memory plus multiple connections
loses writes under black-box testing). Open the database from an absolute path.
""",
            ["fastapi", "sqlite", "scaffold", "boot"],
            feature_keys=[],
            universal=True,
        ),
        _t(
            "validation-422-shape",
            "The validation-error response contract.",
            "When the spec has required fields or constraints (every instance).",
            """
Reject a missing required input or a constraint violation with the configured
validation code and a stable error envelope: an errors array of objects, each naming
the offending input and a human reason. Check a boundary-valid input still succeeds.
""",
            ["validation", "error-shape"],
            feature_keys=[],
            universal=True,
        ),
        _t(
            "server-managed-fields-recipe",
            "Handling generated / read-only fields.",
            "When the spec has generated or read-only fields (every instance).",
            """
Treat generated and read-only inputs as server-managed: ignore any client-supplied
value, populate them server-side, and reject or ignore attempts to change them on a
partial update. Always echo them back so a reader sees the server's value.
""",
            ["server-managed", "readonly", "generated"],
            feature_keys=[],
            universal=True,
        ),
        _t(
            "pagination-contract",
            "Correct list pagination.",
            "When the list endpoint declares pagination.",
            """
Honor the limit and offset query parameters; apply the default window when none is
given; hard-cap the window at the configured maximum even if a larger one is requested.
Keep a stable total ordering so pages do not overlap or drop entries.
""",
            ["pagination", "limit", "offset"],
            feature_keys=["pagination"],
        ),
        _t(
            "unique-409-recipe",
            "Single-field uniqueness conflicts.",
            "When a field is declared unique.",
            """
Enforce uniqueness at write time and return the configured conflict code on a duplicate,
not a generic validation failure. Apply the same check on the create and update paths.
""",
            ["unique", "conflict"],
            feature_keys=["unique"],
        ),
        _t(
            "sort-contract",
            "Sorting the list endpoint.",
            "When the list endpoint declares sortable fields.",
            """
Accept a sort parameter naming a field; a leading minus means descending. For a
composite sort, apply the keys left to right (primary, then tie-breakers). Reject an
unknown sort key rather than silently ignoring it.
""",
            ["sort", "ordering"],
            feature_keys=["sort", "multi-sort"],
        ),
        _t(
            "filter-contract",
            "Filtering the list endpoint.",
            "When the list endpoint declares filterable fields.",
            """
Filter by equality on each declared field via its query parameter; booleans as
true/false. When several filters are supplied they AND together — a returned entry must
match every supplied filter.
""",
            ["filters", "query"],
            feature_keys=["filters", "multi-filter"],
        ),
        _t(
            "state-machine-playbook",
            "Lifecycle state machines.",
            "When the spec declares a state_machine business rule.",
            """
New entities begin in the declared starting state. Permit only declared transitions;
reject any other (including any transition out of a terminal state) with the configured
conflict code. Once locked, further changes are rejected with the same code.
""",
            ["rule:state_machine", "lifecycle", "transition"],
            feature_keys=["rule:state_machine"],
        ),
        _t(
            "cross-field-rule-recipe",
            "Cross-field constraints.",
            "When the spec declares a cross_field business rule.",
            """
Validate the declared relation between two inputs (for example one must not exceed
another) on both create and update, using the values that would result after the change.
Reject a violating combination with the configured validation code.
""",
            ["rule:cross_field", "constraint"],
            feature_keys=["rule:cross_field"],
        ),
        _t(
            "relationship-ref-recipe",
            "References to a second resource.",
            "When the spec declares a relationship (ref) business rule.",
            """
A child references a parent by id. Reject creating a child whose parent does not exist
with the configured code. On parent deletion honor the declared policy: restrict
(refuse while children remain) or cascade (remove the children too).
""",
            ["rule:relationship", "reference", "second-resource"],
            feature_keys=["rule:relationship"],
        ),
        _t(
            "composite-unique-recipe",
            "Multi-field (composite) uniqueness.",
            "When the spec declares a composite_unique business rule.",
            """
Enforce uniqueness over the declared tuple of fields together (not each alone); a
duplicate of the combination returns the configured conflict code. Enforce it on create
and on any update that changes a member of the tuple.
""",
            ["rule:composite_unique", "conflict"],
            feature_keys=["rule:composite_unique"],
        ),
        _t(
            "computed-field-recipe",
            "Server-derived (computed) read-only fields.",
            "When the spec declares a computed_field business rule.",
            """
A derived read-only output is computed server-side — either from sibling inputs of the
same entry or aggregated over related child entries. Never trust a client-supplied
value for it. Recompute it on every read after any change to its inputs or children, so
a reader never sees a stale figure.
""",
            ["rule:computed_field", "derived", "read-side"],
            feature_keys=["rule:computed_field"],
        ),
    ]
}

# Stable write order: universals first (learned early), then feature-keyed items.
ORDERED_CRAFT_IDS: list[str] = [c for c, t in TAXONOMY.items() if t.universal] + [
    c for c, t in TAXONOMY.items() if not t.universal
]

_FEATURE_TO_CRAFT: dict[str, str] = {
    fk: t.craft_id for t in TAXONOMY.values() for fk in t.feature_keys
}


def feature_tag_to_craft_id(feature_tag: str) -> str | None:
    """The canonical craft id a distinguishing feature tag maps to (None if none)."""
    return _FEATURE_TO_CRAFT.get(feature_tag)


_TOK = re.compile(r"[a-z0-9_]+")


def is_canonical(craft_id: str) -> bool:
    """True iff ``craft_id`` is one of the 13 canonical taxonomy ids (ADR-0020 §4)."""
    return craft_id in TAXONOMY


def taxonomy_catalog() -> list[dict]:
    """The canonical craft vocabulary handed to the driver so it WRITEs/UPDATEs by a
    canonical id (not a free-form one): id + feature_keys + when_to_use + universal."""
    return [
        {
            "id": t.craft_id,
            "feature_keys": list(t.feature_keys),
            "when_to_use": t.when_to_use,
            "universal": t.universal,
        }
        for t in TAXONOMY.values()
    ]


def nearest_canonical_id(
    craft_id: str, tags: list[str] | tuple[str, ...] = (), summary: str = "", when_to_use: str = ""
) -> str:
    """Remap a possibly-non-canonical craft id to the NEAREST canonical taxonomy id.

    The validate-against-taxonomy backstop (G1 Option A): never reject-and-drop a
    reflection (that would lose a real lesson and bias coverage down) — always remap to
    the closest canonical item. Deterministic: (1) pass through if already canonical;
    (2) map via any feature tag the driver supplied; (3) otherwise pick the taxonomy item
    with the greatest token overlap (ties broken by id). Always returns a taxonomy id."""
    if craft_id in TAXONOMY:
        return craft_id
    for t in tags:
        cid = _FEATURE_TO_CRAFT.get(t)
        if cid is not None:
            return cid
    query = f"{craft_id} {' '.join(tags)} {summary} {when_to_use}".lower()
    q = set(_TOK.findall(query))
    best_id, best_score = None, -1
    for cid, tpl in TAXONOMY.items():
        doc = f"{cid} {' '.join(tpl.tags)} {' '.join(tpl.feature_keys)} {tpl.summary} {tpl.when_to_use}"
        score = len(q & set(_TOK.findall(doc.lower())))
        if score > best_score or (score == best_score and (best_id is None or cid < best_id)):
            best_id, best_score = cid, score
    return best_id  # type: ignore[return-value]  # TAXONOMY is non-empty


def template_for_craft_id(craft_id: str) -> CraftTemplate:
    return TAXONOMY[craft_id]


def relevant_craft_ids(feature_tags: list[str]) -> set[str]:
    """Every craft id that *should* be relevant to an instance with these feature tags:
    the universals (relevant to all) plus those keyed by a present feature tag. This is
    the taxonomy-level relevance the curated gold map (G2) resolves against."""
    relevant = {c for c, t in TAXONOMY.items() if t.universal}
    for tag in feature_tags:
        cid = _FEATURE_TO_CRAFT.get(tag)
        if cid is not None:
            relevant.add(cid)
    return relevant


def _active_ids(library) -> set[str]:
    return {cid for cid in library.ids() if library.read(cid).status == "active"}


def uncovered_relevant_craft_ids(feature_tags: list[str], library) -> list[str]:
    """Relevant craft ids not yet present (active) in the library, in write order."""
    missing = relevant_craft_ids(feature_tags) - _active_ids(library)
    return [cid for cid in ORDERED_CRAFT_IDS if cid in missing]


def craft_templates_to_write(feature_tags: list[str], library) -> list[CraftTemplate]:
    """The templates a fresh reflection would write for this instance, in order."""
    return [TAXONOMY[cid] for cid in uncovered_relevant_craft_ids(feature_tags, library)]


def canonical_fraction(library) -> tuple[float, list[str]]:
    """Run-health (G1 condition 4): (fraction of ACTIVE craft ids that are canonical
    taxonomy ids, the sorted list of any non-canonical 'rogue' ids). Empty library = 1.0."""
    active = [cid for cid in library.ids() if library.read(cid).status == "active"]
    if not active:
        return 1.0, []
    rogue = sorted(c for c in active if c not in TAXONOMY)
    return (len(active) - len(rogue)) / len(active), rogue


def canonical_for_feature(feature_tag: str, library) -> CraftItem | None:
    """The existing active craft item for a feature tag, if any (dedupe / UPDATE target)."""
    cid = feature_tag_to_craft_id(feature_tag)
    if cid is None or cid not in _active_ids(library):
        return None
    return library.read(cid)
