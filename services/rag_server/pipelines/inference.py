"""
RAG Inference Pipeline

Complete flow for query processing and answer generation:
1. Initialize chat memory (session-based, PostgreSQL-backed)
2. Build hybrid retriever (pg_textsearch BM25 + pgvector with RRF fusion)
3. Create reranker postprocessor (optional)
4. Build chat engine (condense_plus_context mode)
5. Query processing (retrieval → reranking → LLM generation)
6. Source extraction and response formatting
"""

from typing import AsyncGenerator, Dict, List, Optional, Generator
import asyncio
import contextlib
import contextvars
import json
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core import Settings
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.postprocessor.sbert_rerank import SentenceTransformerRerank
from llama_index.core.chat_engine import CondensePlusContextChatEngine
from llama_index.core.callbacks import CallbackManager, TokenCountingHandler

from infrastructure.config.models_config import get_models_config, effective_reranker_top_n
from infrastructure.llm.prompts import get_system_prompt, get_context_prompt, get_condense_prompt
from infrastructure.pii.config import get_pii_config
from infrastructure.pii.service import get_pii_service, mask_text, unmask_text, TokenMapping
from infrastructure.pii.postprocessor import (
    PIIMaskingPostprocessor,
    clear_session_token_mapping,
    get_session_token_mapping,
)
from infrastructure.pii.streaming import buffer_and_unmask_stream, buffer_and_unmask_stream_async

logger = logging.getLogger(__name__)

# ============================================================================
# GLOBAL STATE
# ============================================================================

# PostgreSQL-backed chat store (persists across container restarts)
_chat_store = None

# Both caches below hold cleartext user messages for the process lifetime unless
# bounded, so both get an idle TTL plus an LRU size cap (config: chat_memory.*).
# Losing a persistent entry is free — the buffer rehydrates from PostgreSQL.
# Losing a temporary entry ends that conversation, which is what "temporary"
# already promises; there is no DB copy and no delete hook, so the TTL is the
# only lever. Process-local by design: the server runs a single uvicorn worker.
@dataclass
class _MemoryEntry:
    memory: ChatMemoryBuffer
    last_used: float  # time.monotonic()


# Cache of memory buffers per session (PostgreSQL-backed sessions)
_memory_cache: "OrderedDict[str, _MemoryEntry]" = OrderedDict()

# Temporary session cache (in-memory only, cleared on restart)
_temporary_sessions: "OrderedDict[str, _MemoryEntry]" = OrderedDict()

# Token counting: reset_token_counter()/get_token_counts() used to share one
# process-global TokenCountingHandler, reset at the start of every query. Under
# concurrent queries (the evaluator runs query_concurrency: 10) that reset from
# query B would wipe query A's in-flight counts, and query A's later read could
# pick up tokens query B accumulated in between — cross-contaminated cost
# figures (Track D #4). Settings.callback_manager itself must stay a single
# global (llama_index reads it once per component construction), so the fix
# routes every event through one permanently-installed wrapper handler that
# forwards to whichever per-query TokenCountingHandler is active in the
# *calling* asyncio task's context. A ContextVar sets are task-local, but a
# task's children (e.g. HybridRRFRetriever's bm25/vector legs, spawned via
# asyncio.create_task after reset_token_counter() has already run) copy the
# parent's context at creation time, so they still route into the same
# handler instance — concurrent sibling queries never see each other's.
_active_token_counter: "contextvars.ContextVar[Optional[TokenCountingHandler]]" = contextvars.ContextVar(
    "active_token_counter", default=None
)

_callback_manager_ready = False


class _ContextScopedTokenCountingHandler(TokenCountingHandler):
    """Installed once as the process-wide callback handler. Every event is
    forwarded to the per-query handler active in the calling task's context
    (see reset_token_counter()) instead of accumulating on itself, so this
    instance's own counters are always empty and unused."""

    def start_trace(self, trace_id: Optional[str] = None) -> None:
        handler = _active_token_counter.get()
        if handler is not None:
            handler.start_trace(trace_id)

    def end_trace(self, trace_id=None, trace_map=None) -> None:
        handler = _active_token_counter.get()
        if handler is not None:
            handler.end_trace(trace_id, trace_map)

    def on_event_start(self, event_type, payload=None, event_id="", parent_id="", **kwargs) -> str:
        handler = _active_token_counter.get()
        if handler is not None:
            return handler.on_event_start(event_type, payload=payload, event_id=event_id, parent_id=parent_id, **kwargs)
        return event_id

    def on_event_end(self, event_type, payload=None, event_id="", **kwargs) -> None:
        handler = _active_token_counter.get()
        if handler is not None:
            handler.on_event_end(event_type, payload=payload, event_id=event_id, **kwargs)


def _ensure_context_scoped_callback_manager() -> None:
    global _callback_manager_ready
    if not _callback_manager_ready:
        Settings.callback_manager = CallbackManager([_ContextScopedTokenCountingHandler(verbose=False)])
        _callback_manager_ready = True
        logger.info("[TOKEN] Installed context-scoped token counting handler")


def reset_token_counter() -> None:
    """Start a fresh, per-query token counter and activate it for the calling
    task's context. Must run before any retrieval/generation work for this
    query so that sub-tasks it spawns inherit the right handler."""
    _ensure_context_scoped_callback_manager()
    _active_token_counter.set(TokenCountingHandler(verbose=False))


def get_token_counts() -> Dict[str, int]:
    """Token counts for the calling task's active query (see reset_token_counter)."""
    handler = _active_token_counter.get()
    if handler is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": handler.prompt_llm_token_count,
        "completion_tokens": handler.completion_llm_token_count,
        "total_tokens": handler.total_llm_token_count,
    }


# ============================================================================
# CONFIGURATION
# ============================================================================

def get_inference_config() -> Dict:
    """Get inference configuration from models config"""
    config = get_models_config()
    return {
        'reranker_enabled': config.reranker.enabled,
        'reranker_model': config.reranker.model,
        'reranker_top_n': config.reranker.top_n,
        'retrieval_top_k': config.retrieval.top_k,
        'hybrid_search_enabled': config.retrieval.enable_hybrid_search,
        'rrf_k': config.retrieval.rrf_k
    }


# ============================================================================
# STEP 1: CHAT MEMORY MANAGEMENT (PostgreSQL-backed)
# ============================================================================

def _get_chat_store():
    """Get or initialize PostgreSQL chat store (lazy initialization)"""
    global _chat_store
    if _chat_store is None:
        from infrastructure.database.sessions import PostgresChatStore
        _chat_store = PostgresChatStore()
        logger.info("[CHAT] Initialized PostgresChatStore (persistent)")
    return _chat_store


def _get_token_limit_for_chat_history() -> int:
    """
    Calculate token limit for chat history based on LLM context window.

    Strategy:
    - Reserve ~50% for chat history
    - Reserve ~40% for retrieved context
    - Reserve ~10% for response generation
    - Fallback to 3000 tokens if introspection unavailable
    """
    try:
        llm = Settings.llm

        # Try to get context window from LLM metadata
        if hasattr(llm, 'metadata') and hasattr(llm.metadata, 'context_window'):
            context_window = llm.metadata.context_window
            token_limit = int(context_window * 0.5)
            logger.info(f"[CHAT] Detected context window: {context_window} tokens, allocating {token_limit} for history (50%)")
            return token_limit

        # Try direct attribute
        if hasattr(llm, 'context_window'):
            context_window = llm.context_window
            token_limit = int(context_window * 0.5)
            logger.info(f"[CHAT] Detected context window: {context_window} tokens, allocating {token_limit} for history (50%)")
            return token_limit

    except Exception as e:
        logger.warning(f"[CHAT] Could not introspect model context window: {e}")

    # Fallback to safe default
    default_limit = 3000
    logger.info(f"[CHAT] Using default token limit: {default_limit}")
    return default_limit


