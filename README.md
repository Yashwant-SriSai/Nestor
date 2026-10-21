# Nestor

Paste a public GitHub repo URL and get an overview, folder tree, diagrams,
file summaries, a chat that cites file and line numbers, and a step-by-step
guide to run it.

## Run locally (Windows PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # then put your real keys in .env
```

Start the backend and the frontend in two separate PowerShell windows (venv
activated in both, both opened in this folder):

```powershell
uvicorn backend.main:app --reload
```

```powershell
streamlit run frontend\app.py
```

## Keys

Create a Gemini key in Google AI Studio and a Groq key in the Groq console.
Put them in `.env` (never commit that file).

## Deploy to Render (two Web Services, set up in the Render dashboard)

Push this project to your own GitHub repo first. Then create two services in
Render ("New" > "Web Service" > connect the repo).

Backend service:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Environment: `GEMINI_API_KEY`, `GROQ_API_KEY`, `PYTHON_VERSION`

Frontend service:

- Build command: `pip install -r requirements.txt`
- Start command: `streamlit run frontend/app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
- Environment: `BACKEND_URL` (the backend service's public URL, no trailing slash), `PYTHON_VERSION`

Notes:

- Free services sleep when idle and restart often. After a restart the backend
  forgets analysed repos (they live in memory), so click "Analyze repo" again.
- Free instances have little memory. If the backend runs out of memory, lower
  `MAX_CHUNKS` and `MAX_REPO_SIZE_MB` in `backend/config.py`, or use a larger instance.
