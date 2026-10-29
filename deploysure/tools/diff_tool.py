"""Compares two release folders: which files and functions changed."""
import ast
import copy
import difflib
import sys
from pathlib import Path

from .code_reader import python_files, read_source, release_path


def _is_code(path: Path) -> bool:
    return not (path.name.startswith("test_") or path.name == "conftest.py")


def _strip_docstring(node: ast.AST) -> ast.AST:
    node = copy.deepcopy(node)
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        node.body = body[1:] or [ast.Pass()]
    return node


def _function_map(source: str, filename: str = "<unknown>") -> dict[str, str]:
    """Maps 'func' or 'Class.method' to a dump of its code, ignoring comments and docstrings."""
    found: dict[str, str] = {}

    def visit(parent: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[prefix + child.name] = ast.dump(_strip_docstring(child))
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")

    visit(ast.parse(source, filename=filename), "")
    return found


def _module_level_dump(source: str, filename: str = "<unknown>") -> str:
    """Imports and constants outside functions, so editing FEE_RATE is not missed."""
    keep = [n for n in ast.parse(source, filename=filename).body
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    return "\n".join(ast.dump(n) for n in keep)


def changed_functions(old_src: str, new_src: str, filename: str = "<unknown>") -> list[str]:
    old, new = _function_map(old_src, filename), _function_map(new_src, filename)
    names = {n for n in old.keys() | new.keys() if old.get(n) != new.get(n)}
    if _module_level_dump(old_src, filename) != _module_level_dump(new_src, filename):
        names.add("<module-level>")
    return sorted(names)


def lines_changed(old_src: str, new_src: str) -> int:
    diff = difflib.unified_diff(old_src.splitlines(), new_src.splitlines(), lineterm="", n=0)
    return sum(1 for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---")))


def diff_releases(old_dir: Path, new_dir: Path) -> dict:
    """Returns changed files with their changed functions and line counts."""
    # Tests are not product code, and generated test cases must never count as a change.
    old_files = {p.name: p for p in python_files(old_dir) if _is_code(p)}
    new_files = {p.name: p for p in python_files(new_dir) if _is_code(p)}
    details: dict[str, dict] = {}
    for name in sorted(old_files.keys() | new_files.keys()):
        old_src = read_source(old_files[name]) if name in old_files else ""
        new_src = read_source(new_files[name]) if name in new_files else ""
        if old_src == new_src:
            continue
        details[name] = {
            "functions": changed_functions(old_src, new_src, name),
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
