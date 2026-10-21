# context.py
# Picks the MOST useful files (README, dependency files, entry points) and
# packs them into one text block for the LLM, stopping at our size budget.

from backend import config

MANIFESTS = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "pipfile",
    "cargo.toml", "go.mod", "pom.xml", "build.gradle", "dockerfile",
    "docker-compose.yml", "docker-compose.yaml", "makefile", "procfile",
    "render.yaml", ".env.example", ".env.sample", "gemfile", "composer.json",
}
ENTRY_STEMS = {"main", "app", "index", "server", "manage", "cli", "__main__", "run", "wsgi", "asgi"}

def is_manifest(path: str) -> bool:
    # True for files that describe how a project is built or run (package.json, requirements.txt ...).
    name = path.rsplit("/", 1)[-1].lower()
    return name in MANIFESTS or name.startswith("requirements")

def _priority(path: str) -> int:
    # Lower number = more important = included first.
    name = path.rsplit("/", 1)[-1].lower()
    if name.startswith("readme"):
        return 0
    if name in MANIFESTS or name.startswith("requirements"):
        return 1
    if name.split(".")[0] in ENTRY_STEMS:
        return 2
    return 3


def wrap_file(path: str, body: str) -> str:
    # Prompt-injection guardrail: tags mark this text as repo DATA. A file that
    # contains "</repo_file>" could fake the end of the tag, so we break it.
    safe_body = body.replace("</repo_file>", "<\\/repo_file>")
    safe_path = path.replace('"', "")
    return f'<repo_file path="{safe_path}">\n{safe_body}\n</repo_file>'


def pack_context(files: dict, budget: int = config.CONTEXT_CHARS,
                 per_file: int = config.CONTEXT_CHARS_PER_FILE) -> str:
    ordered = sorted(files, key=lambda p: (_priority(p), p.count("/"), p.lower()))
    parts, used = [], 0
    for path in ordered:
        text = files[path][:per_file]
        if len(files[path]) > per_file:
            text += "\n... [file truncated]"
        if used + len(text) > budget:
            continue  # this one doesn't fit, but a smaller file later might
        parts.append(wrap_file(path, text))
        used += len(text)
    return "\n\n".join(parts)