from pydantic import BaseModel
from typing import Optional


# ============================================================================
# Existing Schemas (keep for backwards compatibility)
# ============================================================================

class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


class ClearSessionRequest(BaseModel):
    session_id: str


class ClearSessionResponse(BaseModel):
    status: str
    message: str


# ============================================================================
# New Session Management Schemas
# ============================================================================

class SessionMetadataResponse(BaseModel):
    """Single session metadata"""
    session_id: str
    title: str
    created_at: str
    updated_at: str
    is_archived: bool
    is_temporary: bool


class SessionListResponse(BaseModel):
    """List of sessions"""
    sessions: list[SessionMetadataResponse]
    total: int


class CreateSessionRequest(BaseModel):
    """Create new session"""
    is_temporary: bool = False
    title: Optional[str] = None
    first_message: Optional[str] = None  # Generate AI title from this message


class CreateSessionResponse(BaseModel):
    """New session creation result"""
    session_id: str
    title: str
    created_at: str
    is_temporary: bool


class DeleteSessionResponse(BaseModel):
    """Session deletion result"""
    status: str
    message: str


class ArchiveSessionResponse(BaseModel):
    """Session archive/unarchive result"""
    status: str
    message: str
