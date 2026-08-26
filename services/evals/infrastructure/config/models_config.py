"""Model configuration management using Pydantic for type safety and validation."""

from enum import Enum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from infrastructure.settings import get_api_key_for_provider


class ExecutionBoundary(str, Enum):
    """Where a resolved model endpoint actually executes.

    This is a property of the *endpoint*, never inferred from `provider`: an
    OpenAI-compatible transport can point at a vLLM container we run or at
    api.openai.com, and only the config author knows which. Mirrored verbatim in
    services/rag_server/infrastructure/config/models_config.py — the two services
    share no package (same duplication as LLMProvider).

    A model definition that declares no boundary is *unknown*, and unknown fails
    closed: it is never treated as inside the boundary.
    """

    CUSTOMER_MANAGED = "customer_managed"  # a host/VPC we run: local Docker, our EC2, our K8s
    AWS_MANAGED = "aws_managed"  # Bedrock/SageMaker — inside the customer's AWS boundary
    THIRD_PARTY = "third_party"  # OpenAI, Anthropic, any vendor-hosted API


class LLMConfig(BaseModel):
    """Configuration for the main LLM."""

    provider: str
    model: str
    base_url: str | None = None
    timeout: int = 120
    api_key: str | None = None
    requires_api_key: bool = False
    execution_boundary: ExecutionBoundary | None = None

    @field_validator("model")
    @classmethod
    def model_must_exist(cls, v: str) -> str:
        """Validate that model name is not empty."""
        if not v or not v.strip():
            raise ValueError("LLM model name is required and cannot be empty")
        return v

    def validate_provider_requirements(self) -> None:
        """Validate that required fields are present for the selected provider."""
        if self.requires_api_key and not self.api_key:
            raise ValueError(
                f"API key is required for provider '{self.provider}'. "
                f"Mount /run/secrets/{self.provider.upper()}_API_KEY."
            )


class EmbeddingConfig(BaseModel):
    """Configuration for the embedding model."""

    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    requires_api_key: bool = False
    # TEI-only: mirrors rag_server's EmbeddingConfig so config.yml's embedding
    # entry validates identically in both services.
    query_instruction: str | None = None
    text_instruction: str | None = None
    timeout: float | None = None
    execution_boundary: ExecutionBoundary | None = None

    @field_validator("model")
    @classmethod
    def model_must_exist(cls, v: str) -> str:
        """Validate that model name is not empty."""
        if not v or not v.strip():
            raise ValueError("Embedding model name is required and cannot be empty")
        return v

    def validate_provider_requirements(self) -> None:
        """Validate that required fields are present for the selected provider."""
        if self.requires_api_key and not self.api_key:
            raise ValueError(
                f"API key is required for embedding provider '{self.provider}'. "
                f"Mount /run/secrets/{self.provider.upper()}_API_KEY."
            )


class EvalModelConfig(BaseModel):
    """Configuration for an evaluation model (without settings)."""

    provider: str
    model: str
    # base_url/timeout mirror LLMConfig: a judge endpoint is addressable the same
    # way an inference endpoint is, and a self-hosted judge is unreachable without
    # base_url. They used to be silently dropped here.
    base_url: str | None = None
    timeout: int = 120
    api_key: str | None = None
    requires_api_key: bool = False
    execution_boundary: ExecutionBoundary | None = None

    @field_validator("model")
    @classmethod
    def model_must_exist(cls, v: str) -> str:
        """Validate that model name is not empty."""
        if not v or not v.strip():
            raise ValueError("Eval model name is required and cannot be empty")
        return v

    def validate_provider_requirements(self) -> None:
        """Validate that required fields are present for the selected provider."""
        if self.requires_api_key and not self.api_key:
            raise ValueError(
                f"API key is required for eval provider '{self.provider}'. "
                f"Mount /run/secrets/{self.provider.upper()}_API_KEY."
            )


