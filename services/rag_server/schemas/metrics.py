"""Pydantic models for system metrics and configuration API.

Provides comprehensive visibility into:
- Models used (LLM, embedding, reranking, evaluation)
- Retrieval configuration (hybrid search, BM25, vector, reranking)
- System overview

Note: Evaluation-specific schemas have been moved to schemas/eval.py. The
run-level config snapshot lives in the eval service (evals/schemas/results.py),
which is the only thing that builds one.
"""

from datetime import UTC, datetime
from typing import Optional
from pydantic import BaseModel, Field

from infrastructure.config.models_config import ExecutionBoundary


# ============================================================================
# Model Information Models
# ============================================================================

class ModelSize(BaseModel):
    """Model size information."""
    parameters: Optional[str] = Field(None, description="Number of parameters (e.g., '4B', '22M')")
    disk_size_mb: Optional[float] = Field(None, description="Size on disk in MB (for local models)")
    context_window: Optional[int] = Field(None, description="Maximum context window in tokens")


class ModelInfo(BaseModel):
    """Detailed information about a model.

    `execution_boundary` replaces the former `is_local` boolean: a two-valued
    flag cannot separate "a host we run" from "the customer's own AWS account"
    from "a vendor API", and calling Bedrock "not local" is exactly as
    misleading as calling it local. `None` means the active model definition
    declares no boundary — unknown, never "local" — and every consumer must
    treat unknown as outside the trust boundary.
    """
    name: str = Field(..., description="Model name/identifier")
    provider: str = Field(..., description="Model provider (e.g., 'Tei', 'HuggingFace', 'Anthropic')")
    model_type: str = Field(..., description="Type: 'llm', 'embedding', 'reranker', 'eval'")
    execution_boundary: Optional[ExecutionBoundary] = Field(
        ...,
        description=(
            "Where this model actually executes: 'customer_managed', 'aws_managed', "
            "'third_party', or null when the config declares no boundary (unknown — "
            "must be treated as outside the trust boundary)"
        ),
    )
    size: Optional[ModelSize] = Field(None, description="Model size information")
    reference_url: Optional[str] = Field(None, description="URL to model documentation/card")
    description: Optional[str] = Field(None, description="Brief model description")
    status: str = Field("unknown", description="Status: 'loaded', 'available', 'unavailable', 'unknown'")


class ModelsConfig(BaseModel):
    """All models used in the RAG system."""
    llm: ModelInfo = Field(..., description="Language model for inference")
    embedding: ModelInfo = Field(..., description="Embedding model for vector search")
    reranker: Optional[ModelInfo] = Field(None, description="Reranking model (if enabled)")
    eval: Optional[ModelInfo] = Field(None, description="Evaluation model (for running evals)")


# ============================================================================
# Retrieval Configuration Models
# ============================================================================

class VectorSearchConfig(BaseModel):
    """Vector search configuration."""
    enabled: bool = Field(True, description="Vector search is always enabled")
    chunk_size: int = Field(..., description="Chunk size in tokens")
    chunk_overlap: int = Field(..., description="Chunk overlap in tokens")
    vector_store: str = Field("pgvector", description="Vector database used")
    index_type: str = Field("diskann", description="Vector index type (pgvectorscale StreamingDiskANN)")
    table_name: str = Field("document_chunks", description="Table holding chunk embeddings")


class BM25Config(BaseModel):
    """BM25 sparse retrieval configuration."""
    enabled: bool = Field(..., description="Whether BM25 is enabled")
    description: str = Field(
        "Sparse text matching using BM25 algorithm",
        description="What BM25 does"
    )
    strengths: list[str] = Field(
        default_factory=lambda: [
            "Exact keyword matching",
            "IDs and abbreviations",
            "Names and specific terms"
        ],
        description="What BM25 excels at"
    )


class HybridSearchConfig(BaseModel):
    """Hybrid search (BM25 + Vector) configuration."""
    enabled: bool = Field(..., description="Whether hybrid search is enabled")
    bm25: BM25Config = Field(..., description="BM25 configuration")
    vector: VectorSearchConfig = Field(..., description="Vector search configuration")
    fusion_method: str = Field("reciprocal_rank_fusion", description="Method to combine results")
    rrf_k: int = Field(..., description="RRF constant (optimal: 60 per research)")
    description: str = Field(
        "Combines BM25 sparse retrieval with dense vector search using Reciprocal Rank Fusion",
        description="What hybrid search does"
    )
    research_reference: str = Field(
        "https://www.pinecone.io/learn/hybrid-search-intro/",
        description="Reference to hybrid search research"
    )
    improvement_claim: str = Field(
        "48% improvement in retrieval quality (Pinecone benchmark)",
        description="Claimed improvement from research"
    )


