from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

app = FastAPI(title="RAG System Web Interface")

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Setup templates
templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request, "home.html")

@app.post("/search")
async def search(request: Request, query: str = Form(...)):
    # Placeholder: will connect to RAG server later
    placeholder_answer = "This is a placeholder response. The RAG server integration will be implemented in Phase 3."
    placeholder_sources = []

    return templates.TemplateResponse(
        request,
        "results.html",
        {
            "query": query,
            "answer": placeholder_answer,
            "sources": placeholder_sources
        }
    )

@app.get("/health")
async def health():
    return {"status": "healthy"}
