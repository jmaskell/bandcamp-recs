# Fair fan coverage (round-robin supporters) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spread the fan-fetch budget fairly across the whole collection by interleaving supporters column-major, so later/niche records stop starving.

**Architecture:** Replace the row-major flatten of `seed_supporters` in `run()` with a column-major round-robin (each record's #1 supporter, then each record's #2, …) via a small pure helper, so `get_fan_collections` spends the `max_fans` budget breadth-first. Reorder-only: same usernames, so results are unchanged when the budget isn't binding and merely fair when it is.

**Tech Stack:** Python 3.11+, pytest, stdlib only.

## Global Constraints

- **Reorder only** — the change must neither add nor drop any username; it only changes order. No budget (`max_fans`) or threshold (`per_record_min_fans`) change.
- **Deterministic** — a round-robin interleave, never a random shuffle (keeps the cache warm and runs reproducible).
- **Additive to results** — existing pipeline tests assert on the deduped result *set* (membership/sets), not order, and must stay green.
- **No new dependencies.**
- **Use the project venv** for all commands: `.venv/bin/python`.

---

### Task 1: Round-robin supporter interleave

**Files:**
- Modify: `bandcamp_reco/main.py` (add a `round_robin` helper; rewire the `supporter_usernames` flatten)
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `round_robin(lists: list[list]) -> list` — a module-level helper in `main.py` that interleaves several lists column-major, skipping exhausted lists, preserving every element.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_main.py` (the file already does `import bandcamp_reco.main as main_mod`):

```python
def test_round_robin_even_lists():
    assert main_mod.round_robin([[1, 2], [3, 4]]) == [1, 3, 2, 4]


def test_round_robin_uneven_skips_exhausted():
    assert main_mod.round_robin([[1, 2, 3], [4]]) == [1, 4, 2, 3]


def test_round_robin_empty_sublists_and_input():
    assert main_mod.round_robin([[], [1], []]) == [1]
    assert main_mod.round_robin([]) == []
    assert main_mod.round_robin([[1, 2, 3]]) == [1, 2, 3]


def test_round_robin_fairness_reaches_every_list_under_tight_budget():
    # With disjoint supporter lists, the first slice must already include BOTH
    # records — not just the first (the whole point of the fix).
    order = main_mod.round_robin([["a1", "a2", "a3"], ["b1", "b2", "b3"]])
    assert order[:4] == ["a1", "b1", "a2", "b2"]


def test_round_robin_preserves_all_elements():
    lists = [[1, 2, 3], [4], [5, 6]]
    out = main_mod.round_robin(lists)
    assert len(out) == sum(len(l) for l in lists)
    assert sorted(out) == sorted(x for l in lists for x in l)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_main.py::test_round_robin_even_lists -v`
Expected: FAIL — `AttributeError: module 'bandcamp_reco.main' has no attribute 'round_robin'`

- [ ] **Step 3: Add the `round_robin` helper**

In `bandcamp_reco/main.py`, add this function immediately **before** the line `def run(config, fetcher, cache, limit=None, reporter=NULL_REPORTER):`

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

- [ ] **Step 4: Rewire the flatten to use it**

In `bandcamp_reco/main.py`, replace:

```python
    supporter_usernames = [u for seed in seed_supporters.values() for u in seed]
```

with:

```python
    supporter_usernames = round_robin(list(seed_supporters.values()))
```

- [ ] **Step 5: Run the full suite to verify green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — the five new `round_robin` tests pass, and every existing test (including the `test_main` run tests, which assert on the deduped result set rather than order) stays green.

- [ ] **Step 6: Commit**

```bash
git add bandcamp_reco/main.py tests/test_main.py
git commit -m "feat: round-robin supporters so the fan budget spreads fairly across records"
```

---

## Self-Review

**1. Spec coverage**

| Spec item | Task |
| --- | --- |
| Column-major round-robin interleave of `seed_supporters` | Task 1 (helper + rewire) |
| `round_robin` is a module-level helper in `main.py`, unit-tested directly | Task 1 |
| Reorder only — no budget/threshold change | Task 1 (only line 74 changes; `max_fans`/`per_record_min_fans` untouched) |
| Deterministic (no shuffle) | Task 1 (pure index walk) |
| Edge cases: empty input, empty sublists, single list, element preservation | Task 1 tests |
| Fairness property (tight budget reaches every record) | Task 1 test `..._fairness_reaches_every_list...` |
| Existing pipeline tests stay green | Task 1 Step 5 (full suite) |

No gaps.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows complete code.

**3. Type consistency:** `round_robin(lists) -> list` is defined once and called once (`round_robin(list(seed_supporters.values()))`); the tests reference `main_mod.round_robin` matching the module-level definition. The rewired line's right-hand side is the only call site.
