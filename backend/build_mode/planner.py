# planner.py
# Build mode "Run it": Gemini writes a step-by-step guide (clone, install,
# configure, run, test, deploy). Later parts add answering the user's doubts.
#
# BUILD MODE SAFETY: this code only produces TEXT. It never runs a command.
# The user copies each command and runs it themselves.

import re

from backend.errors import LLMError
from backend.llm import gemini_client, groq_client, prompts
from backend.llm.context import pack_context

# Risky commands get a warning label. This is done in CODE with patterns,
# because we can't trust an LLM to always remember to warn.
RISKY = [
    (r"\bsudo\b", "Uses sudo (administrator rights). Only run it if you understand why it is needed."),
    (r"\brm\s+-[a-z]*[rf]", "rm -r / rm -f can permanently delete files. Double-check the path."),
    (r"(curl|wget)[^|\n]*\|\s*(sudo\s+)?(ba|z)?sh\b",
     "Downloads a script and runs it immediately (curl | bash). Read the script first."),
    (r"\b(iex|invoke-expression)\b", "Runs downloaded text as code (iex). Only use sources you fully trust."),
    (r"remove-item[^\n]*-recurse", "Recursively deletes files. Double-check the path."),
    (r"\b(del|rmdir|rd)\b[^\n]*\s/[sq]\b", "Deletes files and folders without asking. Double-check the path."),
    (r"chmod\s+(-r\s+)?777", "Makes files writable by everyone. Rarely a good idea."),
    (r"\b(mkfs|dd\s+if=)", "Can overwrite a whole disk. Do not run it unless you are sure."),
    (r"(npm|yarn)\s+(install|i|add)\s+(-g|--global)",
     "Installs globally and changes your whole machine, not just this project."),
]


def flag_risky(command: str):
    for pattern, warning in RISKY:
        if re.search(pattern, command, re.IGNORECASE):
            return warning
    return None


def generate_plan(repo, os_name: str, level: str) -> dict:
    key = (os_name, level)
    if key in repo.plans:
        return repo.plans[key]

    context = pack_context(repo.files, budget=60_000)
    system, user = prompts.plan_prompts(level, os_name, repo.url, repo.tree[:6000], context)
    data = gemini_client.generate_json(system, user)
    raw_steps = data.get("steps") if isinstance(data, dict) else data

    # Rebuild every step field by field, so a badly-shaped answer can't break the UI.
    steps = []
    for raw in raw_steps or []:
        if not isinstance(raw, dict):
            continue
        commands = []
        for command in (str(c).strip() for c in (raw.get("commands") or [])):
            if command:
                commands.append({"cmd": command, "warning": flag_risky(command)})
        steps.append({
            "title": str(raw.get("title") or "Step"),
            "explanation": str(raw.get("explanation") or ""),
            "commands": commands,
            "expected": str(raw.get("expected") or ""),
            "notes": str(raw.get("notes") or ""),
        })

    if not steps:
        raise LLMError("Gemini did not return any steps. Please try again.")
    repo.plans[key] = {"steps": steps}
    return repo.plans[key]



def answer_doubt(repo, step: dict, os_name: str, level: str, question: str, error_text: str) -> str:
    # Doubts are chat-like, so we use Groq (fast). The repo context is small
    # (README and dependency files come first) to keep the call quick.
    context = pack_context(repo.files, budget=20_000, per_file=3_000)
    messages = [
        ("system", prompts.doubt_system_prompt(level, os_name)),
        ("user", prompts.doubt_user_prompt(step, context, question, error_text)),
    ]
    return groq_client.chat(messages)