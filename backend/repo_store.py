# repo_store.py
# After /analyze we must remember the repo's files and search index for the
# next requests (overview, chat). No database, as planned: a plain in-memory
# dict. Only the newest few repos are kept so the free server doesn't run out
# of memory. If the server restarts, the user simply analyses the repo again.

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from backend import config
from backend.errors import AppError
from backend.indexing.hybrid import RepoIndex


@dataclass
class Repo:
    id: str
    url: str
    files: dict       # {relative/path: text}
    tree: str
    index: RepoIndex  # hybrid search over this repo's chunks
    stats: dict
    # Cache of finished Gemini answers, so each one is generated only once.
    overviews: dict = field(default_factory=dict)  # level -> overview
    summaries: dict = field(default_factory=dict)  # level -> {path: summary}
    diagrams: dict = field(default_factory=dict)   # "architecture" / "dataflow" -> Mermaid code
    plans: dict = field(default_factory=dict)      # (os, level) -> build plan
    rebuild_plan: list = None                      # ordered files for "Rebuild it"

_repos = OrderedDict()
_lock = threading.Lock()  # FastAPI handles requests in several threads at once


def add(repo: Repo) -> None:
    with _lock:
        _repos[repo.id] = repo
        while len(_repos) > config.MAX_REPOS_IN_MEMORY:
            _, oldest = _repos.popitem(last=False)
            oldest.index.close()  # free the dropped repo's vectors too


def get(repo_id: str) -> Repo:
    with _lock:
        repo = _repos.get(repo_id)
    if repo is None:
        raise AppError("That repo is no longer loaded (the server may have restarted). "
                       "Please analyze the repo again.", 404)
    return repo