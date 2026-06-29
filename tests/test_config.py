from bandcamp_reco.config import load_config, Config, AppleMusicConfig


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


def test_apple_music_config_parsed_from_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        'username = "me"\n'
        "[apple_music]\n"
        "enabled = true\n"
        'country = "us"\n'
        "request_delay = 2.0\n"
    )
    cfg = load_config(str(p))
    assert cfg.username == "me"
    assert cfg.apple_music is not None
    assert cfg.apple_music.enabled is True
    assert cfg.apple_music.country == "us"
    assert cfg.apple_music.request_delay == 2.0


def test_apple_music_config_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('username = "me"\n[apple_music]\n')  # empty section
    cfg = load_config(str(p))
    assert cfg.apple_music is not None
    assert cfg.apple_music.enabled is True
    assert cfg.apple_music.country == "gb"        # default
    assert cfg.apple_music.request_delay == 3.0   # default


def test_apple_music_config_absent_when_no_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('username = "me"\n')
    cfg = load_config(str(p))
    assert cfg.apple_music is None


def test_apple_music_config_none_when_disabled(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('username = "me"\n[apple_music]\nenabled = false\n')
    cfg = load_config(str(p))
    assert cfg.apple_music is None


def test_per_record_settings_default_and_override(tmp_path):
    cfg = load_config(str(tmp_path / "nope.toml"))
    assert cfg.per_record_pool_size == 60
    assert cfg.per_record_min_fans == 2

    p = tmp_path / "config.toml"
    p.write_text("per_record_pool_size = 25\nper_record_min_fans = 3\n")
    cfg2 = load_config(str(p))
    assert cfg2.per_record_pool_size == 25
    assert cfg2.per_record_min_fans == 3
