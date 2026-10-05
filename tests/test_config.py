import pytest

from esbi_cli.config import load_config


def write(tmp_path, run_section=""):
    path = tmp_path / "config.toml"
    path.write_text(f'[paths]\nvault = "{tmp_path}"\n{run_section}', encoding="utf-8")
    return path


def test_contradiction_flagging_is_off_unless_the_config_turns_it_on(tmp_path):
    assert load_config(write(tmp_path)).flag_contradictions is False
    on = load_config(write(tmp_path, "[run]\nflag_contradictions = true\n"))
    assert on.flag_contradictions is True


def test_the_update_check_is_on_unless_the_config_turns_it_off(tmp_path):
    assert load_config(write(tmp_path)).update.check is True
    assert load_config(write(tmp_path, "[update]\ncheck = false\n")).update.check is False


def test_the_update_check_setting_can_be_read_without_validating_the_rest(tmp_path, monkeypatch):
    from esbi_cli.config import wants_update_check

    monkeypatch.setenv("ESBI_CONFIG", str(write(tmp_path, "[update]\ncheck = false\n")))
    assert wants_update_check() is False
    monkeypatch.setenv("ESBI_CONFIG", str(write(tmp_path)))
    assert wants_update_check() is True
    monkeypatch.setenv("ESBI_CONFIG", str(write(tmp_path, "[update]\nchek = 1\n[nope")))
    assert wants_update_check() is True  # a broken file is another command's error to report
    monkeypatch.setenv("ESBI_CONFIG", str(tmp_path / "missing.toml"))
    assert wants_update_check() is True


def test_the_update_section_refuses_unknown_keys_and_wrong_types(tmp_path):
    with pytest.raises(ValueError, match=r"\[update\] has an unknown key 'chek'"):
        load_config(write(tmp_path, "[update]\nchek = false\n"))
    with pytest.raises(ValueError, match=r"\[update\].check must be true or false"):
        load_config(write(tmp_path, '[update]\ncheck = "no"\n'))


def test_the_usd_cap_is_off_unless_set_and_must_be_a_positive_number(tmp_path):
    assert load_config(write(tmp_path)).max_usd_per_run is None
    assert load_config(write(tmp_path, "[run]\nmax_usd_per_run = 1.5\n")).max_usd_per_run == 1.5
    assert load_config(write(tmp_path, "[run]\nmax_usd_per_run = 2\n")).max_usd_per_run == 2
    with pytest.raises(ValueError, match=r"\[run\].max_usd_per_run must be a number"):
        load_config(write(tmp_path, '[run]\nmax_usd_per_run = "5"\n'))
    for bad in ("0", "-1.0"):
        with pytest.raises(ValueError, match=r"max_usd_per_run must be more than 0"):
            load_config(write(tmp_path, f"[run]\nmax_usd_per_run = {bad}\n"))


def test_a_scanned_pdf_is_read_up_to_ten_pages_unless_the_config_says_otherwise(tmp_path):
    assert load_config(write(tmp_path)).ocr_max_pages == 10
    assert load_config(write(tmp_path, "[run]\nocr_max_pages = 3\n")).ocr_max_pages == 3


def test_config_search_order_and_the_fallback_next_to_the_installed_project(tmp_path, monkeypatch):
    from esbi_cli import config as config_module

    cwd_cfg, project_cfg, env_cfg, explicit = (tmp_path / n for n in ("cwd", "proj", "env", "exp"))
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATHS", (cwd_cfg, project_cfg))
    monkeypatch.delenv("ESBI_CONFIG", raising=False)

    with pytest.raises(FileNotFoundError, match="cwd"):  # the message lists where it looked
        config_module.find_config()

    project_cfg.write_text("x")
    assert config_module.find_config() == project_cfg  # `sb` run from any other folder

    cwd_cfg.write_text("x")
    assert config_module.find_config() == cwd_cfg  # the current folder wins over the project's

    env_cfg.write_text("x")
    monkeypatch.setenv("ESBI_CONFIG", str(env_cfg))
    assert config_module.find_config() == env_cfg
    explicit.write_text("x")
    assert config_module.find_config(explicit) == explicit  # --config wins over everything