def _expire_idle(cache: "OrderedDict[str, _MemoryEntry]", ttl_seconds: int, now: float) -> int:
    expired = [sid for sid, entry in cache.items() if now - entry.last_used > ttl_seconds]
    for session_id in expired:
        del cache[session_id]
    return len(expired)


def _enforce_capacity(cache: "OrderedDict[str, _MemoryEntry]", max_sessions: int) -> int:
    # Kept in LRU order by _cache_get/_cache_put's move_to_end.
    over_capacity = max(0, len(cache) - max_sessions)
    for _ in range(over_capacity):
        cache.popitem(last=False)
    return over_capacity


def _cache_get(
    cache: "OrderedDict[str, _MemoryEntry]",
    cache_config,
    session_id: str,
) -> Optional[ChatMemoryBuffer]:
    """Expire idle entries, then return session_id's buffer if it survived."""
    now = time.monotonic()
    # Expire first, so a session idle past the TTL gets a fresh buffer rather
    # than the stale one it would otherwise still hit.
    dropped = _expire_idle(cache, cache_config.ttl_seconds, now)
    if dropped:
        logger.debug(f"[CHAT] Expired {dropped} idle memory buffer(s); {len(cache)} retained")

    entry = cache.get(session_id)
    if entry is None:
        return None

    entry.last_used = now
    cache.move_to_end(session_id)
    return entry.memory


def _cache_put(
    cache: "OrderedDict[str, _MemoryEntry]",
    cache_config,
    session_id: str,
    memory: ChatMemoryBuffer,
) -> None:
    cache[session_id] = _MemoryEntry(memory=memory, last_used=time.monotonic())
    cache.move_to_end(session_id)

    # After the insert — the new entry is what can push the cache over the cap.
    evicted = _enforce_capacity(cache, cache_config.max_sessions)
    if evicted:
        logger.info(f"[CHAT] Evicted {evicted} least-recently-used memory buffer(s)")


def get_or_create_chat_memory(
    session_id: str,
    is_temporary: bool = False,
    ensure_metadata: bool = True,
) -> ChatMemoryBuffer:
    """
    Get or create chat memory for a session.

    If is_temporary=True:
    - Use in-memory dict (not PostgreSQL)
    - Lost on server restart
    - No metadata tracking

    Otherwise:
    - Uses PostgreSQL-backed storage (persistent)
    - Session metadata tracked
    """
    from services.session import get_session_metadata, create_session_metadata

    chat_memory_config = get_models_config().chat_memory

    # Handle temporary sessions
    if is_temporary:
        cached = _cache_get(_temporary_sessions, chat_memory_config.temporary, session_id)
        if cached is not None:
            logger.debug(f"[CHAT] Using temporary memory for session: {session_id}")
            return cached

        # Create new temporary memory (no persistence)
        token_limit = _get_token_limit_for_chat_history()
        memory = ChatMemoryBuffer.from_defaults(
            token_limit=token_limit,
            chat_store=None,  # No persistence
            chat_store_key=session_id
        )

        _cache_put(_temporary_sessions, chat_memory_config.temporary, session_id, memory)
        logger.info(f"[CHAT] Created temporary memory for session: {session_id} (in-memory only)")
        return memory

    # Check cache first
    cached = _cache_get(_memory_cache, chat_memory_config.persistent, session_id)
    if cached is not None:
        logger.debug(f"[CHAT] Using cached memory for session: {session_id}")
        return cached

    # Lazy-create metadata if missing (for existing sessions)
    if ensure_metadata:
        metadata = get_session_metadata(session_id)
        if not metadata:
            logger.info(f"[CHAT] Lazy-creating metadata for existing session: {session_id}")
            create_session_metadata(session_id)

    # Create new memory buffer with PostgreSQL chat store
    token_limit = _get_token_limit_for_chat_history()
    memory = ChatMemoryBuffer.from_defaults(
        token_limit=token_limit,
        chat_store=_get_chat_store(),
        chat_store_key=session_id
    )

    # Cache it
    _cache_put(_memory_cache, chat_memory_config.persistent, session_id, memory)
    logger.info(f"[CHAT] Created new memory for session: {session_id} (token_limit={token_limit})")

    return memory


def clear_session_memory(session_id: str) -> None:
    """Clear chat history for a session from PostgreSQL."""
    # Remove from cache. Temporary sessions live only here, so dropping the entry
    # is the whole clear — nothing downstream will find them in PostgreSQL.
    _memory_cache.pop(session_id, None)
    _temporary_sessions.pop(session_id, None)

    # Drop the cleartext PII mapping with the history it belongs to
    clear_session_token_mapping(session_id)

    # Clear from PostgreSQL
    chat_store = _get_chat_store()
    messages = chat_store.get_messages(session_id)
    if messages:
        chat_store.delete_messages(session_id)
        logger.info(f"[CHAT] Cleared memory for session: {session_id}")


def get_chat_history(session_id: str) -> List:
    """Get full chat history for a session."""
    chat_store = _get_chat_store()
    messages = chat_store.get_messages(session_id)
    return messages if messages else []


# ============================================================================
# STEP 2: HYBRID RETRIEVAL (pg_textsearch BM25 + pgvector + RRF)
# ============================================================================

def create_hybrid_retriever(similarity_top_k: int = 10):
    """
    Create hybrid retriever combining pg_textsearch BM25 + pgvector with RRF fusion.

    Research (Pinecone benchmark):
    - 48% improvement in retrieval quality vs vector-only
    - BM25 excels at: exact keywords, IDs, names, abbreviations
    - Vector search excels at: semantic understanding, context
    - RRF (Reciprocal Rank Fusion): simple, robust fusion

    Returns a bare PgVectorRetriever if hybrid search is disabled (vector-only).
    """
    config = get_inference_config()

    if not config['hybrid_search_enabled']:
        from infrastructure.search.vector_retriever import PgVectorRetriever

        logger.info("[HYBRID] Hybrid search disabled - using vector-only retrieval")
        return PgVectorRetriever(similarity_top_k=similarity_top_k)

    logger.info(f"[HYBRID] Creating hybrid retriever (top_k={similarity_top_k}, rrf_k={config['rrf_k']})")

    from infrastructure.search.hybrid_retriever import create_hybrid_retriever as _create_hybrid

    retriever = _create_hybrid(
        similarity_top_k=similarity_top_k,
        rrf_k=config['rrf_k'],
    )

    logger.info("[HYBRID] Hybrid retriever created (pg_textsearch BM25 + pgvector + RRF)")
    return retriever


# ============================================================================
# STEP 3: RERANKING
# ============================================================================

# Cached reranker — CrossEncoder init is not thread-safe in transformers 4.57+
# (init_empty_weights context manager races across threads causing meta tensor errors).
# Initialize once and reuse across all queries.
_cached_reranker: Optional[List] = None


def create_reranker_postprocessor() -> Optional[List]:
    """Return cached reranker postprocessors, creating on first call."""
    global _cached_reranker
    if _cached_reranker is not None:
        return _cached_reranker

    config = get_inference_config()

    if not config['reranker_enabled']:
        logger.info("[RERANKER] Reranking disabled")
        return None

    logger.info(f"[RERANKER] Initializing reranker: {config['reranker_model']}")

    top_n = effective_reranker_top_n(config['reranker_top_n'], config['retrieval_top_k'])
    logger.info(f"[RERANKER] Returning top {top_n} nodes after reranking")

    _cached_reranker = [
        SentenceTransformerRerank(
            model=config['reranker_model'],
            top_n=top_n,
        )
    ]
    logger.info("[RERANKER] Postprocessor initialized and cached")
    return _cached_reranker


