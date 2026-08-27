"""Config display utilities for CLI tools."""

from infrastructure.config.models_config import get_models_config, effective_reranker_top_n


def print_config_banner(compact: bool = True) -> None:
    """Print RAG configuration banner.

    Args:
        compact: If True, show minimal config. If False, show full config.
    """
    try:
        config = get_models_config(validate_secrets=False)

        if compact:
            _print_compact_banner(config)
        else:
            _print_full_banner(config)
    except Exception as e:
        print(f"Warning: Failed to load config: {e}")


def _print_compact_banner(config) -> None:
    """Print compact config banner."""
    print("\nRAG Configuration")

    # LLM
    llm_info = f"{config.llm.provider}/{config.llm.model}"
    print(f"  LLM (inference):  {llm_info}")

    # Embedding
    embed_info = f"{config.embedding.provider}/{config.embedding.model}"
    print(f"  Embedding:        {embed_info}")

    # Reranker
    if config.reranker.enabled:
        top_n = effective_reranker_top_n(config.reranker.top_n, config.retrieval.top_k)
        rerank_info = f"{config.reranker.model} (top_n={top_n})"
        print(f"  Reranker:         {rerank_info}")
    else:
        print(f"  Reranker:         disabled")

    # Eval (if configured)
    if hasattr(config, 'eval') and config.eval:
        eval_info = f"{config.eval.provider}/{config.eval.model}"
        print(f"  Eval (judge):     {eval_info}")

    print("")


def _print_full_banner(config) -> None:
    """Print full config banner with all settings."""
    print("RAG Configuration (Full)")

    # LLM section
    print("\nLLM (Inference):")
    print(f"  Provider:    {config.llm.provider}")
    print(f"  Model:       {config.llm.model}")
    if config.llm.base_url:
        print(f"  Base URL:    {config.llm.base_url}")
    print(f"  Timeout:     {config.llm.timeout}s")
    print(f"  API Key:     {'configured' if config.llm.api_key else 'not set'}")

    # Embedding section
    print("\nEmbedding:")
    print(f"  Provider:    {config.embedding.provider}")
    print(f"  Model:       {config.embedding.model}")
    if config.embedding.base_url:
        print(f"  Base URL:    {config.embedding.base_url}")

    # Reranker section
    print("\nReranker:")
    print(f"  Enabled:     {config.reranker.enabled}")
    if config.reranker.enabled:
        top_n = effective_reranker_top_n(config.reranker.top_n, config.retrieval.top_k)
        configured = config.reranker.top_n if config.reranker.top_n is not None else "unset (derived)"
        print(f"  Model:       {config.reranker.model}")
        print(f"  Top N:       {top_n}  (configured: {configured})")

    # Retrieval section
    print("\nRetrieval:")
    print(f"  Top K:                      {config.retrieval.top_k}")
    print(f"  Hybrid Search:              {config.retrieval.enable_hybrid_search}")
    if config.retrieval.enable_hybrid_search:
        print(f"  RRF K:                      {config.retrieval.rrf_k}")
    print(f"  Contextual Retrieval:       {config.retrieval.enable_contextual_retrieval}")

    # Chunking section. Named per path: the Docling chunker splits on document
    # structure and has neither of these, so showing them as global would repeat
    # the defect that made them config in the first place.
    print("\nChunking (SentenceSplitter path — .txt/.md):")
    print(f"  Chunk Size:                 {config.chunking.chunk_size}")
    print(f"  Chunk Overlap:              {config.chunking.chunk_overlap}")
    print("  Other file types:           docling (structure-based, no size/overlap)")

    # Data policy section. This decides whether an eval judge may see corpus
    # content at all, so an operator checking their config must be able to see it.
    print("\nData Policy (judge egress):")
    print(f"  Corpus Confidential:        {config.data_policy.corpus_confidential}")
    print(
        f"  Allowed Judge Boundaries:   "
        f"{', '.join(sorted(b.value for b in config.data_policy.allowed_judge_boundaries)) or '(none)'}"
    )
    print(
        f"  Public Datasets:            "
        f"{', '.join(sorted(config.data_policy.public_datasets)) or '(none)'}"
    )
    print(f"  Eval Index Is Isolated:     {config.data_policy.eval_index_is_isolated}")

    # Eval section (if configured)
    if hasattr(config, 'eval') and config.eval:
        print("\nEvaluation (LLM-as-Judge):")
        print(f"  Provider:         {config.eval.provider}")
        print(f"  Model:            {config.eval.model}")
        print(f"  Citation Scope:   {config.eval.citation_scope}")
        print(f"  Citation Format:  {config.eval.citation_format}")
        print(f"  API Key:          {'configured' if config.eval.api_key else 'not set'}")

    # PII masking section (opt-in cloud generation tier)
    print("\nPII Masking:")
    print(f"  Enabled:          {config.pii.enabled}")
    if config.pii.enabled:
        print(f"  Entities:         {', '.join(config.pii.entities)}")
        print(f"  spaCy Model:      {config.pii.spacy_model}")
        print(f"  Score Threshold:  {config.pii.score_threshold}")
        print(f"  Output Guardrail: {config.pii.output_guardrails.enabled}")
