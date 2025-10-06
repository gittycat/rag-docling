from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sse_starlette.sse import EventSourceResponse
from pathlib import Path
import httpx
import asyncio
import json
from typing import List
from env_config import get_required_env

app = FastAPI(title="RAG System Web Interface")

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

# Setup templates
templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

# RAG server URL
RAG_SERVER_URL = get_required_env("RAG_SERVER_URL")

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request, "home.html")

@app.post("/search")
async def search(request: Request, query: str = Form(...)):
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
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upload_files = []
            for file in files:
                content = await file.read()
                upload_files.append(
                    ("files", (file.filename, content, file.content_type))
                )

            response = await client.post(
                f"{RAG_SERVER_URL}/upload",
                files=upload_files
            )
            response.raise_for_status()
            result = response.json()
            batch_id = result.get("batch_id")

            if batch_id:
                return RedirectResponse(url=f"/admin/upload/progress/{batch_id}", status_code=303)
            else:
                return RedirectResponse(url="/admin", status_code=303)

    except Exception as e:
        print(f"Upload error: {type(e).__name__}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return RedirectResponse(url="/admin", status_code=303)

@app.post("/admin/delete/{document_id}")
async def delete_document(request: Request, document_id: str):
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

@app.get("/admin/upload/progress/{batch_id}")
async def upload_progress_page(request: Request, batch_id: str):
    return templates.TemplateResponse(
        request,
        "upload_progress.html",
        {"batch_id": batch_id}
    )

@app.get("/admin/upload/progress/{batch_id}/stream")
async def upload_progress_stream(batch_id: str):
    async def event_generator():
        try:
            while True:
                async with httpx.AsyncClient() as client:
                    try:
                        response = await client.get(
                            f"{RAG_SERVER_URL}/tasks/{batch_id}/status",
                            timeout=5.0
                        )
                        if response.status_code == 200:
                            data = response.json()
                            yield {
                                "event": "progress",
                                "data": json.dumps(data)
                            }

                            if data["completed"] >= data["total"]:
                                yield {
                                    "event": "complete",
                                    "data": json.dumps({"message": "All tasks completed"})
                                }
                                break
                        else:
                            yield {
                                "event": "error",
                                "data": json.dumps({"message": "Batch not found"})
                            }
                            break
                    except httpx.RequestError as e:
                        yield {
                            "event": "error",
                            "data": json.dumps({"message": f"Connection error: {str(e)}"})
                        }
                        break

                await asyncio.sleep(0.5)

        except asyncio.CancelledError:
            pass

    return EventSourceResponse(event_generator())

@app.get("/about")
async def about(request: Request):
    return templates.TemplateResponse(request, "about.html")

@app.get("/health")
async def health():
    return {"status": "healthy"}
