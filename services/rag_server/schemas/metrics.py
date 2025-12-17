"""Pydantic models for RAG metrics and configuration API.

Provides comprehensive visibility into:
- Models used (LLM, embedding, reranking, evaluation)
- Retrieval configuration (hybrid search, BM25, vector, reranking)
- Evaluation metrics definitions and historical results
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================================
# Model Information Models
# ============================================================================

class ModelSize(BaseModel):
    """Model size information."""
    parameters: Optional[str] = Field(None, description="Number of parameters (e.g., '4B', '22M')")
    disk_size_mb: Optional[float] = Field(None, description="Size on disk in MB (for local models)")
    context_window: Optional[int] = Field(None, description="Maximum context window in tokens")


class ModelInfo(BaseModel):
    """Detailed information about a model."""
    name: str = Field(..., description="Model name/identifier")
    provider: str = Field(..., description="Model provider (e.g., 'Ollama', 'HuggingFace', 'Anthropic')")
    model_type: str = Field(..., description="Type: 'llm', 'embedding', 'reranker', 'eval'")
    is_local: bool = Field(..., description="Whether model runs locally")
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
    vector_store: str = Field("ChromaDB", description="Vector database used")
    collection_name: str = Field("documents", description="Collection name")


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
# Evaluation Metrics Models
# ============================================================================

class MetricDefinition(BaseModel):
    """Definition of an evaluation metric."""
    name: str = Field(..., description="Metric name")
    category: str = Field(..., description="Category: 'retrieval', 'generation', 'safety'")
    description: str = Field(..., description="What the metric measures")
    threshold: float = Field(..., description="Pass/fail threshold")
    interpretation: str = Field(..., description="How to interpret the score")
    reference_url: Optional[str] = Field(None, description="Documentation URL")


class MetricResult(BaseModel):
    """Result for a single metric."""
    metric_name: str = Field(..., description="Metric name")
    score: float = Field(..., description="Score (0-1)")
    passed: bool = Field(..., description="Whether score meets threshold")
    threshold: float = Field(..., description="Threshold used")
    reason: Optional[str] = Field(None, description="Explanation for the score")


class TestCaseResult(BaseModel):
    """Result for a single test case."""
    test_id: str = Field(..., description="Test case identifier")
    question: str = Field(..., description="Question asked")
    expected_answer: Optional[str] = Field(None, description="Expected answer")
    actual_answer: str = Field(..., description="RAG system answer")
    metrics: list[MetricResult] = Field(..., description="Per-metric results")
    passed: bool = Field(..., description="Whether all metrics passed")
    retrieval_context_count: int = Field(..., description="Number of retrieved chunks")


class EvaluationRun(BaseModel):
    """Complete evaluation run results."""
    run_id: str = Field(..., description="Unique run identifier")
    timestamp: datetime = Field(..., description="When evaluation was run")
    framework: str = Field("DeepEval", description="Evaluation framework used")
    eval_model: str = Field(..., description="Model used for evaluation")

    # Summary statistics
    total_tests: int = Field(..., description="Total number of test cases")
    passed_tests: int = Field(..., description="Number of passing tests")
    pass_rate: float = Field(..., description="Percentage of tests passed")

    # Per-metric averages
    metric_averages: dict[str, float] = Field(..., description="Average score per metric")
    metric_pass_rates: dict[str, float] = Field(..., description="Pass rate per metric")

    # Configuration snapshot
    retrieval_config: Optional[dict] = Field(None, description="Retrieval config at time of eval")

    # Detailed results (optional, can be large)
    test_cases: Optional[list[TestCaseResult]] = Field(None, description="Detailed per-test results")

    # Notes
    notes: Optional[str] = Field(None, description="Notes about this evaluation run")


class EvaluationHistory(BaseModel):
    """Historical evaluation runs for comparison."""
    runs: list[EvaluationRun] = Field(..., description="List of evaluation runs")
    comparison_metrics: list[str] = Field(
        default_factory=lambda: [
            "contextual_precision",
            "contextual_recall",
            "faithfulness",
            "answer_relevancy",
            "hallucination"
        ],
        description="Metrics to compare across runs"
    )


class MetricTrend(BaseModel):
    """Trend data for a single metric across evaluations."""
    metric_name: str = Field(..., description="Metric name")
    values: list[float] = Field(..., description="Score values over time")
    timestamps: list[datetime] = Field(..., description="Timestamps for each value")
    trend_direction: str = Field(..., description="'improving', 'declining', 'stable'")
    latest_value: float = Field(..., description="Most recent score")
    average_value: float = Field(..., description="Average across all runs")


class EvaluationSummary(BaseModel):
    """Summary of evaluation metrics with trends."""
    latest_run: Optional[EvaluationRun] = Field(None, description="Most recent evaluation")
    total_runs: int = Field(..., description="Total number of evaluation runs")
    metric_trends: list[MetricTrend] = Field(..., description="Trends per metric")
    best_run: Optional[EvaluationRun] = Field(None, description="Best performing run")
    configuration_impact: Optional[dict] = Field(
        None,
        description="Analysis of how config changes affected metrics"
    )


# ============================================================================
# System Overview Model (combines everything)
# ============================================================================

class SystemMetrics(BaseModel):
    """Complete system metrics and configuration overview."""

    # System info
    system_name: str = Field("RAG-Docling", description="System name")
    version: str = Field("1.0.0", description="System version")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")

    # Models
    models: ModelsConfig = Field(..., description="All models configuration")

    # Retrieval
    retrieval: RetrievalConfig = Field(..., description="Retrieval pipeline configuration")

    # Evaluation
    evaluation_metrics: list[MetricDefinition] = Field(..., description="Available evaluation metrics")
    latest_evaluation: Optional[EvaluationRun] = Field(None, description="Most recent evaluation results")

    # Document stats
    document_count: int = Field(..., description="Number of indexed documents")
    chunk_count: int = Field(..., description="Total number of chunks")

    # Health
    health_status: str = Field("healthy", description="Overall system health")
    component_status: dict[str, str] = Field(
        default_factory=dict,
        description="Status of each component (chromadb, redis, ollama)"
    )
