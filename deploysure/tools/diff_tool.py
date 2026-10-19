"""Compares two release folders: which files and functions changed."""
import ast
import copy
import difflib
import sys
from pathlib import Path

from .code_reader import python_files, read_source, release_path


def _strip_docstring(node: ast.AST) -> ast.AST:
    node = copy.deepcopy(node)
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        node.body = body[1:] or [ast.Pass()]
    return node


def _function_map(source: str) -> dict[str, str]:
    """Maps 'func' or 'Class.method' to a dump of its code, ignoring comments and docstrings."""
    found: dict[str, str] = {}

    def visit(parent: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + child.name] = ast.dump(_strip_docstring(child))
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")

    visit(ast.parse(source), "")
    return found


def _module_level_dump(source: str) -> str:
    """Imports and constants outside functions, so editing FEE_RATE is not missed."""
    keep = [n for n in ast.parse(source).body
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    return "\n".join(ast.dump(n) for n in keep)


def changed_functions(old_src: str, new_src: str) -> list[str]:
    old, new = _function_map(old_src), _function_map(new_src)
    names = {n for n in old.keys() | new.keys() if old.get(n) != new.get(n)}
    if _module_level_dump(old_src) != _module_level_dump(new_src):
        names.add("<module-level>")
    return sorted(names)


def lines_changed(old_src: str, new_src: str) -> int:
    diff = difflib.unified_diff(old_src.splitlines(), new_src.splitlines(), lineterm="", n=0)
    return sum(1 for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---")))


def diff_releases(old_dir: Path, new_dir: Path) -> dict:
    """Returns changed files with their changed functions and line counts."""
    old_files = {p.name: p for p in python_files(old_dir)}
    new_files = {p.name: p for p in python_files(new_dir)}
    details: dict[str, dict] = {}
    for name in sorted(old_files.keys() | new_files.keys()):
        old_src = read_source(old_files[name]) if name in old_files else ""
        new_src = read_source(new_files[name]) if name in new_files else ""
        if old_src == new_src:
            continue
        details[name] = {
            "functions": changed_functions(old_src, new_src),
            "lines_changed": lines_changed(old_src, new_src),
        }
    return {
        "changed_files": list(details),
        "details": details,
        "lines_changed": sum(d["lines_changed"] for d in details.values()),
    }


if __name__ == "__main__":
    result = diff_releases(release_path(sys.argv[1]), release_path(sys.argv[2]))
    print(f"{sys.argv[1]} -> {sys.argv[2]}")
    for file, info in result["details"].items():
        print(f"  {file}: functions={info['functions']} lines_changed={info['lines_changed']}")
