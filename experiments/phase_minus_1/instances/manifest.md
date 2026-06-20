# Phase −1 instance manifest — the 30 tasks

Same CRUD skeleton, escalating features (see `../domain.md` §4). Build one `*.spec.yaml` per row from the schema; `example_books.spec.yaml` is `books` below.

## Easy (E1–E10) — scalars; required/type/range/length only; create/get/list(no pagination)/delete; no uniqueness/filters/sort/partial/relationships

| key | resource | distinguishing detail |
|---|---|---|
| E1 | notes | title + body; min/max length |
| E2 | bookmarks | url (pattern) + label |
| E3 | tags | name + color (hex pattern) |
| E4 | todos | text + done(bool default false) |
| E5 | snippets | language + code; max_len |
| E6 | measurements | value(number) + unit |
| E7 | countries | name + iso_code(len 2) |
| E8 | quotes | text + author |
| E9 | habits | name + target_per_week(int range) |
| E10 | feeds | url(pattern) + title |

## Medium (M1–M10) — 6–9 fields incl. enum+datetime+bool-default; one unique field (→409); full CRUD incl. partial PATCH; list with pagination + 1–2 filters + 1 sort

| key | resource | unique | enum | filters / sort |
|---|---|---|---|---|
| M1 | books | isbn | genre | genre, in_stock / published_year, price_cents |
| M2 | products | sku | category | category, active / price_cents |
| M3 | customers | email | tier | tier / created_at |
| M4 | events | slug | status | status / starts_at |
| M5 | articles | slug | status | status, author_id / published_at |
| M6 | vehicles | vin | type | type, available / year |
| M7 | recipes | slug | difficulty | difficulty / prep_minutes |
| M8 | subscriptions | external_id | plan | plan, active / renews_at |
| M9 | tickets | reference | priority | priority, status / created_at |
| M10 | venues | slug | kind | kind, city / capacity |

## Hard (H1–H10) — Medium + ≥1 business rule; pagination + multiple filters + multi-sort

| key | resource | business rule |
|---|---|---|
| H1 | orders | state_machine: pending→paid→shipped→delivered; cancel only before shipped; invalid → 409 |
| H2 | reservations | cross_field: end_at > start_at; relationship: ref room; overlap on same room → 409 |
| H3 | accounts | computed_field: balance derived from posted transactions (ref) |
| H4 | projects | relationship: tasks ref project; deleting project with open tasks → 409 (restrict) |
| H5 | playlists | relationship + ordering: tracks ref playlist with unique position (composite_unique) |
| H6 | coupons | cross_field: discount_cents ≤ min_order_cents; state: active window by dates |
| H7 | shipments | state_machine: created→in_transit→delivered / exception; relationship: ref order |
| H8 | inventory | composite_unique: (sku, warehouse); computed_field: available = on_hand − reserved |
| H9 | appointments | cross_field + overlap: no two for same provider(ref) overlapping in time → 409 |
| H10 | invoices | computed_field: total = Σ line items(ref); state_machine: draft→sent→paid; immutable once paid |

## Fixed run order (interleaved — do not reorder)

Difficulty kept stationary so a downward cost slope is attributable to craft (`../domain.md` §4). Run in triplets `[Ek, Mk, Hk]`:

```
1:E1  2:M1  3:H1   4:E2  5:M2  6:H2   7:E3  8:M3  9:H3
10:E4 11:M4 12:H4  13:E5 14:M5 15:H5  16:E6 17:M6 18:H6
19:E7 20:M7 21:H7  22:E8 23:M8 24:H8  25:E9 26:M9 27:H9
28:E10 29:M10 30:H10
```

**Warm-up:** exclude positions 1–5 from the cost-per-task slope fit.
**Per-task budget cap:** set `budget_cap_usd` per task so one pathological instance can't distort the curve (suggest E ≈ $3, M ≈ $5, H ≈ $8; tune after the first triplet).
