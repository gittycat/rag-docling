"""DeepEval configuration for evaluation v2."""

from infrastructure.config.models_config import get_models_config


def get_evaluator_model(model: str | None = None, temperature: float = 0.0):
    """Get configured DeepEval model based on eval provider."""
    config = get_models_config()
    eval_config = config.eval

    if eval_config.provider != "ollama" and not eval_config.api_key:
        raise ValueError(
            f"API key is required for eval provider '{eval_config.provider}'."
        )

    model_name = model or eval_config.model
    provider = eval_config.provider.lower()

    if provider == "anthropic":
        from deepeval.models import AnthropicModel
        return AnthropicModel(model=model_name, temperature=temperature)

    if provider == "openai":
        from deepeval.models import OpenAIModel
        return OpenAIModel(model=model_name, temperature=temperature)

    if provider == "ollama":
        from deepeval.models import OllamaModel
        return OllamaModel(model=model_name, temperature=temperature)

    raise ValueError(f"Unsupported eval provider for DeepEval: {provider}")


def get_default_evaluator():
    return get_evaluator_model()
