from pathlib import Path

from antsim_ui.config import load_config, validate_config

DEFAULT = Path(__file__).parent.parent / "configs" / "default.json"


def test_default_config_is_valid():
    cfg = load_config(DEFAULT)
    assert len(cfg["species"]) == 3


def test_unknown_key_is_reported():
    problems = validate_config({"bogus": 1, "species": [{}]})
    assert any("unknown" in p for p in problems)


def test_species_count_is_checked():
    assert validate_config({"species": []})
