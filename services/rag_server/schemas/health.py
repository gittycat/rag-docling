from pydantic import BaseModel


class ModelsInfoResponse(BaseModel):
    llm_model: str
    llm_hosting: str
    embedding_model: str
    reranker_model: str | None
    reranker_enabled: bool


class ConfigResponse(BaseModel):
    max_upload_size_mb: int
