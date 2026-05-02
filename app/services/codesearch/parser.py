from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from tree_sitter import Node
from tree_sitter_language_pack import get_parser

from app.services.codesearch.languages import detect_language
from app.services.codesearch.models import FileIR, Import, Scope, Symbol

MAX_FILE_SIZE_BYTES = 500 * 1024
SKIP_DIRECTORIES = {"vendor", "node_modules"}
IDENTIFIER_NODE_TYPES = {
    "identifier",
    "field_identifier",
    "property_identifier",
    "type_identifier",
    "package_identifier",
}
CLASS_NODE_TYPES = {
    "class_definition",
    "class_declaration",
    "interface_declaration",
    "record_declaration",
    "struct_item",
    "type_declaration",
}
FUNCTION_NODE_TYPES = {
    "function_definition",
    "function_declaration",
    "function_item",
}
METHOD_NODE_TYPES = {
    "method_definition",
    "method_declaration",
}
VARIABLE_NODE_TYPES = {"variable_declarator"}
SCOPE_KINDS = {"class", "function", "method"}


def parse_file(path: Path) -> FileIR | None:
    """Parse a single source file. Returns ``None`` for unsupported or binary files."""
    language = detect_language(path)
    if language is None:
        return None

    try:
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return None
        source_bytes = path.read_bytes()
    except OSError:
        return None

    if _is_binary(source_bytes):
        return None

    try:
        parser = get_parser(language)
        tree = parser.parse(source_bytes)
    except Exception:
        return None
    lines = source_bytes.decode("utf-8", errors="replace").splitlines()

    symbols: list[Symbol] = []
    scopes: list[Scope] = []
    imports: list[Import] = []

    def walk(node: Node, class_stack: list[str]) -> None:
        symbol = _extract_symbol(node, path, source_bytes, class_stack)
        next_stack = class_stack
        if symbol is not None:
            symbols.append(symbol)
            if symbol.kind in SCOPE_KINDS:
                scopes.append(
                    Scope(
                        name=symbol.name,
                        kind=symbol.kind,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                    )
                )
            if symbol.kind == "class":
                next_stack = [*class_stack, symbol.name]

        parsed_imports = _extract_imports(node, source_bytes, language)
        if parsed_imports:
            imports.extend(parsed_imports)

        for child in node.children:
            walk(child, next_stack)

    walk(tree.root_node, [])

    return FileIR(
        path=str(path),
        language=language,
        symbols=symbols,
        scopes=scopes,
        imports=imports,
        lines=lines,
    )


def parse_snapshot(snapshot_path: Path) -> list[FileIR]:
    """Walk a snapshot tree and parse all supported files that pass skip heuristics."""
    results: list[FileIR] = []
    for path in _iter_files(snapshot_path):
        if _should_skip_file(snapshot_path, path):
            continue
        parsed = parse_file(path)
        if parsed is not None:
            results.append(parsed)
    return results


def _iter_files(snapshot_path: Path) -> Iterator[Path]:
    """Yield files deterministically without materializing the full tree."""
    for root, dirnames, filenames in os.walk(snapshot_path):
        dirnames[:] = sorted(
            dirname for dirname in dirnames if dirname not in SKIP_DIRECTORIES
        )
        for filename in sorted(filenames):
            yield Path(root) / filename


def _should_skip_file(snapshot_path: Path, path: Path) -> bool:
    relative_path = path.relative_to(snapshot_path)
    parts = set(relative_path.parts)
    if parts & SKIP_DIRECTORIES:
        return True
    if path.name.endswith(".min.js") or path.name.endswith("_pb2.py"):
        return True
    try:
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return True
        with path.open("rb") as handle:
            if _is_binary(handle.read(8192)):
                return True
    except OSError:
        return True
    return False


def _is_binary(content: bytes) -> bool:
    return b"\x00" in content[:8192]


def _extract_symbol(
    node: Node,
    path: Path,
    source_bytes: bytes,
    class_stack: list[str],
) -> Symbol | None:
    kind: str | None = None
    if node.type in CLASS_NODE_TYPES:
        kind = "class"
    elif node.type in METHOD_NODE_TYPES:
        kind = "method"
    elif node.type in FUNCTION_NODE_TYPES:
        kind = "method" if class_stack else "function"
    elif node.type in VARIABLE_NODE_TYPES and _is_callable_variable(node):
        kind = "variable"

    if kind is None:
        return None

    name = _extract_name(node, source_bytes)
    if not name:
        return None

    return Symbol(
        name=name,
        kind=kind,
        file=str(path),
        start_line=node.start_point.row + 1,
        end_line=node.end_point.row + 1,
    )


