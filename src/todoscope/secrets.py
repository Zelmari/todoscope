"""Secret detection inside comment text (MS-22).

Comment text is untrusted data and the only repository-derived content that
may cross the AI payload boundary. Before any payload is built, findings are
screened against a deterministic list of high-signal credential shapes so a
key or token can never leave the machine. Detection is conservative: it
flags unambiguous secret formats (long random-looking prefixes, private-key
headers, credential assignments) and never prose.
"""

from __future__ import annotations

import re

from todoscope.scan import IndexedFinding

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "openai-style-api-key",
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "aws-access-key-id",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "aws-credential-assignment",
        re.compile(
            r"(?i)\baws[_-]?(?:secret[_-]?access[_-]?key|access[_-]?key[_-]?id)\b"
            r"\s*[:=]\s*[\"'][^\"']{12,}[\"']"
        ),
    ),
    (
        "private-key-header",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----"),
    ),
    (
        "github-token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    ),
    (
        "github-fine-grained-pat",
        re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    ),
    (
        "stripe-live-key",
        re.compile(r"\b(?:sk|rk)_live_[0-9A-Za-z]{24,}\b"),
    ),
    (
        "slack-token",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ),
    (
        "sendgrid-api-key",
        re.compile(r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b"),
    ),
    (
        "google-api-key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ),
    (
        "jwt-token",
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
    ),
    (
        "bearer-token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}\b"),
    ),
    (
        "credential-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|"
            r"refresh[_-]?token|token|secret|password|passwd|pwd|credential)s?\b"
            r"\s*[:=]\s*[\"'][^\"']{12,}[\"']"
        ),
    ),
)


def secret_matches(text: str) -> tuple[str, ...]:
    """Names of the credential rules matching ``text``, in rule order."""
    return tuple(name for name, pattern in _RULES if pattern.search(text))


def findings_with_secrets(
    findings: tuple[IndexedFinding, ...],
) -> tuple[IndexedFinding, ...]:
    """Findings whose comment text matches at least one credential rule."""
    return tuple(
        indexed for indexed in findings if secret_matches(indexed.finding.text)
    )


def secret_entries(
    findings: tuple[IndexedFinding, ...],
) -> tuple[tuple[IndexedFinding, tuple[str, ...]], ...]:
    """Pairs of finding and matching rule names, in finding order."""
    return tuple(
        (indexed, secret_matches(indexed.finding.text))
        for indexed in findings
        if secret_matches(indexed.finding.text)
    )
