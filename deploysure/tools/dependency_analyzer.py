"""Builds an import graph of a release and finds what a change can reach."""
import ast
import sys
from pathlib import Path

from .code_reader import python_files, read_source, release_path


def build_import_graph(release_dir: Path) -> dict[str, set[str]]:
    """Maps each module to the other project modules it imports."""
    modules = {p.stem for p in python_files(release_dir)}
    graph: dict[str, set[str]] = {}
    for path in python_files(release_dir):
        deps: set[str] = set()
        for node in ast.walk(ast.parse(read_source(path), filename=path.name)):
            if isinstance(node, ast.Import):
                deps.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    deps.add(node.module.split(".")[0])
                else:  # "from . import x"
                    deps.update(a.name for a in node.names)
        graph[path.stem] = (deps & modules) - {path.stem}
    return graph


def impacted_modules(graph: dict[str, set[str]], changed: list[str]) -> list[str]:
    """Changed modules plus everything that imports them, directly or not."""
    seen = set(changed)
    queue = list(changed)
    while queue:
        current = queue.pop()
        for module, deps in graph.items():
            if current in deps and module not in seen:  # 'seen' also stops import cycles
                seen.add(module)
                queue.append(module)
    return sorted(seen)


def is_test_module(name: str) -> bool:
    return name.startswith("test_")


if __name__ == "__main__":
    g = build_import_graph(release_path(sys.argv[1]))
    changed = sys.argv[2:]
    print("imports:", {m: sorted(d) for m, d in g.items() if d and not is_test_module(m)})
    print(f"impacted by {changed}:", impacted_modules(g, changed))
