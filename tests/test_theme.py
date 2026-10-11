from team_theme import espn_slug, lookup_theme


def test_abbrev_aliases():
    assert espn_slug("LAK") == "la"
    assert espn_slug("NJD") == "nj"
    assert espn_slug("SJS") == "sj"
    assert espn_slug("TBL") == "tb"
    assert espn_slug("UTA") == "utah"


def test_unknown_team_uses_default_not_keyerror():
    theme = lookup_theme("XYZ")
    assert theme["primary"].startswith("#")
    assert theme["secondary"].startswith("#")


def test_ari_is_historical_but_safe():
    theme = lookup_theme("ARI")
    assert theme["primary"]