class ScoringSettings(BaseModel):
    """Weighted-score objective weights and normalization thresholds.

    These decide what the headline number means. A latency-sensitive deployment
    and a cost-sensitive one need different thresholds, so they belong in
    config.yml rather than being constants in the runner.
    """

    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "accuracy": 0.30,
            "faithfulness": 0.20,
            "citation": 0.20,
            # Claim-level grounding: reported, not scored, until an operator
            # raises it. See config.yml's eval.scoring block.
            "groundedness": 0.0,
            "retrieval": 0.15,
            "cost": 0.10,
            "latency": 0.05,
        }
    )
    # Latency at or above the threshold normalizes to 0.0, 0 ms to 1.0. Separate
    # per tier: end-to-end pays retrieval and ingestion cost that generation does not.
    latency_threshold_ms_generation: float = 5_000
    latency_threshold_ms_end_to_end: float = 30_000
    # Cost per query at or above this normalizes to 0.0 (USD)
    max_cost_per_query_usd: float = 0.10

    @field_validator("weights")
    @classmethod
    def weights_must_be_non_negative(cls, v: dict[str, float]) -> dict[str, float]:
        negative = [k for k, w in v.items() if w < 0]
        if negative:
            raise ValueError(f"Objective weights cannot be negative: {negative}")
        if not v or all(w == 0 for w in v.values()):
            raise ValueError("At least one objective weight must be greater than zero")
        return v


class EvalSettings(BaseModel):
    """Evaluation settings (non-model-specific)."""

    citation_scope: Literal["retrieved", "explicit"] = "retrieved"
    citation_format: Literal["numeric"] = "numeric"
    abstention_phrases: list[str] = Field(
        default_factory=lambda: [
            "I don't have enough information to answer this question.",
            "I do not have enough information to answer this question.",
            "I don't have enough information to answer the question.",
            "I do not have enough information to answer the question.",
            "Not enough information to answer.",
            "Insufficient information to answer.",
        ]
    )


class EvalConfig(BaseModel):
    """Combined evaluation configuration (model + settings)."""

    provider: str
    model: str
    base_url: str | None = None
    timeout: int = 120
    api_key: str | None = None
    requires_api_key: bool = False
    execution_boundary: ExecutionBoundary | None = None
    citation_scope: Literal["retrieved", "explicit"] = "retrieved"
    citation_format: Literal["numeric"] = "numeric"
    abstention_phrases: list[str] = Field(
        default_factory=lambda: [
            "I don't have enough information to answer this question.",
            "I do not have enough information to answer this question.",
            "I don't have enough information to answer the question.",
            "I do not have enough information to answer the question.",
            "Not enough information to answer.",
            "Insufficient information to answer.",
        ]
    )
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)

    @field_validator("model")
    @classmethod
    def model_must_exist(cls, v: str) -> str:
        """Validate that model name is not empty."""
        if not v or not v.strip():
            raise ValueError("Eval model name is required and cannot be empty")
        return v

    def validate_provider_requirements(self) -> None:
        """Validate that required fields are present for the selected provider."""
        if self.requires_api_key and not self.api_key:
            raise ValueError(
                f"API key is required for eval provider '{self.provider}'. "
                f"Mount /run/secrets/{self.provider.upper()}_API_KEY."
            )


class RerankerModelConfig(BaseModel):
    """Configuration for a reranker model (without enabled flag)."""

    model: str
    top_n: int = 5


class RerankerSettings(BaseModel):
    """Reranker settings (non-model-specific)."""

    enabled: bool = True


class RerankerConfig(BaseModel):
    """Combined reranker configuration (model + settings)."""

    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_n: int = 5


class RetrievalConfig(BaseModel):
    """Configuration for retrieval settings."""

    top_k: int = 10
    enable_hybrid_search: bool = True
    rrf_k: int = 60
    enable_contextual_retrieval: bool = False


class CitationInstructions(BaseModel):
    """Citation instruction templates by format."""

    numeric: str = (
        "\n- Add numeric citations in square brackets like [1], [2] that map to the "
        "order of context chunks provided above."
    )