def _extract_name(node: Node, source_bytes: bytes) -> str | None:
    named_child = node.child_by_field_name("name")
    if named_child is not None:
        return _node_text(named_child, source_bytes)

    if node.type == "type_declaration":
        for child in node.children:
            if child.type == "type_spec":
                type_name = child.child_by_field_name("name")
                if type_name is not None:
                    return _node_text(type_name, source_bytes)

    for child in node.children:
        if child.type in IDENTIFIER_NODE_TYPES:
            return _node_text(child, source_bytes)
    return None


def _extract_imports(node: Node, source_bytes: bytes, language: str) -> list[Import]:
    if node.type not in {
        "import_statement",
        "import_from_statement",
        "import_declaration",
        "use_declaration",
    }:
        return []

    line = node.start_point.row + 1
    if language == "python":
        return _extract_python_imports(node, source_bytes, line)
    if language in {"javascript", "typescript"}:
        return _extract_js_imports(node, source_bytes, line)
    if language == "go":
        return _extract_go_imports(node, source_bytes, line)
    if language == "rust":
        text = _node_text(node, source_bytes)
        return [
            Import(
                module=text.removeprefix("use ").rstrip(";"),
                names=[],
                line=line,
            )
        ]
    if language == "java":
        module = next(
            (
                _node_text(child, source_bytes)
                for child in node.children
                if child.type in {"scoped_identifier", "identifier"}
            ),
            "",
        )
        return [Import(module=module, names=[], line=line)] if module else []
    return []


def _extract_python_imports(
    node: Node,
    source_bytes: bytes,
    line: int,
) -> list[Import]:
    if node.type == "import_statement":
        modules = [
            _node_text(child, source_bytes)
            for child in node.children
            if child.type == "dotted_name"
        ]
        return [Import(module=module, names=[], line=line) for module in modules]

    module = next(
        (
            _node_text(child, source_bytes)
            for child in node.children
            if child.type == "dotted_name"
        ),
        "",
    )
    names: list[str] = []
    seen_module = False
    for child in node.children:
        if child.type != "dotted_name":
            continue
        text = _node_text(child, source_bytes)
        if not seen_module:
            seen_module = True
            continue
        names.append(text)
    return [Import(module=module, names=names, line=line)] if module else []


def _extract_js_imports(
    node: Node,
    source_bytes: bytes,
    line: int,
) -> list[Import]:
    text = _node_text(node, source_bytes)
    module_match = re.search(r"""from\s+["']([^"']+)["']""", text)
    names_match = re.search(r"\{([^}]*)\}", text)
    default_match = re.match(
        r"import\s+(?:type\s+)?([A-Za-z_$][\w$]*)\s*(?:,|from\b)",
        text,
    )

    names: list[str] = []
    if default_match:
        names.append(default_match.group(1))
    if names_match:
        names.extend(
            _normalize_js_import_name(part)
            for part in names_match.group(1).split(",")
            if part.strip()
        )

    module = module_match.group(1) if module_match else ""
    return [Import(module=module, names=names, line=line)] if module else []


def _normalize_js_import_name(part: str) -> str:
    return part.strip().removeprefix("type ").split(" as ")[0].strip()


def _extract_go_imports(
    node: Node,
    source_bytes: bytes,
    line: int,
) -> list[Import]:
    text = _node_text(node, source_bytes)
    results: list[Import] = []
    for offset, raw_line in enumerate(text.splitlines()):
        current_line = line + offset
        stripped = raw_line.strip()
        if not stripped or stripped in {"import (", "import", ")"}:
            continue
        if stripped.startswith("import "):
            stripped = stripped.removeprefix("import ").strip()
        stripped = stripped.rstrip(")")
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) == 1:
            module = parts[0].strip('"')
            results.append(Import(module=module, names=[], line=current_line))
            continue
        if len(parts) >= 2:
            alias = parts[0]
            module = parts[-1].strip('"')
            results.append(Import(module=module, names=[alias], line=current_line))
    return results


def _is_callable_variable(node: Node) -> bool:
    value = node.child_by_field_name("value")
    if value is None:
        return False
    return value.type in {"arrow_function", "function", "function_expression"}


def _node_text(node: Node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode(
        "utf-8",
        errors="replace",
    )
