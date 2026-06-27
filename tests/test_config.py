from bandcamp_reco.config import load_config, Config


def test_load_config_uses_defaults_when_file_missing(tmp_path):
    cfg = load_config(str(tmp_path / "nope.toml"))
    assert cfg.username == "jmaskell"
    assert cfg.top_n == 50
    assert cfg.request_delay == 0.7


def test_load_config_overlays_file_values(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('username = "someone"\ntop_n = 10\n')
    cfg = load_config(str(p))
    assert cfg.username == "someone"
    assert cfg.top_n == 10
    # untouched keys keep defaults
    assert cfg.max_fans == 500
    assert isinstance(cfg, Config)