def ensure_reranker_model_cached() -> None:
    """Fail fast if the reranker model is not present in the local HF cache."""
    config = get_inference_config()

    if not config['reranker_enabled']:
        return

    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import LocalEntryNotFoundError

    model = config['reranker_model']
    try:
        snapshot_download(model, local_files_only=True)
    except LocalEntryNotFoundError as e:
        logger.error(
            "[STARTUP] Reranker model missing in local cache. "
            "Run `just init` to download '%s' into ./.cache/huggingface, then restart.",
            model,
        )
        raise RuntimeError(
            "[STARTUP] Reranker model not found in local cache. "
            f"Run `just init` to download '{model}' into ./.cache/huggingface, "
            "then restart the service."
        ) from e


# ============================================================================
# PII MASKING (opt-in cloud generation tier — see infrastructure/pii/)
# ============================================================================
#
# Masking only ever touches what is sent to the generation LLM. The
# persisted chat history (PostgresChatStore) and the sources returned to the
# user always keep the original, unmasked text — masking happens on
# throwaway copies built for a single call and discarded afterward.


class _PIIMaskingContext:
    """Per-request masking state: shared token mapping, masked query, a
    throwaway memory seeded with masked history (fed to the chat engine
    instead of the real one), and a handle to the real memory so the
    original turn can be persisted after the call completes."""

    def __init__(self, token_mapping: TokenMapping, masked_query: str, scratch_memory: ChatMemoryBuffer, real_memory: ChatMemoryBuffer):
        self.token_mapping = token_mapping
        self.masked_query = masked_query
        self.scratch_memory = scratch_memory
        self.real_memory = real_memory


def _prepare_pii_masking(
    session_id: str,
    is_temporary: bool,
    ensure_metadata: bool,
    query_text: str,
) -> Optional[_PIIMaskingContext]:
    """Build masked query + masked chat history for this call. Returns None if PII masking is disabled."""
    if not get_pii_config().enabled:
        return None

    token_mapping = get_session_token_mapping(session_id)
    real_memory = get_or_create_chat_memory(session_id, is_temporary=is_temporary, ensure_metadata=ensure_metadata)

    masked_history = []
    for msg in real_memory.get_all():
        result = mask_text(str(msg.content), existing_mapping=token_mapping, context_id=session_id)
        masked_history.append(ChatMessage(role=msg.role, content=result.masked_text))

    masked_query = mask_text(query_text, existing_mapping=token_mapping, context_id=session_id).masked_text

    scratch_memory = ChatMemoryBuffer.from_defaults(
        chat_history=masked_history,
        token_limit=_get_token_limit_for_chat_history(),
    )
    return _PIIMaskingContext(token_mapping, masked_query, scratch_memory, real_memory)


def _unmask_pii_response(pii_ctx: _PIIMaskingContext, response_text: str, session_id: str) -> str:
    """Validate + fuzzy-recover + unmask the LLM response, then run the output guardrail scan."""
    service = get_pii_service()
    config = get_pii_config()
    token_mapping = pii_ctx.token_mapping

    text = response_text
    if config.validation.enabled:
        valid, altered = service.validate_tokens_preserved(token_mapping, text)
        if not valid:
            logger.warning(f"[PII] {len(altered)} tokens altered by LLM, attempting fuzzy recovery")
            text = service.attempt_fuzzy_recovery(text, token_mapping)

    unmask_result = service.unmask(text, token_mapping, context_id=session_id)
    final_answer = unmask_result.unmasked_text
    if not unmask_result.validation_passed:
        logger.warning(f"[PII] Unmasking incomplete: {len(unmask_result.tokens_missing)} tokens not found")

    if config.output_guardrails.enabled:
        leaked = service.scan_for_leaked_pii(final_answer, context_id=session_id)
        if leaked:
            logger.warning(f"[PII] Output guardrail: {len(leaked)} PII entities detected in response")
            if config.output_guardrails.block_on_detection:
                from infrastructure.pii.service import PIILeakageError
                raise PIILeakageError(f"PII detected in response: {len(leaked)} entities")

    return final_answer


def _finalize_pii_masking(pii_ctx: _PIIMaskingContext, query_text: str, response_text: str, session_id: str) -> str:
    """Unmask the response, then persist the real (unmasked) turn to the real chat memory —
    the scratch memory used for the call is discarded."""
    final_answer = _unmask_pii_response(pii_ctx, response_text, session_id)
    pii_ctx.real_memory.put(ChatMessage(role=MessageRole.USER, content=query_text))
    pii_ctx.real_memory.put(ChatMessage(role=MessageRole.ASSISTANT, content=final_answer))
    return final_answer


async def _prepare_pii_masking_async(
    session_id: str,
    is_temporary: bool,
    ensure_metadata: bool,
    query_text: str,
) -> Optional[_PIIMaskingContext]:
    """Async variant of _prepare_pii_masking: uses aget_all() for the real memory's chat
    store (the sync get_all() bridges to asyncio via run_async_safely, which deadlocks when
    called from a thread that already has a running loop — see Task 1.6), and offloads the
    CPU-bound Presidio analysis to a thread so it doesn't block the event loop."""
    if not get_pii_config().enabled:
        return None

    token_mapping = get_session_token_mapping(session_id)
    real_memory = get_or_create_chat_memory(session_id, is_temporary=is_temporary, ensure_metadata=ensure_metadata)
    history = await real_memory.aget_all()

    def _mask_all() -> tuple[list[ChatMessage], str]:
        masked_history = [
            ChatMessage(role=msg.role, content=mask_text(str(msg.content), existing_mapping=token_mapping, context_id=session_id).masked_text)
            for msg in history
        ]
        masked_query = mask_text(query_text, existing_mapping=token_mapping, context_id=session_id).masked_text
        return masked_history, masked_query

    masked_history, masked_query = await asyncio.to_thread(_mask_all)
    scratch_memory = ChatMemoryBuffer.from_defaults(
        chat_history=masked_history,
        token_limit=_get_token_limit_for_chat_history(),
    )
    return _PIIMaskingContext(token_mapping, masked_query, scratch_memory, real_memory)


async def _afinalize_pii_masking(pii_ctx: _PIIMaskingContext, query_text: str, response_text: str, session_id: str) -> str:
    """Async variant of _finalize_pii_masking — offloads the CPU-bound unmask work to a
    thread and uses aput() for the real memory's chat store."""
    final_answer = await asyncio.to_thread(_unmask_pii_response, pii_ctx, response_text, session_id)
    await pii_ctx.real_memory.aput(ChatMessage(role=MessageRole.USER, content=query_text))
    await pii_ctx.real_memory.aput(ChatMessage(role=MessageRole.ASSISTANT, content=final_answer))
    return final_answer


def _unmask_source_nodes(source_nodes: List[NodeWithScore], token_mapping: TokenMapping) -> List[NodeWithScore]:
    """Sources shown to the user must never contain mask tokens — only the LLM-facing copy is masked.

    Covers metadata too (file_name, path): the postprocessor masks it, and
    extract_sources reads it straight back out for display. Unmasking is a plain
    string replace, so running it over every string value is cheap."""
    unmasked = []
    for nws in source_nodes:
        text = unmask_text(nws.node.get_content(), token_mapping).unmasked_text
        metadata = {
            key: unmask_text(value, token_mapping).unmasked_text if isinstance(value, str) else value
            for key, value in nws.node.metadata.items()
        }
        node = TextNode(text=text, metadata=metadata)
        unmasked.append(NodeWithScore(node=node, score=nws.score))
    return unmasked


# ============================================================================
# STEP 4: CHAT ENGINE CREATION
# ============================================================================

