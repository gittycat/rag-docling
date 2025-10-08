from llama_index.llms.ollama import Ollama
from core_logic.env_config import get_required_env

def get_llm_client():
    ollama_url = get_required_env("OLLAMA_URL")
    model = get_required_env("LLM_MODEL")
    return Ollama(model=model, base_url=ollama_url, request_timeout=120.0)

def get_prompt_strategy():
    return get_required_env("PROMPT_STRATEGY").lower()

def get_prompt_template_fast() -> str:
    """Fast strategy: minimal instructions for quick responses with simple documents"""
    return """Answer the question using the provided context. If the answer isn't in the context, say "I don't know."

Context information:
{context_str}

Question: {query_str}

Answer:"""

def get_prompt_template_balanced() -> str:
    """Balanced strategy: good default with clear grounding and anti-hallucination measures"""
    return """Answer the question using ONLY the information in the provided context below.

Rules:
- Use ONLY the provided context to answer
- If the answer is not in the context, respond with: "I don't have enough information to answer this question."
- Do not use prior knowledge or make assumptions
- Be concise and accurate

Context information:
{context_str}

Question: {query_str}

Answer:"""

def get_prompt_template_precise() -> str:
    """Precise strategy: strong anti-hallucination with step-by-step reasoning"""
    return """Answer the question using ONLY the provided context below.

Instructions:
1. Read the context documents carefully
2. If the answer is found in the context, provide a clear answer
3. If the answer is NOT in the context, respond EXACTLY with: "I don't have enough information in the provided context to answer this question."
4. Do NOT use your prior knowledge or make assumptions beyond what's explicitly stated
5. If you're uncertain, err on the side of saying you don't know

Context information:
{context_str}

Question: {query_str}

Answer:"""

def get_prompt_template_comprehensive() -> str:
    """Comprehensive strategy: maximum accuracy with chain-of-thought and self-critique"""
    return """Answer the question using ONLY the provided context below.

Instructions:
Follow this step-by-step process:

Step 1: Identify which context documents contain relevant information for the question
Step 2: Extract the specific facts or statements that relate to the question
Step 3: Formulate your answer using ONLY the extracted information
Step 4: Review your answer to ensure it doesn't contain information not in the context
Step 5: Cite which parts of the context you used

If at any step you find insufficient information in the context:
- Respond EXACTLY with: "I don't have enough information in the provided context to answer this question."
- Do NOT use your prior knowledge
- Do NOT make assumptions or inferences beyond what's explicitly stated

If you're uncertain or the information is ambiguous, always err on the side of saying you don't know.

Context information:
{context_str}

Question: {query_str}

Let's work through this step by step:"""

def get_prompt_template() -> str:
    """Route to appropriate prompt template based on config"""
    strategy = get_prompt_strategy()

    if strategy == "fast":
        return get_prompt_template_fast()
    elif strategy == "precise":
        return get_prompt_template_precise()
    elif strategy == "comprehensive":
        return get_prompt_template_comprehensive()
    else:  # balanced (default)
        return get_prompt_template_balanced()
