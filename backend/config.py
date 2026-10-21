# config.py
# All limits, ignore-lists, model names and API keys live here.

import os

from dotenv import load_dotenv

# Reads the .env file (if present) into environment variables. This is how API
# keys reach the code WITHOUT being written in it (secrets guardrail).
load_dotenv()


def _key(name: str) -> str:
    # Treat the placeholder from .env.example ("your-...") as "not set".
    value = os.getenv(name, "").strip()
    return "" if value.startswith("your-") else value


GEMINI_API_KEY = _key("GEMINI_API_KEY")

# Model names change often. This one was checked against Google's models page
# (ai.google.dev/gemini-api/docs/models). If it is ever retired, set
# GEMINI_MODEL in .env instead of editing code.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

GROQ_API_KEY = _key("GROQ_API_KEY")

# Checked against console.groq.com/docs/models. Phase 3 (the agent) needs a model
# that supports tool calling, so check Groq's docs if this model is ever retired.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
# config.py
# WHY this file exists: all our limits and ignore-lists live in ONE place.
# If we want to change "50 MB" to "30 MB" later, we edit one line here
# instead of hunting through many files.

# ---------------------------------------------------------------------------
# Resource limits (guardrail: protects Render's free-tier memory and our time)
# ---------------------------------------------------------------------------

# Refuse repos bigger than this after cloning. Huge repos would use too much
# memory when we read and index them.
MAX_REPO_SIZE_MB = 50

# Skip any single file larger than this. Huge files are usually generated or
# data files, and they would flood the LLM with useless text.
MAX_FILE_SIZE_KB = 200

# Stop after this many files. This bounds how much work indexing must do later.
MAX_FILES = 500

# If git clone takes longer than this, give up. Without a timeout, a slow or
# stuck clone could freeze our server forever.
CLONE_TIMEOUT_SECONDS = 60

MAX_REPOS_IN_MEMORY = 2   # the oldest analysed repo is dropped when a 3rd arrives
# ---------------------------------------------------------------------------
# Junk filters (guardrail: only read files that help explain the project)
# ---------------------------------------------------------------------------

# Folders we never look inside. They hold downloaded dependencies, git
# internals, or build output, none of which explains the project itself.
IGNORED_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "build", "dist", "target", ".next", ".idea", ".vscode", "vendor",
}

# Lock files are auto-generated and very long, so they add noise, not meaning.
IGNORED_FILENAMES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "Cargo.lock", "composer.lock",
}

# Files ending with these are images, binaries, archives, fonts, or generated
# files. We can't read them as text, and we never want to open or run them.
# It's a tuple (not a set) because str.endswith() accepts a tuple.
IGNORED_SUFFIXES = (
    # images
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp",
    # binaries and compiled files
    ".exe", ".dll", ".so", ".bin", ".pyc", ".class", ".jar",
    # archives
    ".zip", ".tar", ".gz", ".7z",
    # media, fonts, documents
    ".mp3", ".mp4", ".mov", ".woff", ".woff2", ".ttf", ".pdf",
    # generated or minified files
    ".min.js", ".min.css", ".map",
)
# ".env" files often hold real secrets committed by accident, so we skip them.
# Template files with these endings are safe and useful to read.
SAFE_ENV_SUFFIXES = (".example", ".sample", ".template")
# ---------------------------------------------------------------------------
# How much repo text we send to the LLM in one prompt
# ---------------------------------------------------------------------------
CONTEXT_CHARS = 100_000          # total file text in one prompt
CONTEXT_CHARS_PER_FILE = 6_000   # one long file is cut off after this many characters

# ---------------------------------------------------------------------------
# Retry with backoff for rate-limited LLM calls
# ---------------------------------------------------------------------------
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 3     # waits 3s, then 6s between attempts
# ---------------------------------------------------------------------------
# Chunking (splitting files into searchable pieces)
# ---------------------------------------------------------------------------
CHUNK_MAX_LINES = 60       # a chunk never grows past this many lines
FALLBACK_CHUNK_LINES = 40  # window size for files that aren't Python/JavaScript
MAX_CHUNKS = 800           # embedding chunks is the slowest, most memory-hungry step
# ---------------------------------------------------------------------------
# Search and chat
# ---------------------------------------------------------------------------
SEARCH_TOP_K = 5            # code chunks given to the chat model per question
CHAT_HISTORY_MESSAGES = 6   # how many earlier chat messages the model sees
# ---------------------------------------------------------------------------
# File summaries (Gemini summarises files in batches, to stay within rate limits)
# ---------------------------------------------------------------------------
SUMMARY_CHARS_PER_FILE = 1_500   # only the start of each file is sent
SUMMARY_BATCH_CHARS = 80_000     # files are grouped into prompts of about this size
# ---------------------------------------------------------------------------
# Agent tool limits (keep tool answers small so the LLM isn't flooded)
# ---------------------------------------------------------------------------
READ_LINES_MAX = 150           # most lines read_lines returns in one call
TOOL_OUTPUT_MAX_CHARS = 8000   # hard cap on any single tool answer
# ---------------------------------------------------------------------------
# Agent loop limit (guardrail: protects the LLM rate limits and response time)
# ---------------------------------------------------------------------------
AGENT_MAX_STEPS = 8   # most tool-calling rounds the agent may use per question