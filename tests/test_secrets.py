"""Secret detection inside comment text tests (MS-22)."""

from __future__ import annotations

import json

import pytest

from todoscope.ai import AiSkipReason
from todoscope.cli import main
from todoscope.extraction import Finding
from todoscope.scan import IndexedFinding
from todoscope.secrets import findings_with_secrets, secret_matches

POSITIVE_CASES: tuple[tuple[str, str], ...] = (
    (
        "openai-style-api-key",
        "rotate the sk-abcdefghijklmnopqrstuvwxyz01234567 key",
    ),
    ("aws-access-key-id", "set AWS key AKIAIOSFODNN7EXAMPLE"),
    (
        "aws-credential-assignment",
        'aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"',
    ),
    ("private-key-header", "-----BEGIN RSA PRIVATE KEY-----"),
    ("private-key-header", "-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("private-key-header", "-----BEGIN PGP PRIVATE KEY BLOCK-----"),
    ("github-token", "ghp_abcdefghijklmnopqrstuvwxyzABCDEFGH"),
    ("github-fine-grained-pat", "github_pat_abcdefghijklmnopqrstuvwxyz_12345"),
    ("stripe-live-key", "sk_" + "live_" + "abcdefghijklmnopqrstuvwx"),
    ("slack-token", "xoxb-123456789012-1234567890123-abcdefgh"),
    ("sendgrid-api-key", "SG.abcdefghijklmnop.STUVWXYZabcdefghijklmnop"),
    ("google-api-key", "AIzaSyD-abcdefghijklmnopqrstuvwxyz01234"),
    (
        "jwt-token",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
    ),
    ("bearer-token", "use bearer abcdefghijklmnopqrstuvwxyz012345 for the call"),
    ("credential-assignment", "token = 'abcdefghijklmnop'"),
    ("credential-assignment", 'password: "hunter2secret!"'),
)

NEGATIVE_CASES: tuple[str, ...] = (
    "handle expired refresh tokens",
    "update the api key documentation",
    "secretary onboarding notes",
    "short key sk-abc",
    "verify the commit signature",
    "bearer of bad news",
    "access granted",
    "remember to rotate keys quarterly",
    "use a token bucket for rate limiting",
    "credential rotation is due next quarter",
)


@pytest.mark.parametrize(("rule", "text"), POSITIVE_CASES)
def test_rule_matches_its_canonical_example(rule: str, text: str) -> None:
    assert rule in secret_matches(text)


def test_benign_comments_match_nothing() -> None:
    for text in NEGATIVE_CASES:
        assert secret_matches(text) == (), repr(text)


def test_findings_with_secrets_filters_only_matching_findings() -> None:
    findings = (
        IndexedFinding(
            id=1,
            finding=Finding(
                "TODO", "rotate the sk-abcdefghijklmnopqrstuvwxyz01234567", "a.py", 1
            ),
        ),
        IndexedFinding(id=2, finding=Finding("TODO", "clean this up", "b.py", 2)),
        IndexedFinding(
            id=3, finding=Finding("FIXME", "-----BEGIN EC PRIVATE KEY-----", "c.py", 3)
        ),
    )
    flagged = findings_with_secrets(findings)
    assert [indexed.id for indexed in flagged] == [1, 3]


def _write_project(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "# TODO: rotate the sk-abcdefghijklmnopqrstuvwxyz01234567 key\n"
    )
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')


def test_ai_request_is_refused_when_secret_found(tmp_path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-key")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("no AI request may be made")

    monkeypatch.setattr("todoscope.openai_client.analyze", fail_if_called)
    result = main([str(tmp_path / "src"), "--ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "possible credentials were found" in captured.out
    assert "app.py:1: TODO" in captured.out


def test_json_reports_secrets_skip_reason(tmp_path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-key")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("no AI request may be made")

    monkeypatch.setattr("todoscope.openai_client.analyze", fail_if_called)
    result = main([str(tmp_path / "src"), "--ai", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["ai"] == {
        "status": "skipped",
        "reason": AiSkipReason.SECRETS_FOUND.value,
    }


def test_local_scan_is_unaffected_by_secrets(tmp_path, monkeypatch, capsys) -> None:
    _write_project(tmp_path)
    result = main([str(tmp_path / "src")])
    captured = capsys.readouterr()
    assert result == 0
    assert "possible credentials were found" not in captured.out
    assert "1. src/app.py:1: TODO" in captured.out


def _write_clean_project(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "# TODO: clean up\n"
        "# TODO: rotate the sk-abcdefghijklmnopqrstuvwxyz01234567 key\n"
        "# TODO: AWS credentials were rotated, update AKIAIOSFODNN7EXAMPLE\n"
    )


def test_check_secrets_lists_flagged_findings(tmp_path, capsys) -> None:
    _write_clean_project(tmp_path)
    result = main([str(tmp_path / "src"), "--check-secrets"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Possible credentials in comments" in captured.out
    assert "app.py:2: TODO" in captured.out
    assert "openai-style-api-key" in captured.out
    assert "app.py:3: TODO" in captured.out
    assert "aws-access-key-id" in captured.out


def test_check_secrets_without_flag_shows_nothing(tmp_path, capsys) -> None:
    _write_clean_project(tmp_path)
    result = main([str(tmp_path / "src")])
    captured = capsys.readouterr()
    assert result == 0
    assert "Possible credentials in comments" not in captured.out


def test_check_secrets_quiet_conflict(tmp_path, capsys) -> None:
    _write_clean_project(tmp_path)
    result = main([str(tmp_path / "src"), "--quiet", "--check-secrets"])
    captured = capsys.readouterr()
    assert result == 0
    assert "--quiet and --check-secrets cannot be used together." in captured.err
    assert "Possible credentials" not in captured.out


def test_check_secrets_json_shape(tmp_path, capsys) -> None:
    _write_clean_project(tmp_path)
    result = main([str(tmp_path / "src"), "--check-secrets", "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert [entry["line"] for entry in data["secrets"]] == [2, 3]
    assert data["secrets"][0]["rules"] == ["openai-style-api-key"]
    assert data["secrets"][1]["rules"] == ["aws-access-key-id"]


def test_check_secrets_json_null_without_flag(tmp_path, capsys) -> None:
    _write_clean_project(tmp_path)
    result = main([str(tmp_path / "src"), "--format", "json"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    assert data["secrets"] is None


def test_check_secrets_sarif_emits_error_results(tmp_path, capsys) -> None:
    _write_clean_project(tmp_path)
    result = main([str(tmp_path / "src"), "--check-secrets", "--format", "sarif"])
    captured = capsys.readouterr()
    assert result == 0
    data = json.loads(captured.out)
    rules = [rule["id"] for rule in data["runs"][0]["tool"]["driver"]["rules"]]
    assert "credential-in-comment" in rules
    secret_results = [
        r for r in data["runs"][0]["results"] if r["ruleId"] == "credential-in-comment"
    ]
    assert [r["level"] for r in secret_results] == ["error", "error"]
    assert secret_results[0]["properties"]["rules"] == ["openai-style-api-key"]


def test_check_secrets_ai_is_still_refused(tmp_path, monkeypatch, capsys) -> None:
    _write_clean_project(tmp_path)
    (tmp_path / ".todoscope.json").write_text('{"model": "m"}')
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-shell-key")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("no AI request may be made")

    monkeypatch.setattr("todoscope.openai_client.analyze", fail_if_called)
    result = main([str(tmp_path / "src"), "--ai", "--check-secrets"])
    captured = capsys.readouterr()
    assert result == 0
    assert "possible credentials were found" in captured.out
    assert "Possible credentials in comments" in captured.out