# Task 1.5: verified the installed llama-index-core's
# CondensePlusContextChatEngine._condense_question / _acondense_question
# already short-circuit to the raw query when chat_history is empty — no
# wrapper needed for the first-message-in-session case.
def _stage_items(nodes: List[NodeWithScore]) -> list[Dict]:
    return [
        {
            "chunk_id": node_with_score.node.node_id,
            "doc_id": str(node_with_score.node.metadata.get("document_id", "")),
            "score": node_with_score.score,
            "rank": rank,
            "metadata": {
                "file_hash": node_with_score.node.metadata.get("file_hash"),
                "source_locator": node_with_score.node.metadata.get("source_locator"),
            },
        }
        for rank, node_with_score in enumerate(nodes, start=1)
    ]


def _append_stage_trace(
    stage_traces: list[Dict] | None,
    name: str,
    duration_ms: float,
    nodes: List[NodeWithScore] | None = None,
    *,
    status: str = "ok",
    error: str | None = None,
) -> None:
    if stage_traces is None:
        return
    stage_traces.append(
        {
            "name": name,
            "duration_ms": duration_ms,
            "item_count": len(nodes) if nodes is not None else 0,
            "items": _stage_items(nodes) if nodes is not None else None,
            "status": status,
            "error": error,
        }
    )


def _context_assembly_duration_ms(chat_engine) -> float:
    value = getattr(chat_engine, "_last_context_assembly_ms", 0.0)
    return value if isinstance(value, (int, float)) else 0.0


def _nested_stage_duration_ms(stage_traces: list[Dict] | None) -> float:
    """Wall time already accounted for by stages nested inside _run_c3.

    The installed CondensePlusContextChatEngine calls _aget_nodes() from inside
    _run_c3, so retrieval and reranking happen *within* the context-assembly
    span and are also emitted as their own stages. Their durations are
    subtracted from the emitted context_assembly figure so the stage list nests:
    summing it can never exceed the query's latency_ms.
    """
    if not stage_traces:
        return 0.0
    return sum(
        trace.get("duration_ms", 0.0)
        for trace in stage_traces
        if trace.get("name") in ("bm25", "vector", "fusion", "rerank")
        and not trace.get("parallel")
    ) + _parallel_group_duration_ms(stage_traces)


def _parallel_group_duration_ms(stage_traces: list[Dict] | None) -> float:
    """Concurrent legs overlap wall time, so the group costs its slowest leg."""
    if not stage_traces:
        return 0.0
    parallel = [t.get("duration_ms", 0.0) for t in stage_traces if t.get("parallel")]
    return max(parallel) if parallel else 0.0


def total_stage_duration_ms(stage_traces: list[Dict] | None) -> float:
    """The stage list's wall-clock cost, honouring the nesting contract.

    Stages marked `parallel` ran concurrently with their siblings and are
    counted once at the slowest leg rather than summed. Every other stage is
    exclusive of the others by construction. This is the quantity the phase-1
    bound applies to: it must never exceed the query's measured latency_ms.
    """
    if not stage_traces:
        return 0.0
    sequential = sum(
        trace.get("duration_ms", 0.0)
        for trace in stage_traces
        if not trace.get("parallel")
    )
    return sequential + _parallel_group_duration_ms(stage_traces)


def _retriever_stage_traces(
    retriever, nodes: List[NodeWithScore], duration_ms: float
) -> list[Dict]:
    traces = getattr(retriever, "last_stage_traces", None)
    if isinstance(traces, list):
        return traces

    # HybridRRFRetriever records both legs and fusion itself. A vector-only
    # deployment has no discarded leg list to expose, so capture its one stage
    # here without inventing a BM25 or fusion result.
    from infrastructure.search.vector_retriever import get_vector_health

    health = get_vector_health()
    error = health.get("last_error")
    return [
        {
            "name": "vector",
            "duration_ms": duration_ms,
            "item_count": len(nodes),
            "items": _stage_items(nodes),
            "status": "degraded" if error else "ok",
            "error": error,
        }
    ]


class _StageTracingCondensePlusContextChatEngine(CondensePlusContextChatEngine):
    """Chat engine that records retrieval and context preparation without altering it."""

    def _get_nodes(self, message: str) -> List[NodeWithScore]:
        retrieval_started = time.perf_counter()
        nodes = self._retriever.retrieve(message)
        retrieval_duration_ms = (time.perf_counter() - retrieval_started) * 1000
        stage_traces = getattr(self, "_stage_traces", None)
        if isinstance(stage_traces, list):
            stage_traces.extend(
                _retriever_stage_traces(self._retriever, nodes, retrieval_duration_ms)
            )

        pre_rerank_nodes = nodes
        rerank_duration_ms = 0.0
        reranker_ran = False
        for postprocessor in self._node_postprocessors or []:
            started = time.perf_counter()
            nodes = postprocessor.postprocess_nodes(nodes, query_bundle=QueryBundle(message))
            if isinstance(postprocessor, SentenceTransformerRerank):
                reranker_ran = True
                rerank_duration_ms += (time.perf_counter() - started) * 1000
        _append_stage_trace(
            stage_traces if isinstance(stage_traces, list) else None,
            "rerank",
            rerank_duration_ms,
            nodes if reranker_ran else pre_rerank_nodes,
        )
        return nodes

    def _run_c3(self, *args, **kwargs):
        started = time.perf_counter()
        result = super()._run_c3(*args, **kwargs)
        self._last_context_assembly_ms = (time.perf_counter() - started) * 1000
        stage_traces = getattr(self, "_stage_traces", None)
        traces = stage_traces if isinstance(stage_traces, list) else None
        _append_stage_trace(
            traces,
            "context_assembly",
            # Exclusive: retrieval and rerank run inside _run_c3 and are already
            # emitted as their own stages. `_last_context_assembly_ms` stays
            # inclusive because `generation` subtracts it for the same reason.
            max(self._last_context_assembly_ms - _nested_stage_duration_ms(traces), 0.0),
            result[2],
        )
        return result


class _AsyncSafeCondensePlusContextChatEngine(_StageTracingCondensePlusContextChatEngine):
    """CondensePlusContextChatEngine variant safe to `await` directly on the
    main event loop.

    The base class's `_aget_nodes()` calls node_postprocessors (e.g. the
    cross-encoder reranker) synchronously inline inside the coroutine, which
    would block the event loop for the CPU-bound reranking duration. This
    override runs postprocessing in a thread instead.
    """

    async def _aget_nodes(self, message: str) -> List[NodeWithScore]:
        retrieval_started = time.perf_counter()
        nodes = await self._retriever.aretrieve(message)
        retrieval_duration_ms = (time.perf_counter() - retrieval_started) * 1000
        stage_traces = getattr(self, "_stage_traces", None)
        if isinstance(stage_traces, list):
            stage_traces.extend(
                _retriever_stage_traces(self._retriever, nodes, retrieval_duration_ms)
            )

        pre_rerank_nodes = nodes
        rerank_duration_ms = 0.0
        reranker_ran = False
        for postprocessor in self._node_postprocessors or []:
            started = time.perf_counter()
            nodes = await asyncio.to_thread(
                postprocessor.postprocess_nodes, nodes, query_bundle=QueryBundle(message)
            )
            if isinstance(postprocessor, SentenceTransformerRerank):
                reranker_ran = True
                rerank_duration_ms += (time.perf_counter() - started) * 1000
        _append_stage_trace(
            stage_traces if isinstance(stage_traces, list) else None,
            "rerank",
            rerank_duration_ms,
            nodes if reranker_ran else pre_rerank_nodes,
        )
        return nodes

    async def _arun_c3(self, *args, **kwargs):
        started = time.perf_counter()
        result = await super()._arun_c3(*args, **kwargs)
        self._last_context_assembly_ms = (time.perf_counter() - started) * 1000
        stage_traces = getattr(self, "_stage_traces", None)
        traces = stage_traces if isinstance(stage_traces, list) else None
        _append_stage_trace(
            traces,
            "context_assembly",
            # Exclusive: retrieval and rerank run inside _run_c3 and are already
            # emitted as their own stages. `_last_context_assembly_ms` stays
            # inclusive because `generation` subtracts it for the same reason.
            max(self._last_context_assembly_ms - _nested_stage_duration_ms(traces), 0.0),
            result[2],
        )
        return result


