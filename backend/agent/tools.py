# tools.py
# The agent can't see the repo directly. These 4 tools are its "hands and
# eyes". Every tool answers with FILE PATHS and LINE NUMBERS, which is exactly
# what the agent cites in its final answer.
#
# SECURITY: the tools only look inside repo.files (text already in memory).
# They can't open arbitrary paths on the server or run repo code, so a path
# like "../../etc/passwd" simply isn't found.

from langchain_core.tools import tool

from backend import config
from backend.errors import AppError
from backend.explain_mode import numbered, summarize_file
from backend.llm.context import wrap_file


def build_tools(repo, level: str) -> list:
    """Tools are created per request, so each one is bound to ONE repo."""

    # The docstring of each tool is what the LLM reads to decide when to use it,
    # so they are written for the model, not for us.

    @tool
    def search_code(query: str) -> str:
        """Search the repo's code by meaning AND by exact keywords (file names, function
        names). Returns the best matching code chunks with file paths and line numbers.
        Use this first for almost every question."""
        results = repo.index.search(query, config.SEARCH_TOP_K)
        if not results:
            return "No matching code found. Try different keywords, or use list_dir."
        parts = [wrap_file(c["path"], numbered(c["text"], c["start_line"])) for c in results]
        return "\n".join(parts)[:config.TOOL_OUTPUT_MAX_CHARS]

    @tool
    def read_lines(path: str, start_line: int, end_line: int) -> str:
        """Read an exact range of lines from one file (line numbers start at 1). Use it
        after search_code when you need more context around a result. Returns at most
        150 lines."""
        if path not in repo.files:
            return f"File not found: {path}. Use list_dir to see the real paths."
        lines = repo.files[path].split("\n")
        start = max(1, int(start_line))
        if start > len(lines):
            return f"{path} only has {len(lines)} lines."
        end = min(len(lines), int(end_line), start + config.READ_LINES_MAX - 1)
        if end < start:
            return "end_line must be greater than or equal to start_line."
        body = numbered("\n".join(lines[start - 1:end]), start)
        return wrap_file(path, body)[:config.TOOL_OUTPUT_MAX_CHARS]

    @tool
    def list_dir(path: str = "") -> str:
        """List the files and sub-folders directly inside a folder. Use an empty string
        for the repo root. Folders end with a slash."""
        prefix = path.strip("/")
        prefix = prefix + "/" if prefix else ""
        children = set()
        for file_path in repo.files:
            if file_path.startswith(prefix):
                head, slash, _ = file_path[len(prefix):].partition("/")
                children.add(head + "/" if slash else head)
        if not children:
            return f"No such folder: '{path}'. Call list_dir with an empty path to start at the root."
        # Folders first, then files.
        return "\n".join(sorted(children, key=lambda n: (not n.endswith("/"), n.lower())))

    @tool
    def get_file_summary(path: str) -> str:
        """Get a short plain-English summary of one file. Use it for a quick idea of what
        a file is for. For exact details always use read_lines instead."""
        if path not in repo.files:
            return f"File not found: {path}. Use list_dir to see the real paths."
        try:
            return wrap_file(path, summarize_file(repo, level, path))
        except AppError as exc:
            # Return the problem as TEXT, so the agent can recover instead of crashing.
            return f"Could not summarise this file: {exc.message}"

    return [search_code, read_lines, list_dir, get_file_summary]