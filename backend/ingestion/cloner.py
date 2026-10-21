# cloner.py
# The ONLY place that runs git. It copies a public repo into a temp folder.
#
# SECURITY RULE for the whole project: a cloned repo is untrusted. We never
# import, run, install or execute anything from it. We only read files as text.

import os
import shutil
import stat
import subprocess
import sys
import tempfile

from backend import config
from backend.errors import AppError


def _force_remove(func, path, _exc):
    # On Windows, files inside .git are read-only, so plain rmtree fails.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_dir(path: str) -> None:
    """Delete a folder tree, including the read-only files git creates on Windows."""
    # Python 3.12 renamed rmtree's `onerror` argument to `onexc`.
    kwargs = {"onexc": _force_remove} if sys.version_info >= (3, 12) else {"onerror": _force_remove}
    try:
        shutil.rmtree(path, **kwargs)
    except OSError:
        pass  # leftover temp files are harmless; never crash a request over them


def _dir_size_mb(path: str) -> float:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        dirnames[:] = [d for d in dirnames if d != ".git"]  # git internals aren't "the project"
        for name in filenames:
            full = os.path.join(dirpath, name)
            if not os.path.islink(full):
                total += os.path.getsize(full)
    return total / (1024 * 1024)


def clone_repo(clean_url: str):
    """Clone with --depth 1. Returns (workdir, repo_dir, size_mb). The caller must remove_dir(workdir)."""
    workdir = tempfile.mkdtemp(prefix="nestor_")
    repo_dir = os.path.join(workdir, "repo")

    # Input-validation guardrail: an ARGUMENT LIST (never a shell string), so the
    # URL can't be interpreted as extra shell commands.
    cmd = [
        "git",
        "-c", "credential.helper=",   # never use or store saved credentials
        "-c", "core.symlinks=false",  # symlinks become plain text files, so a repo can't point us at /etc/passwd
        "clone",
        "--depth", "1",               # only the latest snapshot, not the whole history
        "--single-branch", "--no-tags",
        "--",                         # everything after this is data, never an option
        clean_url, repo_dir,
    ]
    # GitHub asks for a password when a repo doesn't exist or is private.
    # Without this setting our server would hang waiting for someone to type it.
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, env=env,
            timeout=config.CLONE_TIMEOUT_SECONDS, shell=False,
        )
    except subprocess.TimeoutExpired:
        remove_dir(workdir)
        raise AppError(
            f"Cloning took longer than {config.CLONE_TIMEOUT_SECONDS}s, so it was stopped. "
            "The repo may be too large.", 504)
    except FileNotFoundError:
        remove_dir(workdir)
        raise AppError("Git is not installed on the server.", 500)

    if result.returncode != 0:
        remove_dir(workdir)
        # We deliberately don't echo git's raw error text back to the user.
        raise AppError(
            "Could not clone that repo. Check that the URL is correct and the repo is public.", 400)

    # Resource-limit guardrail. Trade-off: git can't tell us the size up front,
    # so the clone finishes BEFORE we measure it; the timeout above is the safety
    # net for gigantic repos.
    size_mb = _dir_size_mb(repo_dir)
    if size_mb > config.MAX_REPO_SIZE_MB:
        remove_dir(workdir)
        raise AppError(
            f"This repo is {size_mb:.0f} MB. The limit is {config.MAX_REPO_SIZE_MB} MB "
            "to keep the free server within memory.", 413)

    return workdir, repo_dir, size_mb