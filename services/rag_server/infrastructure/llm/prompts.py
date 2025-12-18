"""
Centralized prompt management for RAG pipeline.

All prompts used by the chat engine are defined here for easy maintenance
and consistency across the application.
"""
from typing import Optional


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

    Placeholders (filled by LlamaIndex):
        {context_str}: Retrieved document chunks
        {chat_history}: Previous conversation messages
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
