import os
from typing import List
import ollama

def get_llm_model():
    return os.getenv("LLM_MODEL", "llama3.2")

def construct_prompt(query: str, context_docs: List[str]) -> str:
    context = "\n\n".join(context_docs)

    prompt = f"""You are a helpful assistant that answers questions based on the provided context.

Context information:
{context}

Question: {query}

Please answer the question based on the context provided above. If the context doesn't contain enough information to answer the question, say so clearly."""

    return prompt

def generate_response(query: str, context: str) -> str:
    ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
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