def test_the_nightly_time_defaults_to_three_and_can_be_set_as_hours_and_minutes(tmp_path):
    assert load_config(write(tmp_path)).nightly_at == (3, 0)
    cfg = load_config(write(tmp_path, '[run]\nnightly_time = "04:30"\n'))
    assert cfg.nightly_at == (4, 30)


@pytest.mark.parametrize("bad", ["25:00", "3pm", "03:60", "", "0300"])
def test_a_nightly_time_that_is_not_hh_mm_is_refused_with_the_expected_form(tmp_path, bad):
    with pytest.raises(ValueError, match="HH:MM"):
        load_config(write(tmp_path, f'[run]\nnightly_time = "{bad}"\n'))


def test_the_viewer_is_obsidian_unless_the_notes_section_says_none(tmp_path):
    assert load_config(write(tmp_path)).viewer == "obsidian"
    assert load_config(write(tmp_path, '[notes]\nviewer = "none"\n')).viewer == "none"
    with pytest.raises(ValueError, match="obsidian.*none"):
        load_config(write(tmp_path, '[notes]\nviewer = "notion"\n'))


def test_the_notes_are_written_in_english_unless_the_config_names_a_language(tmp_path):
    assert load_config(write(tmp_path)).language == "en"
    assert load_config(write(tmp_path, '[notes]\nlanguage = "es"\n')).language == "es"


def test_an_unsupported_language_is_refused_when_the_config_is_read(tmp_path):
    with pytest.raises(ValueError, match=r"\[notes\]\.language must be one of: en, es, got 'fr'"):
        load_config(write(tmp_path, '[notes]\nlanguage = "fr"\n'))


def _error(tmp_path, body):
    with pytest.raises(ValueError) as caught:
        load_config(write(tmp_path, body))
    return str(caught.value)


def test_a_misspelled_key_names_the_section_the_key_and_the_valid_keys(tmp_path):
    text = _error(tmp_path, '[llm.summarize]\nmodel = "ollama/x"\nnum_ctxx = 4096\n')
    assert "[llm.summarize]" in text and "'num_ctxx'" in text
    assert "did you mean 'num_ctx'" in text and "base_url" in text and "\n" not in text


@pytest.mark.parametrize(
    "body, section, key",
    [
        ("[email]\nenabld = true\n", "[email]", "'enabld'"),
        ("[bench]\ncasess = 2\n", "[bench]", "'casess'"),
        ("[run]\nmax_chunk = 3\n", "[run]", "'max_chunk'"),
        ("[notes]\nlanguge = 'es'\n", "[notes]", "'languge'"),
        ("legacy_vaul = '/x'\n", "[paths]", "'legacy_vaul'"),
        ("[llms.summarize]\nmodel = 'x'\n", "[llms]", "llms"),
    ],
)
def test_an_unknown_key_in_any_section_is_refused_with_its_name(tmp_path, body, section, key):
    text = _error(tmp_path, body)
    assert section in text and key in text


@pytest.mark.parametrize(
    "body, expected",
    [
        ('[llm.summarize]\nmodel = "x"\nnum_ctx = "big"\n', "[llm.summarize].num_ctx"),
        ('[run]\nmax_chunks = "ten"\n', "[run].max_chunks"),
        ('[run]\nfind_connections = "yes"\n', "[run].find_connections"),
        ('[email]\nenabled = "true"\n', "[email].enabled"),
        ('[bench]\nmodels = "ollama/x"\n', "[bench].models"),
        ('[llm.summarize]\nmodel = "x"\ntemperature = true\n', "[llm.summarize].temperature"),
    ],
)
def test_a_value_of_the_wrong_type_names_the_key_and_what_it_expects(tmp_path, body, expected):
    text = _error(tmp_path, body)
    assert expected in text and "must be" in text and "\n" not in text


def test_a_model_section_without_a_model_and_a_table_that_is_not_one_are_named(tmp_path):
    assert "[llm.ask]" in _error(tmp_path, "[llm.ask]\nnum_ctx = 1\n")
    assert "[llm]" in _error(tmp_path, '[llm]\nmodel = "x"\n')


