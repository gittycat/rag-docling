from pydantic import BaseModel


class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[dict]


class ClearSessionRequest(BaseModel):
    session_id: str


class ClearSessionResponse(BaseModel):
    status: str
    message: str
