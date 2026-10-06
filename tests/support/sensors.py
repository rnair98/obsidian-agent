import ast
from pathlib import Path

_WRITE_ATTRS = {"write_text", "write_bytes"}
_WRITE_MODES = set("wax+")


def _via_backend(expr: ast.AST) -> bool:
    if isinstance(expr, ast.Name):
        return expr.id == "backend"
    if isinstance(expr, ast.Attribute):
        return expr.attr == "backend" or _via_backend(expr.value)
    return False


def _writes(call: ast.Call) -> bool:
    mode = call.args[0] if call.args else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    if mode is None:
        return False
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return bool(_WRITE_MODES & set(mode.value))
    return True  # a computed mode may write


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if isinstance(func, ast.Name) and func.id == "open":
        return "open()"
    if (
        isinstance(func, ast.Attribute)
        and func.attr in _WRITE_ATTRS
        and not _via_backend(func.value)
    ):
        return f"{func.attr}()"
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "open"
        and not _via_backend(func.value)
        and _writes(node)
    ):
        return "open()"
    return None


def direct_write_violations(root: Path) -> list[str]:
    paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
    found: list[str] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            call = _call_name(node)
            if call is None:
                continue
            found.append(
                f"§10 sandbox: {path}:{node.lineno} calls {call}. "
                "Writers go through FilesystemBackend. "
                "ARCHITECTURE.md §9 and §10."
            )
    return found


def _decorator_name(dec: ast.expr) -> str | None:
    func = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _defines_workflow(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        decorators = getattr(node, "decorator_list", ())
        for dec in decorators:
            if _decorator_name(dec) == "workflow":
                return True
    return False


def _imported_names(init_path: Path) -> set[str]:
    tree = ast.parse(init_path.read_text(), filename=str(init_path))
    names: set[str] = set()
    # Only unconditional top-level imports run at package initialization.
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.rsplit(".", 1)[-1])
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.rsplit(".", 1)[-1])
    return names


def workflow_import_violations(workflows: Path) -> list[str]:
    imported = _imported_names(workflows / "__init__.py")
    missing: list[str] = []
    for path in sorted(workflows.glob("*.py")):
        if path.name == "__init__.py" or not _defines_workflow(path):
            continue
        if path.stem not in imported:
            missing.append(
                f"§9 workflow: {path} defines @workflow but "
                f"{workflows / '__init__.py'} does not import it. "
                "Registration is import-time. ARCHITECTURE.md §9 and §10."
            )
    return missing


def graph_workflow_violations(graphs: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(graphs.rglob("*.py")):
        if _defines_workflow(path):
            found.append(
                f"§9 workflow: {path} defines @workflow. "
                "A graph is not a workflow. Decorate the factory in "
                "app/engine/workflows/. ARCHITECTURE.md §9."
            )
    return found
