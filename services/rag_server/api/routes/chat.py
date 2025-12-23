import logging
from fastapi import APIRouter, HTTPException

from schemas.chat import ChatHistoryResponse, ClearSessionRequest, ClearSessionResponse
from pipelines.inference import get_chat_history, clear_session_memory

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/chat/history/{session_id}", response_model=ChatHistoryResponse)
async def get_session_history(session_id: str):
    """Get the full chat history for a session"""
    try:
        messages = get_chat_history(session_id)

        # Convert ChatMessage objects to dicts
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "role": msg.role.value if hasattr(msg.role, 'value') else str(msg.role),
                "content": msg.content
            })

        return ChatHistoryResponse(
            session_id=session_id,
            messages=formatted_messages
        )
    except Exception as e:
        logger.error(f"[CHAT_HISTORY] Error retrieving history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/clear", response_model=ClearSessionResponse)
async def clear_chat_session(request: ClearSessionRequest):
    """Clear the chat history for a session"""
    try:
        clear_session_memory(request.session_id)
        return ClearSessionResponse(
            status="success",
            message=f"Chat history cleared for session {request.session_id}"
        )
    except Exception as e:
        logger.error(f"[CHAT_CLEAR] Error clearing session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
