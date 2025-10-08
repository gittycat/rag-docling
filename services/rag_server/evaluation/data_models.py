from pydantic import BaseModel, Field


class EvaluationSample(BaseModel):
    user_input: str = Field(..., description="The question or query from the user")
    retrieved_contexts: list[str] = Field(..., description="List of context chunks retrieved by the system")
    response: str = Field(default="", description="The generated answer from the LLM")
    reference: str | None = Field(default=None, description="Ground truth answer for comparison")

    def to_ragas_dict(self) -> dict:
        return {
            "user_input": self.user_input,
            "retrieved_contexts": self.retrieved_contexts,
            "response": self.response,
            "reference": self.reference,
        }


class EvaluationResult(BaseModel):
    metric_name: str
    score: float
    sample_count: int
    per_sample_scores: list[float] | None = None
    metadata: dict = Field(default_factory=dict)


class RetrievalEvaluationResult(BaseModel):
    context_precision: float | None = None
    context_recall: float | None = None
    context_entity_recall: float | None = None
    sample_count: int
    per_sample_results: list[dict] | None = None


class GenerationEvaluationResult(BaseModel):
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    answer_correctness: float | None = None
    sample_count: int
    per_sample_results: list[dict] | None = None


class EndToEndEvaluationResult(BaseModel):
    retrieval: RetrievalEvaluationResult
    generation: GenerationEvaluationResult
    overall_score: float | None = None
    sample_count: int
