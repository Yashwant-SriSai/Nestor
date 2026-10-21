# validator.py
# WHY this file exists: the URL comes from the user, and we must treat every
# user input as untrusted. We only let through URLs that look EXACTLY like
# https://github.com/<owner>/<repo>. Anything else is rejected BEFORE we run
# git on it.

import re

# GitHub usernames: letters, digits and hyphens, and they must start with a
# letter or digit. Because the owner can't start with "-", it can never look
# like a command-line option (e.g. "--upload-pack=...") to git.
_OWNER = r"[A-Za-z0-9][A-Za-z0-9-]{0,38}"

# Repo names: letters, digits, dot, underscore, hyphen.
_REPO = r"[A-Za-z0-9._-]{1,100}"

# WHY a strict regex instead of "does it contain github.com?":
# a loose check would accept tricks like https://evil.com/github.com/x/y or
# https://github.com.evil.com/x/y. A full-match pattern accepts only the
# exact shape we want, and nothing else.
_GITHUB_URL = re.compile(rf"https://github\.com/({_OWNER})/({_REPO})")


def validate_github_url(url: str) -> str:
    """Return a clean clone URL, or raise ValueError with a friendly message."""
    cleaned = url.strip()

    # Be forgiving about two harmless things people paste: a trailing slash
    # and a trailing ".git".
    cleaned = cleaned.rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[: -len(".git")]

    match = _GITHUB_URL.fullmatch(cleaned)
    if match is None:
        raise ValueError(
            "Please enter a public GitHub repo URL like "
            "https://github.com/owner/repo"
        )

    owner, repo = match.groups()

    # "." and ".." are legal characters in our pattern but are not real repo
    # names, and ".." is a path trick, so we block them explicitly.
    if repo in (".", ".."):
        raise ValueError("That is not a valid repository name.")

    # We rebuild the URL from the checked pieces instead of returning the
    # user's raw text, so only validated characters ever reach git.
    return f"https://github.com/{owner}/{repo}.git"