def create_chat_engine(
    session_id: str,
    retrieval_top_k: int = 10,
    is_temporary: bool = False,
    ensure_metadata: bool = True,
    async_safe: bool = False,
    memory_override: Optional[ChatMemoryBuffer] = None,
    pii_token_mapping: Optional[TokenMapping] = None,
    stage_traces: list[Dict] | None = None,
) -> CondensePlusContextChatEngine:
    """
    Create chat engine with hybrid search, reranking, and conversational memory.

    Flow:
    1. Load LlamaIndex native prompts (system, context, condense)
    2. Get or create chat memory for session (or use memory_override, a
       throwaway memory pre-seeded with masked history for the PII tier)
    3. Create hybrid retriever (or a bare vector retriever when hybrid is off)
    4. Create reranker postprocessor (if enabled), then PII masking
       postprocessor (if pii_token_mapping given) — masking always runs
       after reranking, since the reranker needs original text for quality
    5. Build CondensePlusContextChatEngine with all components

    CondensePlusContextChatEngine mode:
    - Condenses chat history + new query into standalone question
    - Retrieves relevant context
    - Generates answer using context + chat history

    Returns configured chat engine ready for querying.
    """
    config = get_inference_config()

    logger.info(f"[CHAT_ENGINE] Creating chat engine for session: {session_id}")
    logger.info(f"[CHAT_ENGINE] Config: top_k={retrieval_top_k}, reranker={config['reranker_enabled']}, hybrid={config['hybrid_search_enabled']}")

    # Get prompts
    system_prompt = get_system_prompt()
    include_citations = False
    citation_format = "numeric"
    try:
        from infrastructure.config.models_config import get_models_config
        eval_config = get_models_config().eval
        include_citations = eval_config.citation_scope == "explicit"
        citation_format = eval_config.citation_format
    except Exception:
        include_citations = False
    context_prompt = get_context_prompt(
        include_citations=include_citations,
        citation_format=citation_format,
    )
    condense_prompt = get_condense_prompt()  # None = use LlamaIndex default

    # Get chat memory (with temporary support), unless a masked scratch memory was provided
    memory = memory_override or get_or_create_chat_memory(
        session_id,
        is_temporary=is_temporary,
        ensure_metadata=ensure_metadata,
    )

    # Create retriever (hybrid, or vector-only when hybrid search is disabled)
    retriever = create_hybrid_retriever(similarity_top_k=retrieval_top_k)

    # Reranker first, PII masking last (must see reranked, pre-mask node text)
    node_postprocessors = list(create_reranker_postprocessor() or [])
    if pii_token_mapping is not None:
        node_postprocessors.append(PIIMaskingPostprocessor(token_mapping=pii_token_mapping, context_id=session_id))
    node_postprocessors = node_postprocessors or None

    # Create chat engine
    if config['hybrid_search_enabled']:
        logger.info("[CHAT_ENGINE] Using hybrid retriever (pg_textsearch BM25 + pgvector + RRF)")
    else:
        logger.info("[CHAT_ENGINE] Using vector retriever only")
    engine_class = _AsyncSafeCondensePlusContextChatEngine if async_safe else _StageTracingCondensePlusContextChatEngine
    chat_engine = engine_class.from_defaults(
        retriever=retriever,
        memory=memory,
        node_postprocessors=node_postprocessors,
        system_prompt=system_prompt,
        context_prompt=context_prompt,
        condense_prompt=condense_prompt,
        verbose=False
    )
    chat_engine._stage_traces = stage_traces

    logger.info("[CHAT_ENGINE] Chat engine created successfully")
    return chat_engine


# ============================================================================
# STEP 5: QUERY PROCESSING
# ============================================================================

def extract_sources(
    source_nodes: List,
    include_chunks: bool = False,
    dedupe_by_document: bool = True,
) -> List[Dict]:
    """
    Extract source information from retrieved nodes.

    Flow:
    - Deduplicate by document_id (multiple chunks from same doc)
    - Extract metadata: document_id, file_name, path, score
    - Create excerpt (first 200 chars) and include full text
    - Return list of source dictionaries
    """
    sources = []
    seen_docs = set()

    for node in source_nodes:
        metadata = node.metadata
        doc_id = metadata.get('document_id')
        chunk_index = metadata.get('chunk_index')
        chunk_id = getattr(node, "id_", None)

        # Deduplicate by document_id
        if dedupe_by_document and doc_id:
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)

        full_text = node.get_content()
        source = {
            'document_id': doc_id,
            'document_name': metadata.get('file_name', 'Unknown'),
            'excerpt': full_text[:200] + '...' if len(full_text) > 200 else full_text,
            'full_text': full_text,
            'path': metadata.get('path', ''),
            'score': node.score if hasattr(node, 'score') and node.score else None
        }
        if include_chunks:
            source["chunk_id"] = chunk_id
            source["chunk_index"] = chunk_index
            source["source_locator"] = metadata.get("source_locator")
            source["file_hash"] = metadata.get("file_hash")
        sources.append(source)

    return sources


def extract_numeric_citations(answer: str, sources: List[Dict]) -> List[Dict]:
    """Extract numeric citations like [1], [1,2], [1-3] mapped to sources list."""
    import re

    if not answer or not sources:
        return []

    citation_indices: list[int] = []
    bracket_patterns = [
        r"\[(\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*)\]",
        r"\((\d+(?:\s*-\s*\d+)?(?:\s*,\s*\d+(?:\s*-\s*\d+)?)*)\)",
    ]

    for pattern in bracket_patterns:
        for match in re.findall(pattern, answer):
            parts = [p.strip() for p in match.split(",")]
            for part in parts:
                if "-" in part:
                    bounds = [b.strip() for b in part.split("-", 1)]
                    if len(bounds) == 2 and bounds[0].isdigit() and bounds[1].isdigit():
                        start = int(bounds[0])
                        end = int(bounds[1])
                        if start <= end:
                            citation_indices.extend(range(start, end + 1))
                elif part.isdigit():
                    citation_indices.append(int(part))

    # De-duplicate while preserving order
    seen = set()
    unique_indices = []
    for idx in citation_indices:
        if idx not in seen:
            seen.add(idx)
            unique_indices.append(idx)

    citations = []
    for idx in unique_indices:
        source_idx = idx - 1
        if 0 <= source_idx < len(sources):
            source = sources[source_idx]
            citations.append(
                {
                    "source_index": idx,
                    "document_id": source.get("document_id"),
                    "chunk_id": source.get("chunk_id"),
                    "chunk_index": source.get("chunk_index"),
                }
            )

    return citations


