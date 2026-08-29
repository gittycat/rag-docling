from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    """Current toggleable settings."""

    contextual_retrieval_enabled: bool = Field(
        ..., description="Whether contextual retrieval is enabled for document ingestion"
    )
    chunk_size: int = Field(..., description="SentenceSplitter chunk size, in tokens")
    chunk_overlap: int = Field(..., description="SentenceSplitter chunk overlap, in tokens")


class SettingsUpdate(BaseModel):
    """Partial settings update. Only provided fields are updated."""

    contextual_retrieval_enabled: bool | None = Field(
        None, description="Enable or disable contextual retrieval"
    )
    chunk_size: int | None = Field(
        None, gt=0, description="SentenceSplitter chunk size, in tokens. Applies to documents ingested after the change; does not rechunk existing documents."
    )
    chunk_overlap: int | None = Field(
        None, ge=0, description="SentenceSplitter chunk overlap, in tokens"
    )
