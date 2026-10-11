"""Team colors and ESPN logo slugs. Unknown teams get a default theme."""

DEFAULT = {"primary": "#041E42", "secondary": "#8E8E90", "espn": "nhl"}

THEMES = {
    "ANA": {"primary": "#F95602", "secondary": "#111111", "espn": "ana"},
    "ARI": {"primary": "#8C2633", "secondary": "#E2D6B5", "espn": "ari"},
    "BOS": {"primary": "#111111", "secondary": "#FCB514", "espn": "bos"},
    "BUF": {"primary": "#002654", "secondary": "#FCB514", "espn": "buf"},
    "CGY": {"primary": "#B72B35", "secondary": "#F1BE48", "espn": "cgy"},
    "CAR": {"primary": "#B72B35", "secondary": "#111111", "espn": "car"},
    "CHI": {"primary": "#CF0A2C", "secondary": "#111111", "espn": "chi"},
    "COL": {"primary": "#6F263D", "secondary": "#236192", "espn": "col"},
    "CBJ": {"primary": "#002654", "secondary": "#CE1126", "espn": "cbj"},
    "DAL": {"primary": "#006847", "secondary": "#8F8F8C", "espn": "dal"},
    "DET": {"primary": "#CE1126", "secondary": "#FFFFFF", "espn": "det"},
    "EDM": {"primary": "#041E41", "secondary": "#FF4C00", "espn": "edm"},
    "FLA": {"primary": "#041E42", "secondary": "#C8102E", "espn": "fla"},
    "LAK": {"primary": "#111111", "secondary": "#A2AAAD", "espn": "la"},
    "MIN": {"primary": "#004F30", "secondary": "#C51230", "espn": "min"},
    "MTL": {"primary": "#C51230", "secondary": "#192168", "espn": "mtl"},
    "NSH": {"primary": "#041E42", "secondary": "#FFB81C", "espn": "nsh"},
    "NJD": {"primary": "#CE1126", "secondary": "#111111", "espn": "nj"},
    "NYI": {"primary": "#00529B", "secondary": "#F47920", "espn": "nyi"},
    "NYR": {"primary": "#0038A8", "secondary": "#CE1126", "espn": "nyr"},
    "OTT": {"primary": "#E31837", "secondary": "#111111", "espn": "ott"},
    "PHI": {"primary": "#F74902", "secondary": "#000000", "espn": "phi"},
    "PIT": {"primary": "#000000", "secondary": "#FCB514", "espn": "pit"},
    "SJS": {"primary": "#006D75", "secondary": "#EA7200", "espn": "sj"},
    "SEA": {"primary": "#001628", "secondary": "#E9072B", "espn": "sea"},
    "STL": {"primary": "#002F87", "secondary": "#FCB514", "espn": "stl"},
    "TBL": {"primary": "#003DA5", "secondary": "#8E8E90", "espn": "tb"},
    "TOR": {"primary": "#00285E", "secondary": "#8E8E90", "espn": "tor"},
    "UTA": {"primary": "#000000", "secondary": "#041E42", "espn": "utah"},
    "VAN": {"primary": "#041E42", "secondary": "#8E8E90", "espn": "van"},
    "VGK": {"primary": "#111111", "secondary": "#8E8E90", "espn": "vgk"},
    "WSH": {"primary": "#CF142B", "secondary": "#8E8E90", "espn": "wsh"},
    "WPG": {"primary": "#041E42", "secondary": "#8E8E90", "espn": "wpg"},
}

_ALIAS = {
    "LA": "LAK",
    "SJ": "SJS",
    "TB": "TBL",
    "UTAH": "UTA",
    "NJ": "NJD",
}


def canonical_team(code):
    if not code:
        return None
    upper = str(code).upper()
    return _ALIAS.get(upper, upper)


def espn_slug(code):
    theme = lookup_theme(code)
    return theme["espn"]


def lookup_theme(code):
    key = canonical_team(code)
    return THEMES.get(key, DEFAULT)