def query_rag(
    query_text: str,
    session_id: str,
    is_temporary: bool = False,
    include_chunks: bool = False,
    ensure_metadata: bool = True,
    update_session_metadata: bool = True,
) -> Dict:
    """
    Execute RAG query pipeline (synchronous, non-streaming).

    Flow:
    1. Get inference configuration
    2. Create chat engine (with hybrid search, reranking, memory)
    3. Execute query (retrieval → reranking → LLM generation)
    4. Extract sources from retrieved nodes
    5. Update session metadata (touch timestamp, auto-generate title)
    6. Return response with answer, sources, session_id, metrics

    Returns:
        {
            'answer': str,
            'sources': List[Dict],
            'query': str,
            'session_id': str,
            'citations': List[Dict] | None,
            'metrics': {
                'latency_ms': float,
                'token_usage': {
                    'prompt_tokens': int,
                    'completion_tokens': int,
                    'total_tokens': int
                } | None
            }
        }
    """
    from services.session import touch_session, get_session_metadata, update_session_title
    from services.session_titles import generate_session_title

    logger.info(f"[QUERY] Processing query for session: {session_id} (temporary={is_temporary})")
    query_start = time.time()
    stage_traces: list[Dict] = []

    # Reset token counter before query
    reset_token_counter()

    config = get_inference_config()

    logger.info(f"[QUERY] Config: top_k={config['retrieval_top_k']}, reranker={config['reranker_enabled']}, hybrid={config['hybrid_search_enabled']}")

    # PII masking (no-op if pii.enabled is false): builds a masked query + a throwaway
    # memory pre-seeded with masked history, so the chat engine never sees the real store.
    pii_ctx = _prepare_pii_masking(session_id, is_temporary, ensure_metadata, query_text)

    # Create chat engine
    chat_engine = create_chat_engine(
        session_id,
        retrieval_top_k=config['retrieval_top_k'],
        is_temporary=is_temporary,
        ensure_metadata=ensure_metadata,
        memory_override=pii_ctx.scratch_memory if pii_ctx else None,
        pii_token_mapping=pii_ctx.token_mapping if pii_ctx else None,
        stage_traces=stage_traces,
    )

    # Execute query
    logger.info(f"[QUERY] Executing RAG query...")
    generation_started = time.perf_counter()
    response = chat_engine.chat(pii_ctx.masked_query if pii_ctx else query_text)
    generation_duration_ms = max(
        (time.perf_counter() - generation_started) * 1000
        - _context_assembly_duration_ms(chat_engine),
        0.0,
    )
    _append_stage_trace(stage_traces, "generation", generation_duration_ms)

    # Capture token usage immediately after query
    token_counts = get_token_counts()

    # Sources shown to the user must be unmasked, even though the LLM saw masked context
    source_nodes = _unmask_source_nodes(response.source_nodes, pii_ctx.token_mapping) if pii_ctx else response.source_nodes

    # Log retrieved nodes
    logger.info(f"[QUERY] Retrieved {len(source_nodes)} nodes for context")

    if source_nodes:
        total_context_length = 0
        for i, node in enumerate(source_nodes):
            node_text = node.get_content()
            total_context_length += len(node_text)
            score_info = f" (score: {node.score:.4f})" if hasattr(node, 'score') and node.score else ""
            logger.debug(f"[QUERY] Node {i+1}{score_info}: {node_text[:150]}...")

        logger.info(f"[QUERY] Total context length: {total_context_length} chars ({len(source_nodes)} nodes)")
    else:
        logger.warning("[QUERY] No context nodes retrieved - LLM will respond without context")

    # Extract sources
    sources = extract_sources(
        source_nodes,
        include_chunks=include_chunks,
        dedupe_by_document=not include_chunks,
    )

    # Unmask the answer (validation + fuzzy recovery + output guardrail) and persist the
    # real turn to chat history — the scratch memory used above is discarded here.
    answer = _finalize_pii_masking(pii_ctx, query_text, str(response), session_id) if pii_ctx else str(response)

    citations = None
    citation_started = time.perf_counter()
    if include_chunks:
        try:
            from infrastructure.config.models_config import get_models_config

            models_config = get_models_config()
            if models_config.eval.citation_format == "numeric":
                citations = extract_numeric_citations(answer, sources)
        except Exception:
            citations = None
    _append_stage_trace(stage_traces, "citation", (time.perf_counter() - citation_started) * 1000)

    # Update session metadata (non-temporary sessions only)
    if update_session_metadata and not is_temporary:
        touch_session(session_id)

        # Auto-generate title from first user message if needed
        metadata = get_session_metadata(session_id)
        if metadata and metadata.title == "New Chat":
            title = generate_session_title(query_text)
            update_session_title(session_id, title)

    query_duration = time.time() - query_start
    latency_ms = query_duration * 1000
    logger.info(f"[QUERY] Query complete ({query_duration:.2f}s) - {len(sources)} sources returned")
    logger.info(f"[QUERY] Token usage: {token_counts}")

    return {
        'answer': answer,
        'sources': sources,
        'query': query_text,
        'session_id': session_id,
        'citations': citations,
        'metrics': {
            'latency_ms': latency_ms,
            'token_usage': token_counts if token_counts['total_tokens'] > 0 else None,
            'stages': stage_traces,
        },
    }


async def query_rag_async(
    query_text: str,
    session_id: str,
    is_temporary: bool = False,
    include_chunks: bool = False,
    ensure_metadata: bool = True,
    update_session_metadata: bool = True,
) -> Dict:
    """
    Async variant of query_rag(): awaits chat_engine.achat() directly instead
    of going through an executor thread. Same return shape as query_rag().

    Session metadata updates use the `_async` repository functions directly
    (touch_session_async, etc.) rather than the sync ones, since those sync
    functions block via run_async_safely() and are only safe to call from a
    thread other than the main event loop's — which this coroutine runs on.
    """
    from services.session import touch_session_async, get_session_metadata_async, update_session_title_async
    from services.session_titles import generate_session_title

    logger.info(f"[QUERY] Processing async query for session: {session_id} (temporary={is_temporary})")
    query_start = time.time()
    stage_traces: list[Dict] = []

    reset_token_counter()

    config = get_inference_config()

    logger.info(f"[QUERY] Config: top_k={config['retrieval_top_k']}, reranker={config['reranker_enabled']}, hybrid={config['hybrid_search_enabled']}")

    pii_ctx = await _prepare_pii_masking_async(session_id, is_temporary, ensure_metadata, query_text)

    chat_engine = create_chat_engine(
        session_id,
        retrieval_top_k=config['retrieval_top_k'],
        is_temporary=is_temporary,
        ensure_metadata=ensure_metadata,
        async_safe=True,
        memory_override=pii_ctx.scratch_memory if pii_ctx else None,
        pii_token_mapping=pii_ctx.token_mapping if pii_ctx else None,
        stage_traces=stage_traces,
    )

    logger.info(f"[QUERY] Executing async RAG query...")
    generation_started = time.perf_counter()
    response = await chat_engine.achat(pii_ctx.masked_query if pii_ctx else query_text)
    generation_duration_ms = max(
        (time.perf_counter() - generation_started) * 1000
        - _context_assembly_duration_ms(chat_engine),
        0.0,
    )
    _append_stage_trace(stage_traces, "generation", generation_duration_ms)

    token_counts = get_token_counts()

    source_nodes = _unmask_source_nodes(response.source_nodes, pii_ctx.token_mapping) if pii_ctx else response.source_nodes
    logger.info(f"[QUERY] Retrieved {len(source_nodes)} nodes for context")

    sources = extract_sources(
        source_nodes,
        include_chunks=include_chunks,
        dedupe_by_document=not include_chunks,
    )

    answer = (
        await _afinalize_pii_masking(pii_ctx, query_text, str(response), session_id)
        if pii_ctx
        else str(response)
    )

    citations = None
    citation_started = time.perf_counter()
    if include_chunks:
        try:
            models_config = get_models_config()
            if models_config.eval.citation_format == "numeric":
                citations = extract_numeric_citations(answer, sources)
        except Exception:
            citations = None
    _append_stage_trace(stage_traces, "citation", (time.perf_counter() - citation_started) * 1000)

    if update_session_metadata and not is_temporary:
        await touch_session_async(session_id)

        metadata = await get_session_metadata_async(session_id)
        if metadata and metadata.title == "New Chat":
            title = generate_session_title(query_text)
            await update_session_title_async(session_id, title)

    query_duration = time.time() - query_start
    latency_ms = query_duration * 1000
    logger.info(f"[QUERY] Async query complete ({query_duration:.2f}s) - {len(sources)} sources returned")
    logger.info(f"[QUERY] Token usage: {token_counts}")

    return {
        'answer': answer,
        'sources': sources,
        'query': query_text,
        'session_id': session_id,
        'citations': citations,
        'metrics': {
            'latency_ms': latency_ms,
            'token_usage': token_counts if token_counts['total_tokens'] > 0 else None,
            'stages': stage_traces,
        },
    }


