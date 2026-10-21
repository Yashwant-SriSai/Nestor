# rebuild.py
# Build mode "Rebuild it": to recreate a project from an empty folder you must
# create files in the right order, because a file should only be written AFTER
# the files it imports. We read each file's imports to build an IMPORT GRAPH,
# then order the files least-dependent first.
#
# SECURITY: imports are found by PARSING TEXT (ast.parse and a regex). ast.parse
# only reads syntax. The repo's code is never imported or executed.

import ast
import posixpath
import re

from backend.explain_mode import summarize_file
from backend.llm.context import is_manifest

PY_EXTS = (".py",)
JS_EXTS = (".js", ".jsx", ".mjs", ".cjs")

# Matches:  import x from './a'  |  require('./a')  |  import('./a')  |  export * from './a'
_JS_IMPORT = re.compile(
    r"""(?:import\s+(?:[^'"]*?\s+from\s+)?|require\(\s*|import\(\s*|export\s+[^'"]*?\s+from\s+)['"]([^'"]+)['"]""")


# ----------------------------------------------------------------- Python ---
def _python_module_index(py_paths: list) -> dict:
    """Map every dotted ending of a file's path to the file: a/b/c.py -> 'a.b.c', 'b.c', 'c'."""
    index = {}
    for path in py_paths:
        parts = path[:-3].split("/")  # drop ".py"
        if parts[-1] == "__init__":
            parts = parts[:-1]
        for i in range(len(parts)):
            index.setdefault(".".join(parts[i:]), []).append(path)
    return index


def _common_prefix(a: str, b: str) -> int:
    count = 0
    for x, y in zip(a.split("/")[:-1], b.split("/")[:-1]):
        if x != y:
            break
        count += 1
    return count


def _resolve_python(importer, level, module, alias, files, index):
    """Return the repo file an import refers to, or None (standard library / third-party)."""
    if module and alias:
        # `from a import b`: b may be a module (a.b) or just a name inside module a.
        names = [f"{module}.{alias}", module]
    else:
        names = [module or alias]  # `import a.b` or `from . import x`

    for dotted in names:
        if not dotted:
            continue
        if level > 0:  # relative import: from . import x / from ..pkg import y
            base = importer.split("/")[:-1]
            if level - 1 > len(base):
                continue
            base = base[:len(base) - (level - 1)]
            relative = "/".join(base + dotted.split("."))
            for candidate in (f"{relative}.py", f"{relative}/__init__.py"):
                if candidate in files:
                    return candidate
            continue

        candidates = index.get(dotted, [])
        # A lone name like "json" or "config" could be a library OR a repo file.
        # Only trust it when the file sits next to the importer or at the repo root.
        if "." not in dotted:
            here = posixpath.dirname(importer)
            candidates = [c for c in candidates if posixpath.dirname(c) in (here, "")]
        if candidates:
            # Several matches: prefer the one closest to the importer.
            return max(candidates, key=lambda c: _common_prefix(c, importer))
    return None


def _python_deps(path, text, files, index) -> set:
    try:
        tree = ast.parse(text)
    except Exception:  # noqa: BLE001 - syntax errors or absurd nesting: treat as "no imports"
        return set()
    deps = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                deps.add(_resolve_python(path, 0, alias.name, "", files, index))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                deps.add(_resolve_python(path, node.level, node.module or "", alias.name, files, index))
    deps.discard(None)
    deps.discard(path)
    return deps


# -------------------------------------------------------------- JavaScript ---
def _js_deps(path, text, files) -> set:
    deps = set()
    for spec in _JS_IMPORT.findall(text):
        if not spec.startswith("."):
            continue  # a package from node_modules, not a file of this repo
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
        options = [target] + [target + ext for ext in JS_EXTS] + [f"{target}/index{ext}" for ext in JS_EXTS]
        for option in options:
            if option in files and option != path:
                deps.add(option)
                break
    return deps


# ---------------------------------------------------------------- ordering ---
def _topological(nodes: set, deps: dict) -> list:
    """Dependencies first. Iterative (no recursion limit), and import cycles are tolerated."""
    order, seen = [], set()
    for start in sorted(nodes, key=lambda n: (len(deps[n]), n)):  # files with no imports first
        if start in seen:
            continue
        seen.add(start)
        stack = [(start, iter(sorted(deps[start])))]
        while stack:
            node, children = stack[-1]
            for child in children:
                if child in deps and child not in seen:
                    seen.add(child)
                    stack.append((child, iter(sorted(deps[child]))))
                    break
            else:
                stack.pop()
                order.append(node)  # all of its dependencies are already in the list
    return order


def get_plan(repo) -> list:
    """Ordered list of {path, depends_on}. Cached on the repo."""
    if repo.rebuild_plan is not None:
        return repo.rebuild_plan

    files = repo.files
    python_index = _python_module_index([p for p in files if p.endswith(PY_EXTS)])

    deps = {}  # only code files have dependencies
    for path, text in files.items():
        if path.endswith(PY_EXTS):
            deps[path] = _python_deps(path, text, files, python_index)
        elif path.endswith(JS_EXTS):
            deps[path] = _js_deps(path, text, files)

    config_files = sorted(p for p in files if p not in deps
                          and (is_manifest(p) or p.rsplit("/", 1)[-1].startswith(".env")))
    other_files = sorted(p for p in files if p not in deps and p not in config_files)

    # Setup files first (you need them to install), then code in dependency
    # order, then everything else (README, docs, data).
    ordered = config_files + _topological(set(deps), deps) + other_files
    repo.rebuild_plan = [{"path": p, "depends_on": sorted(deps.get(p, []))} for p in ordered]
    return repo.rebuild_plan


def get_step(repo, path: str, level: str):
    entry = next((e for e in get_plan(repo) if e["path"] == path), None)
    if entry is None:
        return None
    code = repo.files[path]
    return {
        "path": path,
        "depends_on": entry["depends_on"],
        "code": code[:30_000] + ("\n... [file shortened]" if len(code) > 30_000 else ""),
        "explanation": summarize_file(repo, level, path),  # Gemini, cached per file
    }