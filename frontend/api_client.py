# api_client.py
# ALL network code lives here. app.py (the UI) just calls these small
# functions and never deals with URLs or HTTP errors itself.

import os

import requests
from dotenv import load_dotenv

load_dotenv()

# Locally the backend runs on port 8000. When deployed, BACKEND_URL points to it.
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


class ApiError(Exception):
    """A problem with a friendly message that the UI can show directly."""


def _post(path: str, payload: dict, timeout: int = 180):
    try:
        response = requests.post(f"{BACKEND_URL}{path}", json=payload, timeout=timeout)
    except requests.exceptions.ConnectionError:
        raise ApiError("Can't reach the backend. Is it running? "
                       "Start it with: uvicorn backend.main:app --reload")
    except requests.exceptions.Timeout:
        raise ApiError("The backend took too long to answer. Please try again.")

    if response.status_code >= 400:
        # Our backend always sends {"detail": "friendly message"} for expected errors.
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = None
        raise ApiError(detail if isinstance(detail, str)
                       else f"The backend reported an error ({response.status_code}).")
    return response.json()


def analyze(url: str):
    return _post("/analyze", {"url": url}, timeout=300)  # cloning can be slow


def overview(repo_id: str, level: str):
    return _post("/overview", {"repo_id": repo_id, "level": level})


def chat(repo_id: str, level: str, question: str, history: list):
    return _post("/chat", {"repo_id": repo_id, "level": level,
                           "question": question, "history": history})



def summaries(repo_id: str, level: str):
    return _post("/summaries", {"repo_id": repo_id, "level": level}, timeout=300)["summaries"]



def diagram(repo_id: str, kind: str):
    return _post("/diagram", {"repo_id": repo_id, "kind": kind})["mermaid"]



def build_plan(repo_id: str, level: str, os_name: str):
    return _post("/build/plan", {"repo_id": repo_id, "level": level, "os": os_name})



def build_ask(repo_id: str, level: str, os_name: str, step: dict, question: str, error_text: str):
    payload = {
        "repo_id": repo_id, "level": level, "os": os_name,
        "question": question, "error_text": error_text,
        "step": {"title": step["title"], "explanation": step["explanation"],
                 "commands": [c["cmd"] for c in step["commands"]]},
    }
    return _post("/build/ask", payload)["answer"]


def rebuild_plan(repo_id: str, level: str):
    return _post("/rebuild/plan", {"repo_id": repo_id, "level": level})["order"]


def rebuild_step(repo_id: str, level: str, path: str):
    return _post("/rebuild/step", {"repo_id": repo_id, "level": level, "path": path})