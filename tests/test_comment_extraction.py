"""Language-aware comment extraction (MS-2 feasibility proof)."""

from __future__ import annotations

from todoscope.parsing.comments import (
    Language,
    extract_comments,
    extract_python_comments,
)

PYTHON_PROOF = '''# TODO: real comment
message = "# TODO: string, not a comment"
text = """
# TODO: multiline string, not a comment
"""
r = r"# TODO: raw string, not a comment"
f = f"# TODO: f-string, not a comment"
'''

JAVASCRIPT_PROOF = """// TODO: real comment
const text = "// TODO: string, not a comment";
const template = `// TODO: template text, not a comment`;
"""

RUST_PROOF = """// TODO: real comment
let text = r#"// TODO: raw string, not a comment"#;
"""


def test_python_finds_only_real_comments() -> None:
    comments = extract_python_comments(PYTHON_PROOF)
    assert [c.text for c in comments] == ["# TODO: real comment"]
    assert comments[0].start_line == 1
    assert comments[0].kind == "line"


def test_javascript_finds_only_real_comments() -> None:
    comments = extract_comments(JAVASCRIPT_PROOF, Language.JAVASCRIPT)
    assert [c.text for c in comments] == ["// TODO: real comment"]
    assert comments[0].start_line == 1
    assert comments[0].kind == "line"


def test_rust_finds_only_real_comments() -> None:
    comments = extract_comments(RUST_PROOF, Language.RUST)
    assert [c.text for c in comments] == ["// TODO: real comment"]
    assert comments[0].start_line == 1
    assert comments[0].kind == "line"


def test_typescript() -> None:
    source = """// TODO: ts line
const x: string = "// TODO: not a comment";
const t = `tpl // TODO: not a comment`;
/* TODO: ts block */
"""
    comments = extract_comments(source, Language.TYPESCRIPT)
    assert [c.text for c in comments] == [
        "// TODO: ts line",
        "/* TODO: ts block */",
    ]


def test_tsx_ignores_jsx_text_and_attributes() -> None:
    source = """// TODO: tsx line
const x: string = "// TODO: not a comment";
const el = <div>{/* TODO: jsx block */}
  <span title="// TODO: attr string">text // TODO: jsx text</span>
</div>;
/* TODO: tsx block */
"""
    comments = extract_comments(source, Language.TSX)
    assert [c.text for c in comments] == [
        "// TODO: tsx line",
        "/* TODO: jsx block */",
        "/* TODO: tsx block */",
    ]


def test_js_template_literals_with_nesting() -> None:
    source = "// TODO: real\nconst nested = `${`inner // TODO: not a comment`}`;\n"
    comments = extract_comments(source, Language.JAVASCRIPT)
    assert [c.text for c in comments] == ["// TODO: real"]


def test_block_comment_lines_and_decoration_are_preserved() -> None:
    source = """/*
 * TODO: replace this temporary cache
 * when persistent storage is available
 */
"""
    comments = extract_comments(source, Language.JAVASCRIPT)
    assert len(comments) == 1
    comment = comments[0]
    assert comment.kind == "block"
    assert comment.start_line == 1
    assert comment.end_line == 4
    assert "TODO" in comment.text
    assert " * TODO" in comment.text


def test_rust_doc_comments_are_real_comments() -> None:
    source = "/// TODO: doc comment\n//! TODO: inner doc\nlet x = 1;\n"
    comments = extract_comments(source, Language.RUST)
    assert [c.text for c in comments] == [
        "/// TODO: doc comment",
        "//! TODO: inner doc",
    ]


def test_rust_multihash_raw_strings() -> None:
    source = 'let a = r##"// TODO: not a comment"##;\n// TODO: real\n'
    comments = extract_comments(source, Language.RUST)
    assert [c.text for c in comments] == ["// TODO: real"]


def test_broken_python_file_does_not_crash_and_is_conservative() -> None:
    source = '# TODO: before\nx = """unterminated\n# TODO: inside broken string\n'
    comments = extract_python_comments(source)
    assert [c.text for c in comments] == ["# TODO: before"]


def test_broken_javascript_file_does_not_crash() -> None:
    source = 'function f() { // TODO: still found\n const x = "unterminated;\n'
    comments = extract_comments(source, Language.JAVASCRIPT)
    assert any("TODO" in c.text for c in comments)


def test_non_utf8_source_does_not_crash() -> None:
    comments = extract_comments("# TODO: caf\xe9\n", Language.PYTHON)
    assert comments[0].text.startswith("# TODO")
