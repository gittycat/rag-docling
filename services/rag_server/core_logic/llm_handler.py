from typing import List
import ollama
from core_logic.env_config import get_required_env

def get_llm_model():
    return get_required_env("LLM_MODEL")

def get_prompt_strategy():
    return get_required_env("PROMPT_STRATEGY").lower()

def construct_prompt_fast(query: str, context_docs: List[str]) -> str:
    """Fast strategy: minimal instructions for quick responses with simple documents"""
    context_xml = "\n\n".join(
        f"<context>{doc}</context>"
        for doc in context_docs
    )

    prompt = f"""Answer the question using the provided context. If the answer isn't in the context, say "I don't know."

<contexts>
{context_xml}
</contexts>

Question: {query}

Answer:"""

    return prompt

def construct_prompt_balanced(query: str, context_docs: List[str]) -> str:
    """Balanced strategy: good default with clear grounding and anti-hallucination measures"""
    context_xml = "\n\n".join(
        f"<context id='{i}'>\n{doc}\n</context>"
        for i, doc in enumerate(context_docs, 1)
    )

    prompt = f"""Answer the question using ONLY the information in the provided context below.

Rules:
- Use ONLY the provided context to answer
- If the answer is not in the context, respond with: "I don't have enough information to answer this question."
- Do not use prior knowledge or make assumptions
- Be concise and accurate

<contexts>
{context_xml}
</contexts>

<question>
{query}
</question>

Answer:"""

    return prompt

def construct_prompt_precise(query: str, context_docs: List[str]) -> str:
    """Precise strategy: strong anti-hallucination with step-by-step reasoning"""
    context_xml = "\n\n".join(
        f"<context id='{i}'>\n{doc}\n</context>"
        for i, doc in enumerate(context_docs, 1)
    )

    prompt = f"""Answer the question using ONLY the provided context below.

<instruction>
1. Read the context documents carefully
2. If the answer is found in the context, provide a clear answer and mention which context ID(s) you used
3. If the answer is NOT in the context, respond EXACTLY with: "I don't have enough information in the provided context to answer this question."
4. Do NOT use your prior knowledge or make assumptions beyond what's explicitly stated
5. If you're uncertain, err on the side of saying you don't know
</instruction>

<contexts>
{context_xml}
</contexts>

<question>
{query}
</question>

Answer:"""

    return prompt

def construct_prompt_comprehensive(query: str, context_docs: List[str]) -> str:
    """Comprehensive strategy: maximum accuracy with chain-of-thought and self-critique"""
    context_xml = "\n\n".join(
        f"<context id='{i}'>\n{doc}\n</context>"
        for i, doc in enumerate(context_docs, 1)
    )

    prompt = f"""Answer the question using ONLY the provided context below.

<instruction>
Follow this step-by-step process:

Step 1: Identify which context documents contain relevant information for the question
Step 2: Extract the specific facts or statements that relate to the question
Step 3: Formulate your answer using ONLY the extracted information
Step 4: Review your answer to ensure it doesn't contain information not in the context
Step 5: Cite which context ID(s) you used

If at any step you find insufficient information in the context:
- Respond EXACTLY with: "I don't have enough information in the provided context to answer this question."
- Do NOT use your prior knowledge
- Do NOT make assumptions or inferences beyond what's explicitly stated

If you're uncertain or the information is ambiguous, always err on the side of saying you don't know.
</instruction>

<contexts>
{context_xml}
</contexts>

<question>
{query}
</question>

Let's work through this step by step:"""

    return prompt

def construct_prompt(query: str, context_docs: List[str]) -> str:
    """Route to appropriate prompt strategy based on config"""
    strategy = get_prompt_strategy()

    if strategy == "fast":
        return construct_prompt_fast(query, context_docs)
    elif strategy == "precise":
        return construct_prompt_precise(query, context_docs)
    elif strategy == "comprehensive":
        return construct_prompt_comprehensive(query, context_docs)
    else:  # balanced (default)
        return construct_prompt_balanced(query, context_docs)

def generate_response(query: str, context: str) -> str:
    ollama_url = get_required_env("OLLAMA_URL")
    model = get_llm_model()

    # Create Ollama client
    client = ollama.Client(host=ollama_url)

    # Construct prompt with context
    if context:
        prompt = construct_prompt(query, [context])
    else:
        prompt = f"Question: {query}\n\nPlease answer the question. If you don't have enough information, say so."

    # Generate response
    response = client.generate(
        model=model,
        prompt=prompt
    )

    return response['response']