async def search_rag_async(query_text: str, top_k: int) -> list[Dict]:
    """Run retrieval and reranking only, without creating chat state or calling an LLM."""
    retriever = create_hybrid_retriever(similarity_top_k=top_k)
    retrieval_started = time.perf_counter()
    nodes = await retriever.aretrieve(query_text)
    retrieval_duration_ms = (time.perf_counter() - retrieval_started) * 1000
    stage_traces = _retriever_stage_traces(retriever, nodes, retrieval_duration_ms)

    pre_rerank_nodes = nodes
    reranker = create_reranker_postprocessor()
    rerank_started = time.perf_counter()
    if reranker:
        for postprocessor in reranker:
            nodes = await asyncio.to_thread(
                postprocessor.postprocess_nodes,
                nodes,
                query_bundle=QueryBundle(query_text),
            )
    _append_stage_trace(
        stage_traces,
        "rerank",
        (time.perf_counter() - rerank_started) * 1000 if reranker else 0.0,
        nodes if reranker else pre_rerank_nodes,
    )
    return stage_traces


def query_rag_with_context(
    query_text: str,
    context_passages: List[Dict],
    session_id: Optional[str] = None,
) -> Dict:
    """
    Execute RAG generation with pre-injected context (Tier 1 eval).

    Bypasses hybrid retrieval entirely. Uses the provided passages as context
    and calls the LLM directly via Settings.llm.chat().

    Args:
        query_text: The user's question
        context_passages: List of {"text": str, "doc_id": str} dicts
        session_id: Optional session ID for response tracking

    Returns:
        Same shape as query_rag(): answer, sources, session_id, citations, metrics
    """
    from llama_index.core.llms import ChatMessage
    from infrastructure.config.models_config import get_models_config

    reset_token_counter()
    query_start = time.time()

    # Format passages as numbered context block
    context_lines = []
    for i, p in enumerate(context_passages, 1):
        context_lines.append(f"[{i}] (source: {p['doc_id']})\n{p['text']}")
    context_str = "\n\n".join(context_lines)

    # The grounding rules live in `prompts.context` (config.yml) — "answer using
    # ONLY the context", "never use prior knowledge", and the exact abstention
    # sentence the abstention metrics look for. This function used to hand-roll
    # "Context:\n...\n\nQuestion: ..." and send only `prompts.system`, which
    # carries no grounding rule at all: the generation tier then measured a prompt
    # that exists nowhere else, and scored an unanswerable question as answered
    # every time because the model was never told to abstain.
    #
    # Assembled the way CondensePlusContextChatEngine assembles it on the retrieval
    # path — context prompt folded into the system message, question as the user
    # message — so this tier evaluates the deployed prompt rather than a copy.
    include_citations = False
    citation_format = "numeric"
    try:
        eval_config = get_models_config().eval
        include_citations = eval_config.citation_scope == "explicit"
        citation_format = eval_config.citation_format
    except Exception:
        include_citations = False

    system_prompt = get_system_prompt()
    # replace(), not format(): the filled context is arbitrary document text and
    # any brace in it would blow up str.format.
    context_block = get_context_prompt(
        include_citations=include_citations,
        citation_format=citation_format,
    ).replace("{context_str}", context_str)

    messages = [
        ChatMessage(role="system", content=f"{system_prompt}\n\n{context_block}"),
        ChatMessage(role="user", content=query_text),
    ]

    logger.info(f"[QUERY_WITH_CONTEXT] Calling LLM with {len(context_passages)} passages")
    response = Settings.llm.chat(messages)
    # str(ChatResponse) is "assistant: <text>" — the role prefix was landing in
    # every answer this endpoint returned, and from there into the judge's input.
    answer = response.message.content or ""

    token_counts = get_token_counts()

    # Build sources from provided passages (no retrieval)
    sources = [
        {
            "document_id": p["doc_id"],
            "document_name": p["doc_id"],
            "excerpt": p["text"][:200] + "..." if len(p["text"]) > 200 else p["text"],
            "full_text": p["text"],
            "path": "",
            "score": None,
        }
        for p in context_passages
    ]

    latency_ms = (time.time() - query_start) * 1000
    logger.info(f"[QUERY_WITH_CONTEXT] Complete ({latency_ms:.0f}ms)")

    return {
        "answer": answer,
        "sources": sources,
        "query": query_text,
        "session_id": session_id or str(uuid.uuid4()),
        "citations": None,
        "metrics": {
            "latency_ms": latency_ms,
            "token_usage": token_counts if token_counts["total_tokens"] > 0 else None,
        },
    }


