# filters.py
# A repo has many files that don't explain the project (dependencies, images,
# lock files, binaries). We keep only readable text files, enforce the size and
# count limits, and load them into memory as TEXT. After this step the cloned
# folder is deleted, so no untrusted file stays on disk and nothing from it
# can ever be executed.

import os

from backend import config


def _is_junk_name(name: str) -> bool:
    lower = name.lower()
    if name in config.IGNORED_FILENAMES or lower.endswith(config.IGNORED_SUFFIXES):
        return True
    # .env / .env.local ... may contain committed secrets: skip them,
    # except template files like .env.example.
    if lower.startswith(".env") and not lower.endswith(config.SAFE_ENV_SUFFIXES):
        return True
    return False


def collect_files(repo_dir: str):
    """Return ({relative/path: text}, stats). Dict order = most important files first."""
    candidates = []  # (depth, relative_path, absolute_path)
    skipped = 0

    for dirpath, dirnames, filenames in os.walk(repo_dir, followlinks=False):
        # Editing dirnames in place stops os.walk from entering junk folders.
        dirnames[:] = sorted(d for d in dirnames if d not in config.IGNORED_DIRS)
        for name in filenames:
            abs_path = os.path.join(dirpath, name)
            rel_path = os.path.relpath(abs_path, repo_dir).replace(os.sep, "/")
            # Security guardrail: never follow symlinks (they could point outside the repo).
            if _is_junk_name(name) or os.path.islink(abs_path):
                skipped += 1
                continue
            candidates.append((rel_path.count("/"), rel_path, abs_path))

    # Shallow files first: README, package.json and main.py matter more than
    # deeply nested files when the file-count limit cuts the list off.
    candidates.sort(key=lambda c: (c[0], c[1].lower()))

    files = {}
    limit_hit = False
    for _depth, rel_path, abs_path in candidates:
        if len(files) >= config.MAX_FILES:  # resource-limit guardrail
            limit_hit = True
            skipped += 1
            continue
        size = os.path.getsize(abs_path)
        if size == 0 or size > config.MAX_FILE_SIZE_KB * 1024:
            skipped += 1
            continue
        with open(abs_path, "rb") as f:  # "rb": we only READ bytes, never run anything
            raw = f.read()
        if b"\x00" in raw[:2048]:  # null bytes mean it's a binary file
            skipped += 1
            continue
        files[rel_path] = raw.decode("utf-8", errors="replace")

    return files, {"files_kept": len(files), "files_skipped": skipped, "file_limit_hit": limit_hit}