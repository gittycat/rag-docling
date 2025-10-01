from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from pathlib import Path
import httpx
import os
from typing import List

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

@app.get("/admin")
async def admin(request: Request):
    """
    Display admin page with list of indexed documents.
    Fetches document list from RAG server.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{RAG_SERVER_URL}/documents",
                timeout=10.0
            )
            response.raise_for_status()
            documents = response.json().get("documents", [])
    except httpx.HTTPError:
        # If server not available, show empty list
        documents = []

    return templates.TemplateResponse(
        request,
        "admin.html",
        {"documents": documents}
    )

@app.post("/admin/upload")
async def upload_documents(files: List[UploadFile] = File(...)):
    """
    Upload one or multiple documents to the RAG system.
    Files are forwarded to the RAG server for processing and indexing.
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Prepare files for upload
            upload_files = []
            for file in files:
                content = await file.read()
                upload_files.append(
                    ("files", (file.filename, content, file.content_type))
                )

            # Forward to RAG server
            response = await client.post(
                f"{RAG_SERVER_URL}/upload",
                files=upload_files
            )
            response.raise_for_status()
    except httpx.HTTPError:
        pass  # Silently fail for now

    # Redirect back to admin page
    return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete/{document_id}")
async def delete_document(request: Request, document_id: str):
    """
    Delete a document from the RAG system.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{RAG_SERVER_URL}/documents/{document_id}",
                timeout=10.0
            )
            response.raise_for_status()
    except httpx.HTTPError:
        pass  # Silently fail for now

    # Redirect back to admin page
    return RedirectResponse(url="/admin", status_code=303)

@app.get("/about")
async def about(request: Request):
    """Display about page with system information"""
    return templates.TemplateResponse(request, "about.html")

@app.get("/health")
async def health():
    return {"status": "healthy"}
