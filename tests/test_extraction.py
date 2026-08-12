"""Comment normalisation, marker matching, and finding tests (MS-5)."""

from __future__ import annotations

from todoscope.extraction import (
    Finding,
    findings_for_comments,
    findings_for_file,
    marker_prefix,
    normalise_block_comment,
    normalise_line_comment,
    strip_marker,
)
from todoscope.parsing.comments import Language, extract_comments

TODO = ("TODO",)


def findings(
    source: str, language: Language, markers: tuple[str, ...] = TODO
) -> list[Finding]:
    return findings_for_comments(
        extract_comments(source, language), language, markers, "file.ext"
    )


def test_finds_uppercase_todo() -> None:
    result = findings("# TODO: handle expired tokens\n", Language.PYTHON)
    assert result == [Finding("TODO", "handle expired tokens", "file.ext", 1)]


def test_does_not_find_lowercase_todo() -> None:
    assert findings("# todo: handle expired tokens\n", Language.PYTHON) == []
    assert findings("# Todo: handle expired tokens\n", Language.PYTHON) == []


def test_strips_delimiter_and_leading_whitespace() -> None:
    result = findings("#     TODO: fix this\n", Language.PYTHON)
    assert result[0].text == "fix this"


def test_prefix_matching_variants() -> None:
    assert findings("# TODO\n", Language.PYTHON)[0].marker == "TODO"
    assert findings("# TODOtesting\n", Language.PYTHON)[0].text == "testing"
    assert findings("# TODO(zelmari)\n", Language.PYTHON)[0].text == "(zelmari)"
    assert findings("# TODOLIST\n", Language.PYTHON)[0].text == "LIST"


def test_prefix_matching_negatives() -> None:
    assert findings("# Something TODO\n", Language.PYTHON) == []
    assert findings("# MYTODO\n", Language.PYTHON) == []


def test_longest_matching_marker_wins() -> None:
    result = findings(
        "# TODOFIX: repair authentication\n", Language.PYTHON, ("TODO", "TODOFIX")
    )
    assert result == [Finding("TODOFIX", "repair authentication", "file.ext", 1)]


def test_markers_inside_strings_are_ignored() -> None:
    source = (
        "# TODO: real\n"
        'message = "# TODO: not a comment"\n'
        'text = """\n# TODO: not a comment\n"""\n'
    )
    result = findings(source, Language.PYTHON)
    assert len(result) == 1
    assert result[0].line == 1


def test_js_strings_and_templates_ignored() -> None:
    source = (
        "// TODO: real\n"
        'const a = "// TODO: not a comment";\n'
        "const t = `// TODO: not a comment`;\n"
    )
    result = findings(source, Language.JAVASCRIPT)
    assert len(result) == 1
    assert result[0].line == 1


def test_rust_raw_strings_ignored() -> None:
    source = '// TODO: real\nlet a = r#"// TODO: not a comment"#;\n'
    result = findings(source, Language.RUST)
    assert len(result) == 1


def test_adjacent_continuation_lines_combine() -> None:
    source = (
        "# TODO: replace the temporary cache\n# once persistent storage is available\n"
    )
    result = findings(source, Language.PYTHON)
    assert result == [
        Finding(
            "TODO",
            "replace the temporary cache once persistent storage is available",
            "file.ext",
            1,
        )
    ]


def test_adjacent_marker_lines_start_new_findings() -> None:
    source = "# TODO: replace the cache\n# TODO: add cache expiry\n"
    result = findings(source, Language.PYTHON)
    assert [f.text for f in result] == ["replace the cache", "add cache expiry"]
    assert [f.line for f in result] == [1, 2]


def test_blank_line_ends_finding() -> None:
    source = "# TODO: first\n\n# continuation, not adjacent\n"
    result = findings(source, Language.PYTHON)
    assert len(result) == 1
    assert result[0].text == "first"


def test_code_between_comments_ends_finding() -> None:
    source = "# TODO: first\nx = 1\n# continuation\n"
    result = findings(source, Language.PYTHON)
    assert len(result) == 1


def test_empty_todo_is_included() -> None:
    result = findings("# TODO\n", Language.PYTHON)
    assert result == [Finding("TODO", "", "file.ext", 1)]


