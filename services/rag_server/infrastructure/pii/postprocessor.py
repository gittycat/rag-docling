"""LlamaIndex node postprocessor that masks retrieved chunk text before it
reaches the cloud generation LLM, plus the session-scoped TokenMapping cache
shared across query, retrieved context, and chat history.

Ordering requirement: this MUST run after the reranker. The reranker scores
on-host and needs the original text for quality; masking is the last step
before the prompt is assembled.
"""

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, List, Optional

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from .config import get_pii_config
from .service import TokenMapping, mask_text

logger = logging.getLogger(__name__)


# Metadata whose values are machine-generated identifiers, never free text.
# Masking them would only burn Presidio calls and risk mangling a hash or UUID
# (document_id in particular must survive verbatim — extract_sources dedupes on it).
STRUCTURAL_METADATA_KEYS = frozenset(
    {"document_id", "chunk_index", "file_type", "file_hash", "file_size_bytes", "uploaded_at"}
)


class PIIMaskingPostprocessor(BaseNodePostprocessor):
    """Masks PII in retrieved node text and metadata. Never mutates docstore nodes — works on copies."""

    token_mapping: Any
    context_id: Optional[str] = None

    def _mask_metadata(self, metadata: dict, value_cache: dict[str, str]) -> dict:
        """Mask free-text metadata values. The synthesizer renders nodes with
        MetadataMode.LLM, so anything left here (file_name, path) reaches the LLM.

        value_cache dedupes across the batch — every chunk of a document carries
        the same file_name, and mask() re-runs Presidio on each call."""
        masked = {}
        for key, value in metadata.items():
            if key in STRUCTURAL_METADATA_KEYS or not isinstance(value, str):
                masked[key] = value
                continue
            if value not in value_cache:
                value_cache[value] = mask_text(
                    value, existing_mapping=self.token_mapping, context_id=self.context_id
                ).masked_text
            masked[key] = value_cache[value]
        return masked

    def _postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        masked_nodes = []
        value_cache: dict[str, str] = {}
        for nws in nodes:
            result = mask_text(nws.node.get_content(), existing_mapping=self.token_mapping, context_id=self.context_id)
            masked = TextNode(
                text=result.masked_text,
                metadata=self._mask_metadata(nws.node.metadata, value_cache),
            )
            masked_nodes.append(NodeWithScore(node=masked, score=nws.score))
        return masked_nodes


# Session-scoped mapping cache — [[[PERSON_0]]] must refer to the same person
# across turns, since condense_plus_context re-sends chat history to the LLM
# every request. In-memory only; never persist original PII values to disk.
#
# Bounded two ways, because entries hold cleartext PII: evicted after an idle
# period (pii.session_mapping.ttl_seconds) and capped at max_sessions, LRU-first.
# Losing a mapping is safe — the next turn re-masks from the persisted history and
# rebuilds it; only the token *numbering* changes, which nothing depends on.
#
# Process-local by design. The server runs a single uvicorn worker; adding workers
# would need session affinity, since a shared store would mean persisting PII.
@dataclass
class _CacheEntry:
    mapping: TokenMapping
    last_used: float  # time.monotonic()


_session_mappings: OrderedDict[str, _CacheEntry] = OrderedDict()


def _expire_idle(now: float, ttl_seconds: int) -> int:
    expired = [sid for sid, entry in _session_mappings.items() if now - entry.last_used > ttl_seconds]
    for session_id in expired:
        del _session_mappings[session_id]
    return len(expired)


def _enforce_capacity(max_sessions: int) -> int:
    # OrderedDict is kept in LRU order by get_session_token_mapping's move_to_end.
    over_capacity = max(0, len(_session_mappings) - max_sessions)
    for _ in range(over_capacity):
        _session_mappings.popitem(last=False)
    return over_capacity


def get_session_token_mapping(session_id: str) -> TokenMapping:
    cfg = get_pii_config().session_mapping
    now = time.monotonic()

    # Expire first, so a session idle past the TTL gets a fresh mapping rather
    # than the stale one it would otherwise still hit.
    dropped = _expire_idle(now, cfg.ttl_seconds)

    entry = _session_mappings.get(session_id)
    if entry is None:
        entry = _CacheEntry(mapping=TokenMapping(), last_used=now)
        _session_mappings[session_id] = entry
    else:
        entry.last_used = now
    _session_mappings.move_to_end(session_id)

    # After the insert — the new entry is what can push the cache over the cap.
    dropped += _enforce_capacity(cfg.max_sessions)
    if dropped:
        logger.debug(f"[PII] Evicted {dropped} session token mapping(s); {len(_session_mappings)} retained")
    return entry.mapping


def clear_session_token_mapping(session_id: str) -> None:
    _session_mappings.pop(session_id, None)
