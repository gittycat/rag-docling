from llama_index.llms.ollama import Ollama
from core.config import get_required_env, get_optional_env
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def get_llm_client():
    ollama_url = get_required_env("OLLAMA_URL")
    model = get_required_env("LLM_MODEL")

    # Keep-alive: Keep model loaded in memory between calls
    # Reduces latency for subsequent calls (especially important for contextual retrieval)
    # Default: "10m" (10 minutes), use "-1" to keep indefinitely, "0" to unload immediately
    keep_alive = get_optional_env("OLLAMA_KEEP_ALIVE", "10m")

    logger.info(f"[LLM] Initializing Ollama LLM: {model}, keep_alive={keep_alive}")

    return Ollama(
        model=model,
        base_url=ollama_url,
        request_timeout=120.0,
        keep_alive=keep_alive
    )

def get_system_prompt() -> str:
    """
    System-level instructions for LLM behavior.

    Defines the assistant's personality, response style, and general approach.
    Applied to all LLM interactions including question condensation and answer generation.
    """
    return (
        "You are a professional assistant providing accurate answers based on document context. "
        "Be direct and concise. Avoid conversational fillers like 'Let me explain', 'Okay', 'Well', or 'Sure'. "
        "Start responses immediately with the answer. "
        "Use bullet points for lists when appropriate."
    )

def get_context_prompt() -> str:
    """
    Instructions for using retrieved context to answer questions.

    Specifies strict grounding rules to prevent hallucination and ensure
    answers are based only on the provided document context.

    Placeholders:
    - {context_str}: Retrieved document chunks (provided by LlamaIndex)
    - {chat_history}: Previous conversation (provided by LlamaIndex)
    """
    return """Context from retrieved documents:
{context_str}

Instructions:
- Answer using ONLY the context provided above
- If the context does not contain sufficient information, respond: "I don't have enough information to answer this question."
- Never use prior knowledge or make assumptions beyond what is explicitly stated
- Be specific and cite details from the context when relevant
- Previous conversation context is available for reference

Provide a direct, accurate answer based on the context:"""

def get_condense_prompt() -> Optional[str]:
    """
    Optional: Custom question condensation prompt.

    Controls how follow-up questions are reformulated into standalone queries.
    Returns None to use LlamaIndex's built-in DEFAULT_CONDENSE_PROMPT.

    The default prompt works well for most cases:
    "Given a conversation (between Human and Assistant) and a follow up message from Human,
    rewrite the message to be a standalone question that captures all relevant context."

    Only customize if you need different reformulation behavior.
    """
    # Use LlamaIndex's default - it's well-tested and effective
    return None