def test_vague_todo_text_is_preserved() -> None:
    result = findings("# TODO: fix this\n", Language.PYTHON)
    assert result[0].text == "fix this"


def test_block_comment_lines_are_combined() -> None:
    source = (
        "/*\n"
        " * TODO: replace this temporary cache\n"
        " * when persistent storage is available\n"
        " */\n"
    )
    result = findings(source, Language.JAVASCRIPT)
    assert result == [
        Finding(
            "TODO",
            "replace this temporary cache when persistent storage is available",
            "file.ext",
            1,
        )
    ]


def test_single_line_block_comment() -> None:
    result = findings("/* TODO: fix me */\n", Language.JAVASCRIPT)
    assert result == [Finding("TODO", "fix me", "file.ext", 1)]


def test_block_comment_without_leading_marker_is_ignored() -> None:
    source = "/*\n * description\n * TODO: buried marker\n */\n"
    assert findings(source, Language.JAVASCRIPT) == []


def test_block_and_line_comments_are_separate_findings() -> None:
    source = "/* TODO: block */\n// TODO: line\n"
    result = findings(source, Language.JAVASCRIPT)
    assert [(f.text, f.line) for f in result] == [("block", 1), ("line", 2)]


def test_rust_doc_comments_match() -> None:
    result = findings("/// TODO: doc comment\n//! TODO: inner doc\n", Language.RUST)
    assert [f.text for f in result] == ["doc comment", "inner doc"]
    assert [f.line for f in result] == [1, 2]


def test_multiple_configured_markers() -> None:
    source = "# TODO: first\n# FIXME: second\n# HELP: third\n"
    markers = ("TODO", "FIXME", "HELP", "LATER")
    result = findings(source, Language.PYTHON, markers)
    assert [(f.marker, f.text) for f in result] == [
        ("TODO", "first"),
        ("FIXME", "second"),
        ("HELP", "third"),
    ]


def test_continuation_line_with_other_marker_starts_new_finding() -> None:
    source = "# TODO: first\n# FIXME: adjacent but new\n"
    result = findings(source, Language.PYTHON, ("TODO", "FIXME"))
    assert [f.text for f in result] == ["first", "adjacent but new"]


def test_marker_prefix_helpers() -> None:
    assert marker_prefix("TODO: x", ("TODO", "TODOFIX")) == "TODO"
    assert marker_prefix("TODOFIX: x", ("TODO", "TODOFIX")) == "TODOFIX"
    assert marker_prefix("todo: x", ("TODO",)) is None
    assert strip_marker("TODO: fix", "TODO") == "fix"
    assert strip_marker("TODO fix", "TODO") == "fix"
    assert strip_marker("TODO", "TODO") == ""


def test_normalise_line_comment_strips_decorators() -> None:
    assert normalise_line_comment(Language.PYTHON, "#   TODO: x") == "TODO: x"
    assert normalise_line_comment(Language.RUST, "// TODO: x") == "TODO: x"
    assert normalise_line_comment(Language.RUST, "/// TODO: x") == "TODO: x"
    assert normalise_line_comment(Language.RUST, "//! TODO: x") == "TODO: x"
    assert normalise_line_comment(Language.JAVASCRIPT, "//TODO: x") == "TODO: x"


def test_normalise_block_comment_strips_decoration() -> None:
    raw = "/*\n * TODO: a\n *\n * b\n */"
    assert normalise_block_comment(raw) == "TODO: a b"


def test_findings_for_file_uses_extension_language(tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("# TODO: py\n")
    (tmp_path / "src" / "b.js").write_text("// TODO: js\n")
    (tmp_path / "src" / "c.rs").write_text("// TODO: rs\n")
    result = []
    for name in ("a.py", "b.js", "c.rs"):
        result.extend(findings_for_file(tmp_path / "src" / name, tmp_path, ("TODO",)))
    assert [(f.path, f.text) for f in result] == [
        ("src/a.py", "py"),
        ("src/b.js", "js"),
        ("src/c.rs", "rs"),
    ]


def test_findings_for_file_unsupported_extension_returns_empty(tmp_path) -> None:
    (tmp_path / "notes.md").write_text("# TODO: md\n")
    assert findings_for_file(tmp_path / "notes.md", tmp_path, ("TODO",)) == []
