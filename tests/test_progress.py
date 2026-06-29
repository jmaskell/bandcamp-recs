from bandcamp_reco.progress import Reporter, NULL_REPORTER, make_reporter


def test_disabled_reporter_is_silent(capsys):
    r = Reporter(enabled=False)
    r.phase("Reading your collection")
    with r.bar(10, "Crawling") as bar:
        bar.update()
        bar.update(2)
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""


def test_enabled_phase_writes_header_to_stderr(capsys):
    r = Reporter(enabled=True)
    r.phase("Crawling supporters")
    out, err = capsys.readouterr()
    assert "→ Crawling supporters" in err
    assert out == ""   # progress never goes to stdout


def test_enabled_bar_is_usable_and_does_not_raise(capsys):
    r = Reporter(enabled=True)
    with r.bar(3, "Reading fan collections") as bar:
        bar.update()
        bar.update()
        bar.update()
    # Under pytest stderr is not a TTY, so tqdm disable=None suppresses the bar;
    # we assert the seam works without raising and never writes stdout.
    out, _ = capsys.readouterr()
    assert out == ""


def test_null_reporter_is_disabled():
    assert NULL_REPORTER.enabled is False
    with NULL_REPORTER.bar(5, "x") as bar:
        bar.update()  # no-op, must not raise


def test_make_reporter_quiet_flag():
    assert make_reporter(quiet=True).enabled is False
    assert make_reporter(quiet=False).enabled is True
