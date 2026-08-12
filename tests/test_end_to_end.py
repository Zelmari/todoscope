"""End-to-end tests: full CLI flow on a fixture repository (MS-10)."""

from __future__ import annotations

import subprocess
import sys

from todoscope.ai import AnalysisItem, AnalysisResult
from todoscope.cli import main


def build_fixture(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".gitignore").write_text(".env\nnode_modules/\ngenerated/\n")
    (tmp_path / ".env").write_text("TODOSCOPE_API_KEY=sk-fixture\n")
    (tmp_path / ".todoscope.json").write_text(
        '{"markers": ["TODO", "FIXME"], "exclude": ["legacy/"], "model": "m"}'
    )
    (tmp_path / "main.py").write_text(
        '# TODO: fix main flow\nmessage = "# TODO: not a comment"\n'
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.js").write_text(
        "// FIXME: repair this\nconst t = `// TODO: template, not a comment`;\n"
    )
    (tmp_path / "src" / "deep").mkdir()
    (tmp_path / "src" / "deep" / "util.rs").write_text(
        '// TODO: replace this\nlet x = r#"// TODO: raw, not a comment"#;\n'
    )
    (tmp_path / "legacy").mkdir()
    (tmp_path / "legacy" / "old.py").write_text("# TODO: excluded\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.py").write_text("# TODO: ignored\n")
    (tmp_path / "notes.md").write_text("# TODO: docs are not scanned\n")
    return tmp_path


def test_end_to_end_local_scan_obeys_all_rules(tmp_path, capsys) -> None:
    root = build_fixture(tmp_path)
    result = main([str(root), "--no-ai"])
    captured = capsys.readouterr()
    assert result == 0
    assert "Scanned 3 files in '" in captured.out
    assert "and found 3 TODO, FIXME comments." in captured.out
    assert "1. main.py:1" in captured.out
    assert "2. src/app.js:1" in captured.out
    assert "3. src/deep/util.rs:1" in captured.out
    for missing in ("legacy/old.py", "node_modules", "notes.md", "not a comment"):
        assert missing not in captured.out
    assert "AI analysis skipped: --no-ai was used." in captured.out


def test_end_to_end_ai_merge(tmp_path, monkeypatch, capsys) -> None:
    root = build_fixture(tmp_path)
    monkeypatch.setenv("TODOSCOPE_API_KEY", "sk-e2e")

    def fake_analyze(items, model, api_key, **kwargs):
        by_id = {
            item["id"]: AnalysisItem(
                id=item["id"],
                interpretation=f"Interpret {item['text']}.",
                priority="Medium",
            )
            for item in items
        }
        return AnalysisResult(
            items=tuple(by_id[i] for i in sorted(by_id)),
            overview="Three maintenance comments.",
        )

    monkeypatch.setattr("todoscope.openai_client.analyze", fake_analyze)
    result = main([str(root)])
    captured = capsys.readouterr()
    assert result == 0
    assert "AI interpretation: Interpret fix main flow." in captured.out
    assert "Overall AI summary" in captured.out
    assert "Three maintenance comments." in captured.out
    assert "Priorities are estimated from comment text only." in captured.out
    assert "No source code was provided to the AI." in captured.out
    assert "sk-e2e" not in captured.out


def test_end_to_end_quiet_output(tmp_path, capsys) -> None:
    root = build_fixture(tmp_path)
    result = main([str(root), "--quiet"])
    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == (
        "main.py:1: TODO: fix main flow\n"
        "src/app.js:1: FIXME: repair this\n"
        "src/deep/util.rs:1: TODO: replace this\n"
    )


def test_installed_module_scan_smoke(tmp_path) -> None:
    root = build_fixture(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "todoscope", str(root), "--no-ai"],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert "and found 3 TODO, FIXME comments." in result.stdout
