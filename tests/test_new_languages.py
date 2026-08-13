"""New-language extraction tests: Java, Go, C, C++, C# (MS-15)."""

from __future__ import annotations

import pytest

from todoscope.extraction import findings_for_file


def check(tmp_path, filename: str, content: str) -> list:
    path = tmp_path / filename
    path.write_text(content)
    return findings_for_file(path, tmp_path, ("TODO",))


def test_java_strings_and_text_blocks(tmp_path) -> None:
    source = (
        "// TODO: real line\n"
        'String s = "// TODO: not a comment";\n'
        "/* TODO: real block */\n"
        'String t = """\n// TODO: not a comment\n""";\n'
        "char c = '/';\n"
    )
    findings = check(tmp_path, "a.java", source)
    assert [(f.text, f.line) for f in findings] == [("real line", 1), ("real block", 3)]


def test_go_raw_strings_and_runes(tmp_path) -> None:
    source = (
        "// TODO: real line\n"
        's := "// TODO: not a comment"\n'
        "r := `// TODO: not a comment`\n"
        "c := '/'\n"
        "/* TODO: real block */\n"
    )
    findings = check(tmp_path, "a.go", source)
    assert [(f.text, f.line) for f in findings] == [("real line", 1), ("real block", 5)]


def test_c_preprocessor_lines_and_chars(tmp_path) -> None:
    source = (
        "// TODO: real line\n"
        '#define MSG "// TODO: not a comment"\n'
        "char c = '/';\n"
        "/* TODO: real block */\n"
    )
    findings = check(tmp_path, "a.c", source)
    assert [(f.text, f.line) for f in findings] == [("real line", 1), ("real block", 4)]


def test_cpp_raw_strings(tmp_path) -> None:
    source = (
        "// TODO: real line\n"
        'R"(// TODO: not a comment)"\n'
        'R"delim(/* TODO: also not a comment */)delim"\n'
        "/* TODO: real block */\n"
    )
    findings = check(tmp_path, "a.cpp", source)
    assert [(f.text, f.line) for f in findings] == [("real line", 1), ("real block", 4)]


def test_csharp_verbatim_strings(tmp_path) -> None:
    source = (
        "// TODO: real line\n"
        'var s = "// TODO: not a comment";\n'
        'var v = @"// TODO: not a comment";\n'
        'var i = $@"// TODO: not a comment";\n'
        "/* TODO: real block */\n"
    )
    findings = check(tmp_path, "a.cs", source)
    assert [(f.text, f.line) for f in findings] == [("real line", 1), ("real block", 5)]


@pytest.mark.parametrize(
    ("filename", "line", "expected"),
    [
        ("a.java", 1, "java"),
        ("a.go", 1, "go"),
        ("a.c", 1, "c"),
        ("a.h", 1, "c"),
        ("a.cpp", 1, "cpp"),
        ("a.cc", 1, "cpp"),
        ("a.cxx", 1, "cpp"),
        ("a.hpp", 1, "cpp"),
        ("a.cs", 1, "cs"),
    ],
)
def test_extension_mapping(tmp_path, filename, line, expected) -> None:
    source = f"// TODO: {expected}\n"
    findings = check(tmp_path, filename, source)
    assert [(f.text, f.line) for f in findings] == [(expected, line)]


def test_new_extensions_are_configurable(tmp_path) -> None:
    from todoscope.config import load_config

    (tmp_path / ".todoscope.json").write_text('{"extensions": [".java", ".go", ".cs"]}')
    config = load_config(tmp_path)
    assert config.extensions == (".java", ".go", ".cs")