class PromptConfig(BaseModel):
    """Configuration for RAG pipeline prompts."""

    system: str = (
        "You are a professional assistant providing accurate answers based on document context. "
        "Be direct and concise. Avoid conversational fillers like 'Let me explain', 'Okay', 'Well', or 'Sure'. "
        "Start responses immediately with the answer. "
        "Use bullet points for lists when appropriate."
    )
    context: str = (
        "Context from retrieved documents:\n"
        "{context_str}\n\n"
        "Instructions:\n"
        "- Answer using ONLY the context provided above\n"
        "- If the context does not contain sufficient information, respond: \"I don't have enough information to answer this question.\"\n"
        "- Never use prior knowledge or make assumptions beyond what is explicitly stated\n"
        "- Be specific and cite details from the context when relevant\n"
        "- Use citations consistently when referencing facts{citation_instructions}\n"
        "- Previous conversation context is available for reference\n\n"
        "Provide a direct, accurate answer based on the context:"
    )
    citation_instructions: CitationInstructions = Field(default_factory=CitationInstructions)
    condense: str | None = None  # None = use LlamaIndex default
    contextual_prefix: str = (
        "Document: {document_name} ({document_type})\n\n"
        "Chunk content:\n"
        "{chunk_preview}\n\n"
        "Provide a concise 1-2 sentence context for this chunk, explaining what document it's from and what topic it discusses.\n"
        'Format: "This section from [document/topic] discusses [specific topic/concept]."\n\n'
        "Context (1-2 sentences only):"
    )


class ActiveModels(BaseModel):
    """Active model selection."""

    inference: str
    embedding: str
    eval: str
    reranker: str


class ModelDefinitions(BaseModel):
    """All available model definitions."""

    inference: dict[str, dict[str, Any]]
    embedding: dict[str, dict[str, Any]]
    eval: dict[str, dict[str, Any]]
    reranker: dict[str, dict[str, Any]]


# Boundaries a confidential corpus may be processed in. An allow-list, not a
# deny-list: anything not named here (including an endpoint that declares no
# boundary at all) is refused.
DEFAULT_ALLOWED_JUDGE_BOUNDARIES: frozenset[ExecutionBoundary] = frozenset(
    {ExecutionBoundary.CUSTOMER_MANAGED, ExecutionBoundary.AWS_MANAGED}
)


class DataPolicyConfig(BaseModel):
    """Where this deployment's corpus content is allowed to be processed.

    Deliberately independent of `pii.enabled`. Commercially confidential content
    need not contain a single PII entity, and masking is not the relevant control
    for it — nothing in the eval path is masked anyway: judge prompts embed
    retrieved chunks and generated answers verbatim (evals/judges/llm_judge.py),
    so an eval run ships more corpus content to the judge than a normal query
    ships to the generation LLM.
    """

    # Default true: an operator who has said nothing has not said "public".
    corpus_confidential: bool = True
    allowed_judge_boundaries: set[ExecutionBoundary] = Field(
        default_factory=lambda: set(DEFAULT_ALLOWED_JUDGE_BOUNDARIES)
    )
    # The per-run escape hatch, and the only one. Distinct from corpus_confidential:
    # the production corpus can be confidential while the eval *dataset* is a public
    # HuggingFace benchmark or synthetic data, in which case judge egress leaks
    # nothing. This is what `pii.allow_cloud_judge` used to approximate.
    eval_dataset_is_public: bool = False


def enforce_judge_boundary(
    boundary: ExecutionBoundary | None,
    policy: DataPolicyConfig,
    judge_label: str,
) -> None:
    """Refuse a judge endpoint that would take confidential corpus content out of bounds.

    Called both at config load and at judge resolution, so the object the runtime
    actually calls is the object that was checked.
    """
    if not policy.corpus_confidential or policy.eval_dataset_is_public:
        return

    allowed = ", ".join(sorted(b.value for b in policy.allowed_judge_boundaries)) or "(none)"

    if boundary is None:
        raise ValueError(
            f"Judge '{judge_label}' declares no execution_boundary. An endpoint of "
            f"unknown boundary is treated as outside the trust boundary. Add "
            f"execution_boundary to its models.eval entry in config.yml (one of: "
            f"{', '.join(b.value for b in ExecutionBoundary)}), or set "
            f"data_policy.eval_dataset_is_public: true if the eval dataset is public "
            f"or synthetic."
        )

    if boundary not in policy.allowed_judge_boundaries:
        raise ValueError(
            f"Judge '{judge_label}' runs at execution boundary '{boundary.value}', which "
            f"data_policy.allowed_judge_boundaries does not permit ({allowed}). Judge "
            f"prompts carry retrieved chunks and answers verbatim and are never masked. "
            f"Point active.eval at an in-boundary judge, or set "
            f"data_policy.eval_dataset_is_public: true if the eval dataset holds no "
            f"confidential content."
        )


