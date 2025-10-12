from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sse_starlette.sse import EventSourceResponse
from pathlib import Path
import httpx
import asyncio
import json
import markdown
import bleach
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

def markdown_to_html(text: str) -> str:
    """Convert markdown text to HTML with proper formatting and sanitization."""
    md = markdown.Markdown(extensions=['nl2br', 'fenced_code'])
    html = md.convert(text)

    allowed_tags = [
        'p', 'br', 'strong', 'em', 'u', 'code', 'pre',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'ul', 'ol', 'li',
        'blockquote',
        'a', 'span', 'div'
    ]

    allowed_attributes = {
        'a': ['href', 'title'],
        'code': ['class'],
        'pre': ['class']
    }

    sanitized_html = bleach.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attributes,
        strip=True
    )

    return sanitized_html

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="home.html"
    )

@app.post("/")
async def home_search(
    request: Request,
    query: str = Form(...),
    session_id: str = Form(None)
):
    try:
        # Call RAG server with session_id
        # Timeout set to 120s to handle first-time reranker model download (~80MB)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{RAG_SERVER_URL}/query",
                json={"query": query, "session_id": session_id},
                timeout=120.0
            )
            response.raise_for_status()
            result = response.json()

        answer_text = result.get("answer", "No answer generated")
        answer_html = markdown_to_html(answer_text)
        returned_session_id = result.get("session_id")

        # Get full chat history
        chat_history = []
        if returned_session_id:
            try:
                async with httpx.AsyncClient() as client:
                    history_response = await client.get(
                        f"{RAG_SERVER_URL}/chat/history/{returned_session_id}",
                        timeout=10.0
                    )
                    if history_response.status_code == 200:
                        history_data = history_response.json()
                        chat_history = history_data.get("messages", [])
            except Exception as e:
                print(f"Error fetching chat history: {e}")

        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "query": query,
                "answer": answer_html,
                "sources": result.get("sources", []),
                "session_id": returned_session_id,
                "chat_history": chat_history
            }
        )
    except httpx.HTTPError as e:
        # Handle connection errors gracefully
        return templates.TemplateResponse(
            request=request,
            name="home.html",
            context={
                "query": query,
                "answer": f"Error connecting to RAG server: {str(e)}",
                "sources": [],
                "session_id": session_id,
                "chat_history": []
            }
        )

# Legacy endpoint for backward compatibility
@app.post("/search")
async def search(request: Request, query: str = Form(...), session_id: str = Form(None)):
    return await home_search(request, query, session_id)

@app.post("/new-chat")
async def new_chat(request: Request, session_id: str = Form(...)):
    """Clear chat history and redirect to home"""
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{RAG_SERVER_URL}/chat/clear",
                json={"session_id": session_id},
                timeout=10.0
            )
    except Exception as e:
        print(f"Error clearing chat: {e}")

    return RedirectResponse(url="/", status_code=303)

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
        request=request,
        name="admin.html",
        context={"documents": documents}
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

            return {
                "status": "queued",
                "batch_id": result.get("batch_id"),
                "tasks": result.get("tasks", [])
            }

    except Exception as e:
        print(f"Upload error: {type(e).__name__}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response status: {e.response.status_code}")
            print(f"Response body: {e.response.text}")
        return {
            "status": "error",
            "message": str(e)
        }

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
        request=request,
        name="upload_progress.html",
        context={"batch_id": batch_id}
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
    return templates.TemplateResponse(
        request=request,
        name="about.html"
    )

@app.get("/health")
async def health():
    return {"status": "healthy"}
