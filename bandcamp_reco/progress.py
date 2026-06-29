import sys
from contextlib import contextmanager

from tqdm import tqdm


class _NullBar:
    """A no-op progress handle used when reporting is disabled."""

    def update(self, n=1):
        pass


class Reporter:
    """Presents pipeline progress. Wraps tqdm so nothing else imports it.

    `enabled=False` makes every method a no-op (the default for library
    functions, so they stay silent and testable). Bars additionally auto-
    disable when stderr is not a TTY (tqdm `disable=None`), so pipes and CI
    logs stay clean even when enabled."""

    def __init__(self, enabled=True):
        self.enabled = enabled

    def phase(self, label):
        if self.enabled:
            print(f"→ {label}", file=sys.stderr, flush=True)

    @contextmanager
    def bar(self, total, label):
        if not self.enabled:
            yield _NullBar()
            return
        bar = tqdm(total=total, desc=label, file=sys.stderr, disable=None)
        try:
            yield bar
        finally:
            bar.close()


NULL_REPORTER = Reporter(enabled=False)


def make_reporter(quiet: bool) -> "Reporter":
    return Reporter(enabled=not quiet)