def test_a_whole_number_is_fine_where_a_decimal_is_expected(tmp_path):
    cfg = load_config(write(tmp_path, '[llm.summarize]\nmodel = "x"\ntimeout_seconds = 60\n'))
    assert cfg.llm["summarize"].timeout_seconds == 60


@pytest.fixture
def fresh_notices(monkeypatch):
    from esbi_cli import config as config_module

    monkeypatch.setattr(config_module, "_noticed", set())


def test_the_old_timeout_key_still_works_and_says_it_was_renamed_once(
    tmp_path, capsys, fresh_notices
):
    body = '[llm.summarize]\nmodel = "x"\ntimeout = 45\n'
    assert load_config(write(tmp_path, body)).llm["summarize"].timeout_seconds == 45
    load_config(write(tmp_path, body))  # the second read of the same section stays quiet
    assert capsys.readouterr().err == "notice: [llm.summarize] timeout is now timeout_seconds\n"


def test_each_section_with_the_old_key_is_named(tmp_path, capsys, fresh_notices):
    body = '[llm.summarize]\nmodel = "x"\ntimeout = 1\n[llm.ask]\nmodel = "x"\ntimeout = 2\n'
    load_config(write(tmp_path, body))
    err = capsys.readouterr().err
    assert "[llm.summarize] timeout" in err and "[llm.ask] timeout" in err


def test_timeout_seconds_wins_when_both_keys_are_present(tmp_path, capsys, fresh_notices):
    body = '[llm.summarize]\nmodel = "x"\ntimeout = 45\ntimeout_seconds = 90\n'
    assert load_config(write(tmp_path, body)).llm["summarize"].timeout_seconds == 90


def test_an_unknown_section_is_rejected_without_echoing_a_notice_for_it(
    tmp_path, capsys, fresh_notices
):
    _error(tmp_path, '[llm.evil]\nmodel = "x"\ntimeout = 1\n')
    assert capsys.readouterr().err == ""


def test_a_retired_section_with_the_old_key_still_loads(tmp_path, fresh_notices):
    assert load_config(write(tmp_path, '[llm.lint]\nmodel = "x"\ntimeout = 1\n'))


def test_the_new_key_prints_no_notice(tmp_path, capsys, fresh_notices):
    load_config(write(tmp_path, '[llm.summarize]\nmodel = "x"\ntimeout_seconds = 45\n'))
    assert capsys.readouterr().err == ""


def test_a_typo_next_to_the_renamed_key_still_gets_the_did_you_mean(tmp_path, fresh_notices):
    text = _error(tmp_path, '[llm.summarize]\nmodel = "x"\ntimeout_secods = 5\n')
    assert "unknown key 'timeout_secods'" in text and "did you mean 'timeout_seconds'" in text


def test_the_old_key_is_still_type_checked(tmp_path, fresh_notices):
    text = _error(tmp_path, '[llm.summarize]\nmodel = "x"\ntimeout = "fast"\n')
    assert "must be a number" in text


def test_a_config_file_named_explicitly_that_does_not_exist_is_an_error_not_a_fallback(
    tmp_path, monkeypatch
):
    from esbi_cli import config as config_module

    fallback = tmp_path / "fallback.toml"
    fallback.write_text("x")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATHS", (fallback,))
    monkeypatch.delenv("ESBI_CONFIG", raising=False)
    missing = tmp_path / "typo.toml"

    with pytest.raises(FileNotFoundError, match=f"config file not found: {missing}"):
        config_module.find_config(missing)
    monkeypatch.setenv("ESBI_CONFIG", str(missing))
    with pytest.raises(FileNotFoundError, match=f"config file not found: {missing}"):
        config_module.find_config()


def test_a_key_that_early_versions_wrote_and_never_used_is_still_accepted(tmp_path):
    """`sb init` of the first versions wrote [run].daily_cost_cap_usd, which nothing ever read:
    refusing it would stop the nightly run of every config made back then."""
    cfg = load_config(write(tmp_path, "[run]\ndaily_cost_cap_usd = 2.0\nmax_chunks = 3\n"))

    assert cfg.max_chunks == 3
    with pytest.raises(ValueError, match="daily_cost_cap_usd"):  # only in [run]
        load_config(write(tmp_path, "[notes]\ndaily_cost_cap_usd = 2.0\n"))


