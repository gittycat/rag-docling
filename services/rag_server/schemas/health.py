from pydantic import BaseModel

from infrastructure.config.models_config import ExecutionBoundary


class ModelsInfoResponse(BaseModel):
    llm_model: str
    llm_provider: str
    # Replaced the old llm_hosting 'local'/'cloud' string, which was inferred
    # from the provider name and so could not express aws_managed. null means
    # the config declares no boundary — unknown, never 'local'.
    llm_execution_boundary: ExecutionBoundary | None
    embedding_model: str
    reranker_model: str | None
    reranker_enabled: bool
    # None means unpriced: nobody has supplied rates for this model. It is not
    # the same as zero, and consumers must not render it as free — a self-hosted
    # model priced at $0 by default is what made self-hosting win on cost by
    # assumption. Set MODEL_PRICE_OVERRIDES to publish a measured rate.
    cost_per_1m_input_tokens: float | None
    cost_per_1m_output_tokens: float | None
    cost_rate_source: str = "unpriced"  # "table" | "environment" | "unpriced"
    # Hash of the rendered prompts. Consumers key caches and run provenance on it;
    # null means an older server that does not report prompts, which is not the
    # same as "the prompts are unchanged".
    prompt_fingerprint: str | None = None


class ConfigResponse(BaseModel):
    max_upload_size_mb: int