def query_rag_stream(
    query_text: str,
    session_id: str,
    is_temporary: bool = False,
    include_chunks: bool = False,
    ensure_metadata: bool = True,
    update_session_metadata: bool = True,
) -> Generator[str, None, None]:
    """
    Execute RAG query pipeline with streaming response (Server-Sent Events).

    Flow:
    1. Create chat engine (same as non-streaming)
    2. Use stream_chat for token-by-token generation
    3. Yield SSE events:
       - event: token, data: {"token": "..."}  (for each token)
       - event: sources, data: {"sources": [...], "session_id": "..."}  (after streaming completes)
       - event: done, data: {}  (completion signal)
       - event: error, data: {"error": "..."}  (on error)
    4. Update session metadata after streaming completes

    Yields SSE-formatted strings for client consumption.
    """
    from services.session import touch_session, get_session_metadata, update_session_title
    from services.session_titles import generate_session_title

    try:
        logger.info(f"[QUERY_STREAM] Starting streaming query for session: {session_id} (temporary={is_temporary})")

        # Create chat engine
        config = get_inference_config()
        pii_ctx = _prepare_pii_masking(session_id, is_temporary, ensure_metadata, query_text)
        chat_engine = create_chat_engine(
            session_id,
            retrieval_top_k=config['retrieval_top_k'],
            is_temporary=is_temporary,
            ensure_metadata=ensure_metadata,
            memory_override=pii_ctx.scratch_memory if pii_ctx else None,
            pii_token_mapping=pii_ctx.token_mapping if pii_ctx else None,
        )

        # Stream response tokens
        logger.info(f"[QUERY_STREAM] Executing streaming RAG query...")
        streaming_response = chat_engine.stream_chat(pii_ctx.masked_query if pii_ctx else query_text)

        full_answer_parts = []
        if pii_ctx:
            # Sentence-buffered unmasking (see infrastructure/pii/streaming.py) — a
            # [[[PERSON_0]]] token can straddle two raw deltas, so we can't unmask per-token.
            for chunk in buffer_and_unmask_stream(
                streaming_response.response_gen, get_pii_service(), pii_ctx.token_mapping, context_id=session_id
            ):
                full_answer_parts.append(chunk)
                yield f"event: token\ndata: {json.dumps({'token': chunk})}\n\n"
        else:
            for token in streaming_response.response_gen:
                full_answer_parts.append(token)
                yield f"event: token\ndata: {json.dumps({'token': token})}\n\n"
        full_answer = "".join(full_answer_parts)

        # Sources shown to the user must be unmasked, even though the LLM saw masked context
        source_nodes = (
            _unmask_source_nodes(streaming_response.source_nodes, pii_ctx.token_mapping)
            if pii_ctx
            else streaming_response.source_nodes
        )

        # After streaming completes, send sources
        sources = extract_sources(
            source_nodes,
            include_chunks=include_chunks,
            dedupe_by_document=not include_chunks,
        )

        if pii_ctx:
            # Output guardrail (audit-only for streaming: tokens are already on the
            # wire by the time we can scan the full answer, so we can't block here).
            pii_config = get_pii_config()
            if pii_config.output_guardrails.enabled:
                leaked = get_pii_service().scan_for_leaked_pii(full_answer, context_id=session_id)
                if leaked:
                    logger.warning(f"[PII] Output guardrail: {len(leaked)} PII entities detected in streamed response")
            pii_ctx.real_memory.put(ChatMessage(role=MessageRole.USER, content=query_text))
            pii_ctx.real_memory.put(ChatMessage(role=MessageRole.ASSISTANT, content=full_answer))

        citations = None
        if include_chunks:
            try:
                from infrastructure.config.models_config import get_models_config

                models_config = get_models_config()
                if models_config.eval.citation_format == "numeric":
                    citations = extract_numeric_citations(full_answer, sources)
            except Exception:
                citations = None
        logger.info(f"[QUERY_STREAM] Streaming complete - {len(sources)} sources")

        # Update session metadata (non-temporary sessions only)
        if update_session_metadata and not is_temporary:
            touch_session(session_id)

            # Auto-generate title from first user message if needed
            metadata = get_session_metadata(session_id)
            if metadata and metadata.title == "New Chat":
                title = generate_session_title(query_text)
                update_session_title(session_id, title)

        yield f"event: sources\ndata: {json.dumps({'sources': sources, 'citations': citations, 'session_id': session_id})}\n\n"

        # Send done event
        yield f"event: done\ndata: {{}}\n\n"

    except Exception as e:
        logger.error(f"[QUERY_STREAM] Error during streaming: {str(e)}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"


async def query_rag_stream_async(
    query_text: str,
    session_id: str,
    is_temporary: bool = False,
    include_chunks: bool = False,
    ensure_metadata: bool = True,
    update_session_metadata: bool = True,
) -> AsyncGenerator[str, None]:
    """
    Async variant of query_rag_stream(): awaits chat_engine.astream_chat()
    directly and iterates response.async_response_gen(), instead of running
    the sync generator in a thread with a queue bridge. Same SSE event shape
    as query_rag_stream().
    """
    from services.session import touch_session_async, get_session_metadata_async, update_session_title_async
    from services.session_titles import generate_session_title

    try:
        logger.info(f"[QUERY_STREAM] Starting async streaming query for session: {session_id} (temporary={is_temporary})")
        stream_started = time.perf_counter()
        stage_traces: list[Dict] = []
        time_to_first_token_ms: float | None = None

        config = get_inference_config()
        pii_ctx = await _prepare_pii_masking_async(session_id, is_temporary, ensure_metadata, query_text)
        chat_engine = create_chat_engine(
            session_id,
            retrieval_top_k=config['retrieval_top_k'],
            is_temporary=is_temporary,
            ensure_metadata=ensure_metadata,
            async_safe=True,
            memory_override=pii_ctx.scratch_memory if pii_ctx else None,
            pii_token_mapping=pii_ctx.token_mapping if pii_ctx else None,
            stage_traces=stage_traces,
        )

        logger.info(f"[QUERY_STREAM] Executing async streaming RAG query...")
        generation_started = time.perf_counter()
        streaming_response = await chat_engine.astream_chat(pii_ctx.masked_query if pii_ctx else query_text)

        full_answer_parts = []
        if pii_ctx:
            async for chunk in buffer_and_unmask_stream_async(
                streaming_response.async_response_gen(), get_pii_service(), pii_ctx.token_mapping, context_id=session_id
            ):
                if time_to_first_token_ms is None:
                    time_to_first_token_ms = (time.perf_counter() - stream_started) * 1000
                full_answer_parts.append(chunk)
                yield f"event: token\ndata: {json.dumps({'token': chunk})}\n\n"
        else:
            async for token in streaming_response.async_response_gen():
                if time_to_first_token_ms is None:
                    time_to_first_token_ms = (time.perf_counter() - stream_started) * 1000
                full_answer_parts.append(token)
                yield f"event: token\ndata: {json.dumps({'token': token})}\n\n"
        full_answer = "".join(full_answer_parts)
        generation_duration_ms = max(
            (time.perf_counter() - generation_started) * 1000
            - _context_assembly_duration_ms(chat_engine),
            0.0,
        )
        _append_stage_trace(stage_traces, "generation", generation_duration_ms)

        source_nodes = (
            _unmask_source_nodes(streaming_response.source_nodes, pii_ctx.token_mapping)
            if pii_ctx
            else streaming_response.source_nodes
        )
        sources = extract_sources(
            source_nodes,
            include_chunks=include_chunks,
            dedupe_by_document=not include_chunks,
        )

        if pii_ctx:
            pii_config = get_pii_config()
            if pii_config.output_guardrails.enabled:
                leaked = await asyncio.to_thread(get_pii_service().scan_for_leaked_pii, full_answer, session_id)
                if leaked:
                    logger.warning(f"[PII] Output guardrail: {len(leaked)} PII entities detected in streamed response")
            await pii_ctx.real_memory.aput(ChatMessage(role=MessageRole.USER, content=query_text))
            await pii_ctx.real_memory.aput(ChatMessage(role=MessageRole.ASSISTANT, content=full_answer))

        citations = None
        citation_started = time.perf_counter()
        if include_chunks:
            try:
                models_config = get_models_config()
                if models_config.eval.citation_format == "numeric":
                    citations = extract_numeric_citations(full_answer, sources)
            except Exception:
                citations = None
        _append_stage_trace(stage_traces, "citation", (time.perf_counter() - citation_started) * 1000)
        logger.info(f"[QUERY_STREAM] Async streaming complete - {len(sources)} sources")

        if update_session_metadata and not is_temporary:
            await touch_session_async(session_id)

            metadata = await get_session_metadata_async(session_id)
            if metadata and metadata.title == "New Chat":
                title = generate_session_title(query_text)
                await update_session_title_async(session_id, title)

        metrics = {
            "latency_ms": (time.perf_counter() - stream_started) * 1000,
            "time_to_first_token_ms": time_to_first_token_ms,
            "stages": stage_traces,
        }
        yield f"event: sources\ndata: {json.dumps({'sources': sources, 'citations': citations, 'session_id': session_id, 'metrics': metrics})}\n\n"

        yield f"event: done\ndata: {{}}\n\n"

    except Exception as e:
        logger.error(f"[QUERY_STREAM] Error during async streaming: {str(e)}")
        yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"


# ============================================================================
# BACKWARD COMPATIBILITY
# ============================================================================

def refresh_bm25_retriever() -> None:
    """No-op for backward compatibility. pg_textsearch BM25 index refreshes automatically."""
    logger.debug("[HYBRID] refresh_bm25_retriever called - pg_textsearch handles this automatically")
    pass


def initialize_bm25_retriever(similarity_top_k: int = 10):
    """No-op for backward compatibility. pg_textsearch BM25 is used instead."""
    logger.debug("[HYBRID] initialize_bm25_retriever called - pg_textsearch handles this automatically")
    return None


def get_bm25_retriever():
    """No-op for backward compatibility."""
    return None