class PiiConfig(BaseModel):
    """The eval service's view of the rag-server `pii` block.

    Only the master toggle matters here. Note that it no longer gates judge
    egress — that moved to `data_policy`, because a confidential corpus and a
    PII-bearing corpus are not the same claim.
    """

    enabled: bool = False


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    """Locate config.yml, checking the Docker path then the development checkout."""
    if config_path is not None:
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        return config_path

    possible_paths = [
        Path("/app/config.yml"),  # Docker path
        Path(__file__).parent.parent.parent.parent.parent / "config.yml",  # Development path
    ]
    resolved = next((p for p in possible_paths if p.exists()), None)
    if resolved is None:
        raise FileNotFoundError(f"config.yml not found in standard locations: {possible_paths}")
    return resolved


def load_raw_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Parse config.yml with no validation or secret injection.

    For settings that have nothing to do with model providers. get_models_config()
    raises when the active provider's API key is absent, which must not decide
    whether an unrelated key like eval.abstention_phrases is honoured.
    """
    with open(resolve_config_path(config_path)) as f:
        return yaml.safe_load(f) or {}


class ModelsConfig(BaseModel):
    """Root configuration for all models and retrieval settings."""

    llm: LLMConfig
    embedding: EmbeddingConfig
    eval: EvalConfig
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    prompts: PromptConfig = Field(default_factory=PromptConfig)
    pii: PiiConfig = Field(default_factory=PiiConfig)
    data_policy: DataPolicyConfig = Field(default_factory=DataPolicyConfig)

    def validate_privacy_posture(self) -> None:
        """Refuse to judge a confidential corpus outside the permitted boundaries."""
        enforce_judge_boundary(
            self.eval.execution_boundary,
            self.data_policy,
            f"{self.eval.provider}/{self.eval.model}",
        )

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "ModelsConfig":
        """Load configuration from YAML file and inject secrets from /run/secrets.

        Args:
            config_path: Path to the models.yml file. If None, searches in standard locations.

        Returns:
            ModelsConfig instance with secrets injected.

        Raises:
            FileNotFoundError: If config file is not found.
            ValueError: If required secrets are missing or invalid.
        """
        config_path = resolve_config_path(config_path)

        # Load YAML config
        with open(config_path) as f:
            data = yaml.safe_load(f)

        # Check if using new format (with 'models' and 'active' sections)
        if "models" in data and "active" in data:
            # New format - resolve model references
            resolved_data = cls._resolve_model_references(data)
        else:
            # Legacy format - use as-is
            resolved_data = data

        # Inject API keys from secrets based on requires_api_key flag
        for key in ["llm", "embedding", "eval"]:
            if key in resolved_data and resolved_data[key].get("requires_api_key"):
                provider = resolved_data[key].get("provider")
                if provider:
                    api_key = get_api_key_for_provider(provider)
                    if api_key:
                        resolved_data[key]["api_key"] = api_key

        # Create and validate config
        config = cls(**resolved_data)

        # Run provider-specific validations
        config.llm.validate_provider_requirements()
        config.embedding.validate_provider_requirements()
        config.eval.validate_provider_requirements()
        config.validate_privacy_posture()

        return config

    @staticmethod
    def _resolve_model_references(data: dict[str, Any]) -> dict[str, Any]:
        """Resolve model references from new config format.

        Args:
            data: Raw YAML data with 'models' and 'active' sections

        Returns:
            Resolved configuration data in legacy format

        Raises:
            ValueError: If referenced model is not defined
        """
        models = data.get("models", {})
        active = data.get("active", {})

        resolved = {}

        # Resolve Inference
        inference_key = active.get("inference")
        if inference_key and inference_key in models.get("inference", {}):
            resolved["llm"] = models["inference"][inference_key].copy()
        else:
            raise ValueError(
                f"Active inference model '{inference_key}' not found in models.inference definitions"
            )

        # Resolve Embedding
        embedding_key = active.get("embedding")
        if embedding_key and embedding_key in models.get("embedding", {}):
            resolved["embedding"] = models["embedding"][embedding_key].copy()
        else:
            raise ValueError(
                f"Active embedding model '{embedding_key}' not found in models.embedding definitions"
            )

        # Resolve Eval (merge model config with eval settings)
        eval_key = active.get("eval")
        if eval_key and eval_key in models.get("eval", {}):
            resolved["eval"] = models["eval"][eval_key].copy()
            # Merge eval settings if present
            if "eval" in data:
                eval_settings = data["eval"]
                if "citation_scope" in eval_settings:
                    resolved["eval"]["citation_scope"] = eval_settings["citation_scope"]
                if "citation_format" in eval_settings:
                    resolved["eval"]["citation_format"] = eval_settings["citation_format"]
                if "abstention_phrases" in eval_settings:
                    resolved["eval"]["abstention_phrases"] = eval_settings[
                        "abstention_phrases"
                    ]
                if "scoring" in eval_settings:
                    resolved["eval"]["scoring"] = eval_settings["scoring"]
        else:
            raise ValueError(
                f"Active eval model '{eval_key}' not found in models.eval definitions"
            )

        # Resolve Reranker (merge model config with reranker settings)
        reranker_key = active.get("reranker")
        if reranker_key and reranker_key in models.get("reranker", {}):
            resolved["reranker"] = models["reranker"][reranker_key].copy()
            # Merge reranker settings if present
            if "reranker" in data:
                reranker_settings = data["reranker"]
                if "enabled" in reranker_settings:
                    resolved["reranker"]["enabled"] = reranker_settings["enabled"]
        else:
            raise ValueError(
                f"Active reranker model '{reranker_key}' not found in models.reranker definitions"
            )

        # Copy retrieval settings unchanged
        if "retrieval" in data:
            resolved["retrieval"] = data["retrieval"]

        # Copy prompts unchanged
        if "prompts" in data:
            resolved["prompts"] = data["prompts"]

        # Copy pii unchanged (extra keys are ignored by PiiConfig)
        if "pii" in data:
            resolved["pii"] = data["pii"]

        # Copy data_policy unchanged
        if "data_policy" in data:
            resolved["data_policy"] = data["data_policy"]

        return resolved


class ModelsConfigManager:
    """
    Manages ModelsConfig lifecycle with lazy initialization.

    Supports dependency injection for testing and reconfiguration.
    """

    def __init__(self, config_path: str | Path | None = None):
        """
        Initialize models config manager.

        Args:
            config_path: Optional path to config file. If None, searches standard locations.
        """
        self._config_path = config_path
        self._config: ModelsConfig | None = None

    def get_config(self) -> ModelsConfig:
        """
        Get or load ModelsConfig.

        Lazy initialization - config is loaded on first access.

        Returns:
            ModelsConfig instance
        """
        if self._config is None:
            self._config = ModelsConfig.load(self._config_path)
        return self._config

    def reset(self) -> None:
        """Reset the config instance. Useful for testing."""
        self._config = None


# Global instance for backward compatibility
_default_manager = ModelsConfigManager()


def get_models_config(config_path: str | Path | None = None) -> ModelsConfig:
    """
    Get or load ModelsConfig using default manager.

    Backward-compatible convenience function.
    For dependency injection, use ModelsConfigManager directly.

    Args:
        config_path: Optional path to config file. Only used on first call.

    Returns:
        ModelsConfig instance
    """
    # Note: config_path only affects first call (lazy initialization)
    if _default_manager._config is None and config_path is not None:
        _default_manager._config_path = config_path
    return _default_manager.get_config()


def reset_models_config() -> None:
    """Reset the default models config. Useful for testing."""
    _default_manager.reset()
