# explain_mode.py
# The Gemini-powered Explain features. For now: the project overview.
# Results are cached on the repo object, because each Gemini call is slow and
# rate-limited, so the same question is never asked twice.

import re

from backend import config
from backend.errors import LLMError
from backend.llm import gemini_client, groq_client, prompts
from backend.llm.context import pack_context, wrap_file


def _short_tree(tree: str, max_lines: int = 300) -> str:
    lines = tree.split("\n")
    return "\n".join(lines[:max_lines]) + ("\n..." if len(lines) > max_lines else "")


def _paths_that_exist(items, repo):
    # Anti-hallucination guardrail IN CODE: drop any file the LLM mentioned
    # that isn't really in the repo, instead of trusting the model.
    return [i for i in items if isinstance(i, dict) and i.get("path") in repo.files]


def generate_overview(repo, level: str) -> dict:
    if level in repo.overviews:
        return repo.overviews[level]

    context = pack_context(repo.files)
    system, user = prompts.overview_prompts(level, _short_tree(repo.tree), context)
    data = gemini_client.generate_json(system, user)
    if not isinstance(data, dict):
        raise LLMError("Gemini returned an unexpected format. Please try again.")

    def as_list(key):
        value = data.get(key)
        return value if isinstance(value, list) else []

    # Rebuild the result field by field so a badly-shaped answer can't break the UI.
    default_name = repo.url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    overview = {
        "name": str(data.get("name") or default_name),
        "problem": str(data.get("problem") or "Not clear from the files"),
        "summary": str(data.get("summary") or ""),
        "tech_stack": [t for t in as_list("tech_stack") if isinstance(t, dict)],
        "pipeline": [str(s) for s in as_list("pipeline")],
        "entry_points": _paths_that_exist(as_list("entry_points"), repo),
        "key_files": _paths_that_exist(as_list("key_files"), repo),
        "notes": str(data.get("notes") or ""),
    }
    repo.overviews[level] = overview
    return overview


# ---------------------------------------------------------------------------
# Chat: retrieve the best code chunks, then let Groq answer from them only.
# ---------------------------------------------------------------------------
NOT_FOUND = "I couldn't find this in the repo."
CITATION = re.compile(r"([\w./\-]+\.\w+):(\d+)")  # matches things like backend/main.py:12


def numbered(text: str, first_line: int) -> str:
    # Show real line numbers so the model can cite them exactly.
    return "\n".join(f"{n}: {line}" for n, line in enumerate(text.split("\n"), start=first_line))


def check_citations(answer: str, repo) -> str:
    # Anti-hallucination guardrail IN CODE, so we don't rely on the model obeying the prompt.
    if NOT_FOUND in answer:
        return answer
    cited = {m.group(1) for m in CITATION.finditer(answer)}
    if not cited:
        return answer + "\n\n⚠️ This answer has no file citations, so treat it with caution."
    fake = sorted(path for path in cited if path not in repo.files)
    if fake:
        return answer + f"\n\n⚠️ These cited files do not exist in the repo: {', '.join(fake)}"
    return answer


def answer_question(repo, question: str, history: list, level: str) -> dict:
    chunks = repo.index.search(question, config.SEARCH_TOP_K)
    if not chunks:
        return {"answer": NOT_FOUND, "sources": []}  # nothing retrieved, so never guess

    excerpts = "\n\n".join(
        wrap_file(c["path"], numbered(c["text"], c["start_line"])) for c in chunks)

    messages = [("system", prompts.chat_system_prompt(level, repo.url))]
    messages += [(m["role"], m["content"]) for m in history[-config.CHAT_HISTORY_MESSAGES:]]
    messages.append(("user", f"Code excerpts:\n{excerpts}\n\nQuestion: {question}"))

    answer = groq_client.chat(messages).strip() or NOT_FOUND
    return {
        "answer": check_citations(answer, repo),
        "sources": [f"{c['path']}:{c['start_line']}-{c['end_line']}" for c in chunks],
    }


# ---------------------------------------------------------------------------
# File summaries
# ---------------------------------------------------------------------------
def summarize_files(repo, level: str) -> dict:
    """Summarise EVERY kept file, in batches, and cache the result."""
    cache = repo.summaries.setdefault(level, {})
    pending = [path for path in repo.files if path not in cache]

    # Group files into batches, so we make a few big Gemini calls instead of
    # hundreds of tiny ones (free-tier rate limits).
    batches, current, size = [], [], 0
    for path in pending:
        text = repo.files[path][:config.SUMMARY_CHARS_PER_FILE]
        if current and size + len(text) > config.SUMMARY_BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append((path, text))
        size += len(text)
    if current:
        batches.append(current)

    for batch in batches:
        files_text = "\n\n".join(wrap_file(path, text) for path, text in batch)
        system, user = prompts.summaries_prompts(level, files_text)
        data = gemini_client.generate_json(system, user)
        if isinstance(data, dict):
            for path, _ in batch:
                if isinstance(data.get(path), str):
                    cache[path] = data[path]

    # Keep the repo's own file order. If the model skipped a file, say so
    # honestly instead of inventing a summary.
    return {path: cache.get(path, "(no summary was returned for this file)") for path in repo.files}


def summarize_file(repo, level: str, path: str) -> str:
    """Summary of ONE file (used later by the agent). Reuses the cache when possible."""
    cache = repo.summaries.setdefault(level, {})
    if path not in cache:
        system, user = prompts.single_summary_prompts(level, wrap_file(path, repo.files[path][:12_000]))
        cache[path] = gemini_client.generate(system, user).strip()
    return cache[path]



# ---------------------------------------------------------------------------
# Mermaid diagrams
# ---------------------------------------------------------------------------
def generate_diagram(repo, kind: str) -> str:
    if kind in repo.diagrams:
        return repo.diagrams[kind]

    context = pack_context(repo.files, budget=60_000)  # a diagram needs less text than an overview
    system, user = prompts.diagram_prompts(kind, _short_tree(repo.tree), context)
    code = gemini_client.generate(system, user).strip()

    if code.startswith("```"):  # models add code fences even when told not to
        code = code.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    # Cheap sanity check: real Mermaid flowcharts start with one of these words.
    if not code.startswith(("flowchart", "graph")):
        raise LLMError("Gemini did not return a valid diagram. Please try again.")

    repo.diagrams[kind] = code
    return code