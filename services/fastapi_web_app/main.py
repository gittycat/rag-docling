from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import httpx
import os

app = FastAPI(title="RAG System Web Interface")

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Setup templates
templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

# RAG server URL
RAG_SERVER_URL = os.getenv("RAG_SERVER_URL", "http://rag-server:8001")

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request, "home.html")

@app.post("/search")
async def search(request: Request, query: str = Form(...)):
    """
    Handle search requests by querying the RAG server
    and displaying results to the user.
    """
    try:
        # Call RAG server
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{RAG_SERVER_URL}/query",
                json={"query": query},
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()

        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "query": query,
                "answer": result.get("answer", "No answer generated"),
                "sources": result.get("sources", [])
            }
        )
    except httpx.HTTPError as e:
        # Handle connection errors gracefully
        return templates.TemplateResponse(
            request,
            "results.html",
            {
                "query": query,
                "answer": f"Error connecting to RAG server: {str(e)}",
                "sources": []
            }
        )

@app.get("/health")
async def health():
    return {"status": "healthy"}
