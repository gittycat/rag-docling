"""LlamaIndex node postprocessor that masks retrieved chunk text before it
reaches the cloud generation LLM, plus the session-scoped TokenMapping cache
shared across query, retrieved context, and chat history.

Ordering requirement: this MUST run after the reranker. The reranker scores
on-host and needs the original text for quality; masking is the last step
before the prompt is assembled.
"""

from typing import Any, List, Optional

from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

from .service import TokenMapping, mask_text


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
_session_mappings: dict[str, TokenMapping] = {}


def get_session_token_mapping(session_id: str) -> TokenMapping:
    if session_id not in _session_mappings:
        _session_mappings[session_id] = TokenMapping()
    return _session_mappings[session_id]


def clear_session_token_mapping(session_id: str) -> None:
    _session_mappings.pop(session_id, None)
