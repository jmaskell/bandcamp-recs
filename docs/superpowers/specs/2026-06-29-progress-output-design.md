# Terminal progress output

## Goal

Show what the recommender script is doing and how far along it is while it
runs. Today a run prints almost nothing — one Apple Music error line and a
final "Wrote recommendations" message — so a cold run (which can take many
minutes of throttled network calls) looks frozen. Add phase headers and live
progress bars for the long, loop-shaped phases.

This is additive and presentation-only: it changes no recommendation logic and
no output file. With progress disabled, the script behaves exactly as it does
today.

## Decisions

- **Live progress bars** via **tqdm** (added to `requirements.txt`). tqdm gives
  the bar, percentage, rate, ETA, and terminal-width/TTY handling for free.
- **One presentation seam:** a new `bandcamp_reco/progress.py` wraps tqdm so no
  other module imports it. A `Reporter` exposes `phase(label)` (a header line)
  and `bar(total, label)` (a context manager yielding an `.update(n=1)` handle).
- **Injected, not global:** the three functions that own loops gain one
  optional `reporter` parameter defaulting to a silent no-op, so every existing
  test stays green and the data functions remain testable.
- **Progress on stderr; the result line stays on stdout.** `2>/dev/null` still
  yields just the final `Wrote recommendations to …` line.
- **Auto-off when not a terminal** (tqdm `disable=None`) so pipes/CI logs don't
  fill with carriage-return noise. A `--quiet` flag forces everything off.
- **Counts that mean something:** the fan-collections bar counts fans actually
  fetched against `max_fans`, not raw usernames considered.

## Architecture

```
bandcamp_reco/
  progress.py    NEW: Reporter (tqdm wrapper), NULL_REPORTER, make_reporter
  main.py        change: --quiet flag; build + thread reporter; phase headers;
                 crawl-loop bar
  fans.py        change: get_fan_collections gains reporter=; fan bar
  apple_music.py change: lookup_pool gains reporter=; Apple lookup bar
requirements.txt change: add tqdm>=4.0
```

### `progress.py`

```python
NULL_REPORTER = Reporter(enabled=False)   # module-level, stateless no-op default

class Reporter:
    def __init__(self, enabled=True): ...
    def phase(self, label): ...           # enabled: print "→ <label>" to stderr; else no-op
    def bar(self, total, label): ...       # context manager -> handle with .update(n=1)

def make_reporter(quiet: bool) -> Reporter:   # Reporter(enabled=not quiet)
```

- `phase(label)` writes a one-line header to stderr (`flush=True`), or nothing
  when disabled.
- `bar(total, label)` is a context manager. Enabled, it creates
  `tqdm(total=total, desc=label, file=sys.stderr, disable=None)` and yields a
  small handle with `.update(n=1)`; on exit it closes the bar. Disabled, it
  yields a no-op handle. One `bar()` primitive is used everywhere, so every loop
  reads the same way:

  ```python
  with reporter.bar(len(crawl_albums), "Crawling supporters") as bar:
      for album in crawl_albums:
          ...
          bar.update()
  ```

- `NULL_REPORTER` is the default the data functions fall back to. It is
  stateless (every `bar()` yields a fresh no-op handle), so sharing one instance
  is safe.

### Phase mapping

| Phase | Where | Output |
| --- | --- | --- |
| Reading your collection | `run` → `get_collection(user)` | `phase()` header (paginated, quick — no bar) |
| Crawling supporters | the loop in `run` | bar, total = `len(crawl_albums)`, `update()` per album |
| Reading fan collections | inside `get_fan_collections` | bar, total = `max_fans`, `update()` per fan fetched |
| Scoring + per-record pools | `run` | `phase()` header (in-memory, fast) |
| Checking Apple Music | inside `lookup_pool` (via `_apply_apple_music`) | bar, total = albums to look up, `update()` per lookup |
| Writing page | `run` → `write_html` | `phase()` header |

Functions gaining one optional `reporter=NULL_REPORTER` parameter: `run`,
`get_fan_collections`, `lookup_pool`. `_apply_apple_music` threads it through.
No other signatures change.

### Two deliberate choices

- **Fan-collections bar counts fetched fans, not usernames considered.** The
  username list (supporters × albums) can be thousands, but the loop dedups and
  stops at `max_fans`; a bar over the raw list would crawl to ~15% and freeze
  when the cap hits. Counting fetched fans against `max_fans` makes progress
  honest (`230/500`, or a full `500/500`). The bar's `update()` fires only when
  a fan's collection is actually fetched and recorded.
- **The Apple bar appears only when Apple Music is enabled** — header and bar
  live inside the enabled path, so a run with it off looks exactly as before.

## Edge cases

- **Piped / non-TTY / CI:** tqdm `disable=None` auto-suppresses the bars; phase
  headers remain as plain, harmless log lines.
- **`--quiet`:** reporter disabled — no headers, no bars. The final stdout line
  and the existing Apple-error stderr line are unaffected (neither is progress).
- **Early termination** (`CircuitBreakerTripped` breaks a loop): the
  `with reporter.bar(...)` block closes the bar cleanly on exit; tqdm shows a
  partial count.
- **Apple Music disabled / nothing to look up:** no Apple header or bar.
- **Empty collection / `total == 0`:** tqdm renders `0/0` and finishes
  immediately — no special-casing.

## Testing

- New `tests/test_progress.py`:
  - `Reporter(enabled=False)`: `phase()` prints nothing; `bar()` yields a no-op
    handle whose `.update()` does not raise; it is a proper context manager.
  - `Reporter(enabled=True)`: `phase()` writes the label to stderr (via
    `capsys`); `bar()` yields a handle, and `update()`/context-exit do not raise.
    (Under pytest stderr is not a TTY, so `disable=None` keeps even an enabled
    bar silent — the seam is exercised without polluting test output.)
  - `make_reporter(quiet=True)` returns a disabled reporter; `quiet=False` an
    enabled one.
- Behavior preserved: `get_fan_collections`, `lookup_pool`, and `run` default to
  `NULL_REPORTER`, so existing tests pass untouched. Add one assertion each that
  passing a reporter still returns identical results.
- `tests/test_main.py`: `main(["--quiet"])` parses and runs silently;
  `run(..., reporter=...)` is accepted.

Test hygiene: defaults are silent and pytest's stderr is not a TTY, so no bar
output leaks into the test run.

## Out of scope

- Distinguishing cached vs freshly fetched items in the bar (the bar's speed
  already conveys it; would couple the loops to cache-hit state).
- Per-page progress inside a single `get_collection` call (the outer fan loop's
  bar is granular enough).
- Structured logging, log levels, or a logging framework.
- ETA accuracy tuning (cache hits make the rate non-uniform; tqdm's ETA will
  swing, which is acceptable).