class ContextualRetrievalConfig(BaseModel):
    """Contextual retrieval configuration (Anthropic method)."""
    enabled: bool = Field(..., description="Whether contextual retrieval is enabled")
    description: str = Field(
        "LLM generates 1-2 sentence context per chunk before embedding",
        description="What contextual retrieval does"
    )
    research_reference: str = Field(
        "https://www.anthropic.com/news/contextual-retrieval",
        description="Reference to Anthropic's contextual retrieval paper"
    )
    improvement_claim: str = Field(
        "49% reduction in retrieval failures; 67% with hybrid search + reranking",
        description="Claimed improvement from research"
    )
    performance_impact: str = Field(
        "~85% slower preprocessing (LLM call per chunk)",
        description="Performance impact"
    )


class RerankerConfig(BaseModel):
    """Reranker configuration."""
    enabled: bool = Field(..., description="Whether reranking is enabled")
    model: Optional[str] = Field(None, description="Reranker model name")
    top_n: Optional[int] = Field(None, description="Number of results after reranking")
    description: str = Field(
        "Cross-encoder model that re-scores retrieved chunks for relevance",
        description="What reranking does"
    )
    reference_url: Optional[str] = Field(
        "https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Model reference URL"
    )


class RetrievalConfig(BaseModel):
    """Complete retrieval pipeline configuration."""
    retrieval_top_k: int = Field(..., description="Initial number of chunks to retrieve")
    final_top_n: int = Field(..., description="Final number of chunks after reranking")
    hybrid_search: HybridSearchConfig = Field(..., description="Hybrid search configuration")
    contextual_retrieval: ContextualRetrievalConfig = Field(..., description="Contextual retrieval config")
    reranker: RerankerConfig = Field(..., description="Reranker configuration")
    pipeline_description: str = Field(
        "Query -> Hybrid Retrieval (BM25 + Vector + RRF) -> Reranking -> Top-N Selection -> LLM",
        description="Retrieval pipeline flow"
    )


# ============================================================================
# Evaluation Models (Latency, Cost)
# ============================================================================


class LatencyMetrics(BaseModel):
    """Query latency statistics from an evaluation run.

    Tracks response times to help balance accuracy vs speed.
    """

    avg_query_time_ms: float = Field(..., description="Average query time in milliseconds")
    p50_query_time_ms: float = Field(..., description="Median (P50) query time in milliseconds")
    p95_query_time_ms: float = Field(..., description="95th percentile query time in milliseconds")
    min_query_time_ms: float = Field(..., description="Minimum query time in milliseconds")
    max_query_time_ms: float = Field(..., description="Maximum query time in milliseconds")
    total_queries: int = Field(..., description="Total number of queries measured")


class CostMetrics(BaseModel):
    """Token usage and cost tracking for an evaluation run.

    Enables cost-aware model selection and budgeting.
    """

    total_input_tokens: int = Field(..., description="Total input tokens across all queries")
    total_output_tokens: int = Field(..., description="Total output tokens across all queries")
    total_tokens: int = Field(..., description="Total tokens (input + output)")
    estimated_cost_usd: float = Field(..., description="Estimated total cost in USD")
    cost_per_query_usd: float = Field(..., description="Average cost per query in USD")


# ============================================================================
# System Overview Model
# ============================================================================


class SystemMetrics(BaseModel):
    """Complete system metrics and configuration overview.

    Note: For evaluation-specific schemas, see schemas/eval.py.
    """

    # System info
    system_name: str = Field("ragbench", description="System name")
    version: str = Field("1.0.0", description="System version")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC), description="Response timestamp")

    # Models
    models: ModelsConfig = Field(..., description="All models configuration")

    # Retrieval
    retrieval: RetrievalConfig = Field(..., description="Retrieval pipeline configuration")

    # Document stats
    document_count: int = Field(..., description="Number of indexed documents")
    chunk_count: int = Field(..., description="Total number of chunks")

    # Health
    health_status: str = Field("healthy", description="Overall system health")
    component_status: dict[str, str] = Field(
        default_factory=dict,
        description="Status of each component (postgres, bm25, vector_store, tei)"
    )
