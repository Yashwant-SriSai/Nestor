# main.py
# The FastAPI "front desk". Streamlit sends HTTP requests here; each route
# checks the input, calls the right module, and returns JSON. It holds almost
# no logic itself.
#
# Run from the project root (not from inside backend/):
#   uvicorn backend.main:app --reload

import uuid
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.indexing.chunker import chunk_all
from backend.agent import react_agent
from backend.indexing.hybrid import RepoIndex
from backend import explain_mode, repo_store
from backend.errors import AppError
from backend.ingestion.cloner import clone_repo, remove_dir
from backend.ingestion.filters import collect_files
from backend.ingestion.tree import build_tree
from backend.ingestion.validator import validate_github_url
from backend.build_mode import planner, rebuild

app = FastAPI(title="Nestor API")


@app.exception_handler(AppError)
async def handle_app_error(_request, exc: AppError):
    # Every expected problem becomes a clean {"detail": "message"} for the UI.
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


# Pydantic validates incoming JSON automatically. The max_length limits stop
# someone from sending an enormous request (input-validation guardrail).
class AnalyzeRequest(BaseModel):
    url: str = Field(max_length=300)


class OverviewRequest(BaseModel):
    repo_id: str = Field(max_length=40)
    level: Literal["beginner", "intermediate"] = "beginner"


@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    # validate -> clone -> filter -> tree -> chunk -> index. No LLM is involved here.
    try:
        clean_url = validate_github_url(req.url)
    except ValueError as exc:
        raise AppError(str(exc), 400)

    workdir, repo_dir, size_mb = clone_repo(clean_url)
    try:
        files, file_stats = collect_files(repo_dir)
    finally:
        # The untrusted clone is deleted as soon as we've read the text,
        # even if reading failed halfway.
        remove_dir(workdir)

    if not files:
        raise AppError("No readable text or code files were found in that repo.", 422)

    chunks, chunk_limit_hit = chunk_all(files)
    repo_id = uuid.uuid4().hex[:12]
    repo = repo_store.Repo(
        id=repo_id,
        url=clean_url,
        files=files,
        tree=build_tree(list(files)),
        index=RepoIndex(repo_id, chunks),  # builds both the Chroma and BM25 indexes
        stats={**file_stats, "size_mb": round(size_mb, 1),
               "chunks": len(chunks), "chunk_limit_hit": chunk_limit_hit},
    )
    repo_store.add(repo)
    return {"repo_id": repo.id, "url": repo.url, "tree": repo.tree, "stats": repo.stats}

@app.post("/overview")
def overview(req: OverviewRequest):
    # Gemini reads the key files and returns the overview JSON.
    return explain_mode.generate_overview(repo_store.get(req.repo_id), req.level)
class ChatMessage(BaseModel):
    # Literal limits the role to user/assistant, so a client can't inject a fake "system" message.
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class ChatRequest(OverviewRequest):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=30)
class DiagramRequest(BaseModel):
    repo_id: str = Field(max_length=40)
    kind: Literal["architecture", "dataflow"]
class PlanRequest(OverviewRequest):
    # The OS is required: commands differ between Windows, macOS and Linux.
    os: Literal["windows", "macos", "linux"]

class StepIn(BaseModel):
    # Only the parts of a step the model needs, with size limits.
    title: str = Field(max_length=300)
    explanation: str = Field(max_length=3000)
    commands: list[str] = Field(default_factory=list, max_length=20)


class DoubtRequest(PlanRequest):
    step: StepIn
    question: str = Field(default="", max_length=2000)
    error_text: str = Field(default="", max_length=6000)  # pasted terminal output

class RebuildStepRequest(OverviewRequest):
    path: str = Field(max_length=500)

@app.post("/chat")
def chat(req: ChatRequest):
    history = [m.model_dump() for m in req.history]
    return react_agent.ask(repo_store.get(req.repo_id), req.question, history, req.level)

@app.post("/diagram")
def diagram(req: DiagramRequest):
    return {"mermaid": explain_mode.generate_diagram(repo_store.get(req.repo_id), req.kind)}

@app.post("/build/plan")
def build_plan(req: PlanRequest):
    return planner.generate_plan(repo_store.get(req.repo_id), req.os, req.level)

@app.post("/build/ask")
def build_ask(req: DoubtRequest):
    if not req.question.strip() and not req.error_text.strip():
        raise AppError("Type a question or paste an error first.", 400)
    answer = planner.answer_doubt(repo_store.get(req.repo_id), req.step.model_dump(),
                                  req.os, req.level, req.question.strip(), req.error_text.strip())
    return {"answer": answer}

@app.post("/rebuild/plan")
def rebuild_plan(req: OverviewRequest):
    return {"order": rebuild.get_plan(repo_store.get(req.repo_id))}


@app.post("/rebuild/step")
def rebuild_step(req: RebuildStepRequest):
    step = rebuild.get_step(repo_store.get(req.repo_id), req.path, req.level)
    if step is None:
        raise AppError("That file is not part of the rebuild plan.", 404)
    return step