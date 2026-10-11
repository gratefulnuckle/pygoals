import os

from brightcove import policy_key
from pygoals import build_parser, main


def test_parser_flags():
    args = build_parser().parse_args(["--dry-run", "--quiet", "--device", "Kitchen", "--poll-seconds", "5"])
    assert args.dry_run
    assert args.quiet
    assert args.device == "Kitchen"
    assert args.poll_seconds == 5.0


def test_policy_key_from_env(monkeypatch):
    monkeypatch.delenv("BRIGHTCOVE_PK", raising=False)
    assert policy_key() == ""
    monkeypatch.setenv("BRIGHTCOVE_PK", "test-key")
    assert policy_key() == "test-key"


def test_missing_pk_without_dry_run_exits_2(monkeypatch):
    monkeypatch.delenv("BRIGHTCOVE_PK", raising=False)
    assert main(["--quiet"]) == 2
