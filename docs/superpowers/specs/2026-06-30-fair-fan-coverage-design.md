# Fair fan coverage (round-robin supporters)

## Goal

Spread the fan-fetch budget fairly across the whole collection so later/niche
records stop systematically starving. Today the `max_fans` budget is spent
first-come-first-served in collection order, so the earliest records' supporters
fill it and later records get no fan collections fetched — which is why only
26 of the user's 52 records currently show "enough data" in the "By record"
view.

## Background — the bug

`run()` collects supporters per owned record and flattens them **row-major**
(all of record 1's supporters, then all of record 2's, …):

```python
supporter_usernames = [u for seed in seed_supporters.values() for u in seed]   # main.py:74
```

`get_fan_collections` then walks that list top-to-bottom and stops once it has
fetched `max_fans` (500) distinct fans (`fans.py`). So the budget is consumed by
the records earliest in collection order; records whose supporters appear only
after the 500th distinct fan never get fetched, and their per-record pool comes
back empty → excluded from the picker.

The cache confirms it: `profile_blob` holds exactly 501 entries (the user + 500
fans → the cap was hit), the collection is 52 records, and exactly 26 (~half)
are pickable — the front half in crawl order.

## Decision

Change the flatten to a **column-major round-robin interleave**: take each
record's #1 supporter, then each record's #2, and so on. `get_fan_collections`
then spends the same 500-fan budget breadth-first, so every record gets its top
supporters fetched before any record goes deep. With 52 records and a 500-fan
budget that is ~10 fans per record — ample for the existing 2-fan threshold.

Scope is deliberately minimal (decided during brainstorming):

- **No budget change.** `max_fans` stays 500 — already generous once spread
  fairly at this collection size.
- **No threshold change.** `per_record_min_fans` stays 2. Round-robin alone is
  expected to rescue most of the 26→52; the floor drop is a separate,
  belt-and-suspenders follow-up only if a genuine long tail still starves.
- **Reorder only**, never a random shuffle — determinism keeps the cache warm
  and runs reproducible.

## Architecture

```
bandcamp_reco/
  main.py    change: add round_robin() helper; use it at the flatten (line ~74)
```

One pure helper, one rewired line. No other files change.

### `round_robin`

```python
def round_robin(lists):
    """Interleave lists column-major: every list's 0th item, then every list's
    1st item, and so on, skipping lists that have run out. Spreads the fan-fetch
    budget fairly across records instead of front-loading the earliest records'
    supporters."""
    result, i = [], 0
    while True:
        added = False
        for lst in lists:
            if i < len(lst):
                result.append(lst[i])
                added = True
        if not added:
            break
        i += 1
    return result
```

A module-level helper in `main.py` (where the transform lives), unit-tested
directly.

### The wiring change

Replace:

```python
supporter_usernames = [u for seed in seed_supporters.values() for u in seed]
```

with:

```python
supporter_usernames = round_robin(list(seed_supporters.values()))
```

### Why existing behaviour is preserved

`round_robin` only reorders the usernames — it neither adds nor drops any. So:

- When the `max_fans` budget is **not** binding, `get_fan_collections` dedups to
  the identical fan set, and results are unchanged.
- When it **is** binding, the fetched set becomes fair (spread across records)
  instead of front-loaded. The whole-collection view shifts toward a more
  diverse fan set — neutral-to-positive (high-overlap fans still sort to the top
  of many records' lists, so they are still fetched first).
- Existing pipeline tests assert on the **deduped result set** (membership and
  sets), not on order, so they stay green.

## Edge cases

- **No records crawled / all supporter fetches failed:** `round_robin([]) == []`,
  identical to today's empty flatten.
- **A record with zero supporters:** its empty sublist is skipped naturally.
- **`--limit N`:** round-robin runs across the first N crawled records;
  orthogonal, no special handling.
- **Duplicate usernames across records:** preserved in the interleaved order;
  `get_fan_collections` dedups exactly as before.
- **Determinism:** given the stable crawl order, the interleave is deterministic,
  so the cache stays warm across runs.

## Testing

- Unit-test `round_robin` directly:
  - Even lists: `round_robin([[1,2],[3,4]]) == [1,3,2,4]`
  - Uneven (skips exhausted): `round_robin([[1,2,3],[4]]) == [1,4,2,3]`
  - Empty sublists skipped: `round_robin([[],[1],[]]) == [1]`; `round_robin([]) == []`;
    single list returned unchanged
  - Fairness property: with disjoint lists a tight budget still reaches every
    record — `round_robin([["a1","a2","a3"],["b1","b2","b3"]])[:4] == ["a1","b1","a2","b2"]`
  - No element loss: output length == sum of input lengths
- No-regression: the existing `test_main` run tests stay green (they use 1–2
  supporters and assert on the deduped result set, not order).

## Out of scope

- Raising `max_fans` or any per-record fan target / budget machinery (the 500
  budget is already ample once spread fairly at 52 records).
- Lowering `per_record_min_fans` (and the page's min-fans slider floor/default) —
  the belt-and-suspenders long-tail fix, revisited only if records still starve
  after round-robin.
- Any change to the whole-collection view's own scoring or thresholds.
- Documentation/copy changes (the picker's "M of your records have enough data"
  stays accurate; M just gets larger).
