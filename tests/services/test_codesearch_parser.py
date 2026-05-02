from __future__ import annotations

from pathlib import Path

from app.services.codesearch import parser
from app.services.codesearch.languages import detect_language
from app.services.codesearch.parser import parse_file, parse_snapshot


def test_detect_language_maps_supported_extensions() -> None:
    assert detect_language(Path("module.py")) == "python"
    assert detect_language(Path("module.ts")) == "typescript"
    assert detect_language(Path("module.js")) == "javascript"
    assert detect_language(Path("module.go")) == "go"
    assert detect_language(Path("module.rs")) == "rust"
    assert detect_language(Path("module.java")) == "java"
    assert detect_language(Path("module.txt")) is None


def test_parse_file_builds_python_ir(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text(
        "\n".join(
            [
                "import os",
                "from pkg import alpha, beta",
                "",
                "class Greeter:",
                "    def hello(self):",
                "        return os.getcwd()",
                "",
                "def top_level():",
                "    return 42",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = parse_file(path)

    assert result is not None
    assert result.path == str(path)
    assert result.language == "python"
    assert result.lines[0] == "import os"

    assert {(symbol.name, symbol.kind) for symbol in result.symbols} == {
        ("Greeter", "class"),
        ("hello", "method"),
        ("top_level", "function"),
    }
    assert {(scope.name, scope.kind) for scope in result.scopes} == {
        ("Greeter", "class"),
        ("hello", "method"),
        ("top_level", "function"),
    }
    assert {(item.module, tuple(item.names), item.line) for item in result.imports} == {
        ("os", (), 1),
        ("pkg", ("alpha", "beta"), 2),
    }


def test_parse_file_skips_large_direct_input(tmp_path: Path) -> None:
    path = tmp_path / "large.py"
    path.write_text("#" * (parser.MAX_FILE_SIZE_BYTES + 1), encoding="utf-8")

    assert parse_file(path) is None


def test_parse_file_skips_when_parser_cannot_load(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = tmp_path / "sample.py"
    path.write_text("def run():\n    return 1\n", encoding="utf-8")

    def fail_get_parser(language: str):
        raise RuntimeError(f"no grammar for {language}")

    monkeypatch.setattr(parser, "get_parser", fail_get_parser)

    assert parse_file(path) is None


def test_parse_file_extracts_typescript_type_imports(tmp_path: Path) -> None:
    path = tmp_path / "sample.ts"
    path.write_text(
        "\n".join(
            [
                'import type { Foo } from "./types";',
                'import type Bar from "./bar";',
                'import { type Baz, Quux as Renamed } from "./mixed";',
            ]
        ),
        encoding="utf-8",
    )

    result = parse_file(path)

    assert result is not None
    assert {(item.module, tuple(item.names), item.line) for item in result.imports} == {
        ("./types", ("Foo",), 1),
        ("./bar", ("Bar",), 2),
        ("./mixed", ("Baz", "Quux"), 3),
    }


def test_parse_file_extracts_go_imports_without_fake_aliases(tmp_path: Path) -> None:
    path = tmp_path / "main.go"
    path.write_text(
        "\n".join(
            [
                'import "fmt"',
                'import alias "example.com/pkg"',
                "import (",
                '    "os"',
                '    nethttp "net/http"',
                ")",
            ]
        ),
        encoding="utf-8",
    )

    result = parse_file(path)

    assert result is not None
    assert {(item.module, tuple(item.names), item.line) for item in result.imports} == {
        ("fmt", (), 1),
        ("example.com/pkg", ("alias",), 2),
        ("os", (), 4),
        ("net/http", ("nethttp",), 5),
    }


def test_parse_snapshot_skips_generated_binary_and_vendor_files(
    tmp_path: Path,
) -> None:
    supported = tmp_path / "src" / "main.py"
    supported.parent.mkdir(parents=True)
    supported.write_text("def run():\n    return 1\n", encoding="utf-8")

    skipped_vendor = tmp_path / "vendor" / "lib.py"
    skipped_vendor.parent.mkdir(parents=True)
    skipped_vendor.write_text("def vendor():\n    return 1\n", encoding="utf-8")

    skipped_minified = tmp_path / "web" / "bundle.min.js"
    skipped_minified.parent.mkdir(parents=True)
    skipped_minified.write_text("function x(){}", encoding="utf-8")

    skipped_generated = tmp_path / "api_pb2.py"
    skipped_generated.write_text("def generated():\n    return 1\n", encoding="utf-8")

    skipped_binary = tmp_path / "bin" / "payload.py"
    skipped_binary.parent.mkdir(parents=True)
    skipped_binary.write_bytes(b"\x00\x01\x02")

    large_file = tmp_path / "large.py"
    large_file.write_text("#" * (500 * 1024 + 1), encoding="utf-8")

    results = parse_snapshot(tmp_path)

    assert [item.path for item in results] == [str(supported)]
