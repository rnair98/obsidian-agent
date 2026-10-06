import ast
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_FRAMEWORK = ("langchain", "langgraph")
_DYNAMIC_IMPORTS = frozenset({"import_module", "__import__"})
_ADAPTERS = frozenset(
    {
        "app/engine/agents/types.py",
        "app/engine/executor.py",
        "app/engine/graphs/agents.py",
        "app/engine/graphs/research.py",
        "app/engine/nodes/agent.py",
        "app/engine/nodes/builders/agent.py",
        "app/engine/nodes/builders/middleware.py",
        "app/engine/nodes/persist.py",
        "app/engine/nodes/types.py",
        "app/engine/nodes/vault_profiler.py",
        "app/engine/registry.py",
        "app/engine/schema.py",
        "app/engine/tools/shell.py",
        "app/engine/workflows/agents.py",
        "app/engine/workflows/compose.py",
        "app/engine/workflows/research.py",
    }
)


def _framework_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        elif _is_dynamic_import(node):
            modules = [node.args[0].value]
        for module in modules:
            root = module.split(".", 1)[0]
            if root.startswith(_FRAMEWORK):
                found.append(
                    f"{path.relative_to(_REPO)}:{node.lineno} imports {module}"
                )
    return found


def _is_dynamic_import(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call) or not node.args:
        return False
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    first = node.args[0]
    return (
        name in _DYNAMIC_IMPORTS
        and isinstance(first, ast.Constant)
        and isinstance(first.value, str)
    )


def test_framework_imports_stay_in_the_kept_adapters() -> None:
    offenders: list[str] = []
    for path in sorted((_REPO / "app").rglob("*.py")):
        rel = path.relative_to(_REPO).as_posix()
        hits = _framework_imports(path)
        if hits and rel not in _ADAPTERS:
            offenders.extend(hits)
    assert not offenders, (
        "§9 adoption gate: LangChain or LangGraph imported outside the "
        "kept adapters. Read the primitive, prefer no code, and update "
        "the §9 table plus this allowlist only if the gate accepts it. "
        "ARCHITECTURE.md §9.\n" + "\n".join(offenders)
    )
