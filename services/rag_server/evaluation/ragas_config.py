from langchain_ollama import ChatOllama, OllamaEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
import os


class RagasOllamaConfig:
    def __init__(
        self,
        ollama_url: str | None = None,
        llm_model: str = "gemma3:4b",
        embedding_model: str = "qwen3-embedding:8b",
        request_timeout: float = 300.0,
    ):
        self.ollama_url = ollama_url or os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
        self.llm_model = llm_model
        self.embedding_model = embedding_model
        self.request_timeout = request_timeout

        self._llm = None
        self._embeddings = None

    @property
    def llm(self):
        if self._llm is None:
            chat_ollama = ChatOllama(
                model=self.llm_model,
                base_url=self.ollama_url,
                timeout=self.request_timeout,
                temperature=0.0,
            )
            self._llm = LangchainLLMWrapper(chat_ollama)
        return self._llm

    @property
    def embeddings(self):
        if self._embeddings is None:
            ollama_embeddings = OllamaEmbeddings(
                model=self.embedding_model,
                base_url=self.ollama_url,
            )
            self._embeddings = LangchainEmbeddingsWrapper(ollama_embeddings)
        return self._embeddings

    def get_evaluator_config(self):
        return {
            "llm": self.llm,
            "embeddings": self.embeddings,
        }


def create_default_ragas_config() -> RagasOllamaConfig:
    return RagasOllamaConfig(
        ollama_url=os.getenv("OLLAMA_URL", "http://host.docker.internal:11434"),
        llm_model=os.getenv("LLM_MODEL", "gemma3:4b"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "qwen3-embedding:8b"),
        request_timeout=300.0,
    )