def test_the_model_sections_that_early_versions_wrote_for_tasks_that_never_existed_are_accepted(
    tmp_path,
):
    cfg = load_config(
        write(tmp_path, '[llm.link]\nmodel = "ollama/x"\n[llm.lint]\nmodel = "ollama/y"\n')
    )

    assert set(cfg.llm) == {"link", "lint"}
    with pytest.raises(ValueError, match=r"unknown section \[llm.lnk\]"):
        load_config(write(tmp_path, '[llm.lnk]\nmodel = "ollama/x"\n'))


def test_the_environment_proxy_is_off_unless_the_config_turns_it_on(tmp_path, monkeypatch):
    from esbi_cli import netguard

    monkeypatch.setattr(netguard, "use_environment_proxy", False)
    assert load_config(write(tmp_path)).network.use_environment_proxy is False
    assert netguard.use_environment_proxy is False

    on = load_config(write(tmp_path, "[network]\nuse_environment_proxy = true\n"))

    assert on.network.use_environment_proxy is True
    assert netguard.use_environment_proxy is True  # the guard follows the config that was loaded


def test_the_network_section_refuses_unknown_keys_and_wrong_types(tmp_path):
    with pytest.raises(ValueError, match=r"\[network\] has an unknown key 'use_proxy'"):
        load_config(write(tmp_path, "[network]\nuse_proxy = true\n"))
    with pytest.raises(
        ValueError, match=r"\[network\].use_environment_proxy must be true or false"
    ):
        load_config(write(tmp_path, '[network]\nuse_environment_proxy = "yes"\n'))
    with pytest.raises(ValueError, match=r"\[network\] must be a table"):
        bad = tmp_path / "bad.toml"
        bad.write_text(f'network = true\n[paths]\nvault = "{tmp_path}"\n')
        load_config(bad)


def test_a_proxy_is_never_trusted_after_a_config_that_did_not_ask_for_it(tmp_path, monkeypatch):
    from esbi_cli import config as config_module
    from esbi_cli import netguard

    monkeypatch.setattr(netguard, "use_environment_proxy", False)
    load_config(write(tmp_path, "[network]\nuse_environment_proxy = true\n"))

    config_module.reset_loaded()  # what every command invocation starts with

    assert netguard.use_environment_proxy is False


def test_following_links_in_mail_is_off_by_default_and_capped_between_one_and_ten(tmp_path):
    default = load_config(write(tmp_path)).email
    assert (default.follow_links, default.follow_links_max) == (False, 3)
    on = load_config(write(tmp_path, "[email]\nfollow_links = true\nfollow_links_max = 10\n")).email
    assert (on.follow_links, on.follow_links_max) == (True, 10)
    for bad in (0, 11):
        assert "follow_links_max" in _error(tmp_path, f"[email]\nfollow_links_max = {bad}\n")
    assert "[email].follow_links" in _error(tmp_path, '[email]\nfollow_links = "yes"\n')


def test_the_ocr_section_can_be_switched_off_without_losing_the_model_choice(tmp_path):
    model = 'model = "ollama/qwen3-vl:2b-instruct"\n'
    absent = load_config(write(tmp_path))
    on = load_config(write(tmp_path, f"[llm.ocr]\n{model}"))
    off = load_config(write(tmp_path, f"[llm.ocr]\n{model}enabled = false\n"))

    assert (absent.ocr_on, on.ocr_on, off.ocr_on) == (False, True, False)
    assert off.llm["ocr"].model == "ollama/qwen3-vl:2b-instruct"


def test_enabled_belongs_to_the_ocr_section_only(tmp_path):
    with pytest.raises(ValueError, match=r"\[llm.summarize\].*enabled"):
        load_config(write(tmp_path, '[llm.summarize]\nmodel = "ollama/x"\nenabled = false\n'))
