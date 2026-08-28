"""The generation tier must evaluate the deployed prompt, not a copy of it.

`query_rag_with_context` bypasses retrieval, so it assembles its own messages.
It used to hand-roll "Context:\n...\n\nQuestion: ..." and send only
`prompts.system` — which carries no grounding rule — so the grounding and
abstention instructions in `prompts.context` never reached the model. Every
unanswerable question in a `--tier generation` run was answered from parametric
knowledge, and `abstention_false_negative_rate` sat at exactly 1.0.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipelines.inference import query_rag_with_context


PASSAGES = [{"text": "Huguenot has unclear origins.", "doc_id": "doc1"}]


def _mock_llm(content: str = "I don't have enough information to answer this question."):
    llm = MagicMock()
    response = MagicMock()
    response.message.content = content
    llm.chat.return_value = response
    return llm


def _sent_messages(llm) -> list:
    return llm.chat.call_args[0][0]


def test_grounding_and_abstention_instructions_reach_the_model():
    llm = _mock_llm()
    with patch("pipelines.inference.Settings") as settings:
        settings.llm = llm
        query_rag_with_context("Which city was John Calvin born in?", PASSAGES)

    system = _sent_messages(llm)[0].content
    assert "ONLY the context" in system
    # The exact sentence evals/metrics/abstention.py matches on.
    assert "I don't have enough information to answer this question." in system
    assert "Never use prior knowledge" in system


def test_the_context_passages_are_in_the_prompt():
    llm = _mock_llm()
    with patch("pipelines.inference.Settings") as settings:
        settings.llm = llm
        query_rag_with_context("What is a Huguenot?", PASSAGES)

    system = _sent_messages(llm)[0].content
    assert "Huguenot has unclear origins." in system
    # The placeholder must be filled, never shipped literally.
    assert "{context_str}" not in system


def test_the_question_is_the_user_message():
    llm = _mock_llm()
    with patch("pipelines.inference.Settings") as settings:
        settings.llm = llm
        query_rag_with_context("What is a Huguenot?", PASSAGES)

    messages = _sent_messages(llm)
    assert messages[1].content == "What is a Huguenot?"


def test_the_answer_carries_no_role_prefix():
    """str(ChatResponse) is "assistant: <text>" — that prefix reached the judge."""
    llm = _mock_llm("Noyon, France.")
    with patch("pipelines.inference.Settings") as settings:
        settings.llm = llm
        result = query_rag_with_context("Where was Calvin born?", PASSAGES)

    assert result["answer"] == "Noyon, France."
    assert not result["answer"].startswith("assistant:")


def test_a_brace_in_the_passage_text_does_not_break_prompt_assembly():
    """Document text is arbitrary — `.format()` here would raise on any brace."""
    llm = _mock_llm()
    passages = [{"text": "The config uses {context_str} and {a: 1}.", "doc_id": "d"}]
    with patch("pipelines.inference.Settings") as settings:
        settings.llm = llm
        query_rag_with_context("What does the config use?", passages)

    assert "{a: 1}" in _sent_messages(llm)[0].content
