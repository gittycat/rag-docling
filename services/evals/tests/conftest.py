import pytest
from pydantic import SecretStr


class _TestSettings:
    OPENAI_API_KEY = SecretStr("test-openai-key")
    ANTHROPIC_API_KEY = SecretStr("test-anthropic-key")


@pytest.fixture(scope="session", autouse=True)
def _test_secrets():
    from infrastructure import settings as eval_settings

    eval_settings.SETTINGS = _TestSettings()
    yield
    eval_settings.SETTINGS = None


def pytest_addoption(parser):
    parser.addoption(
        "--run-eval",
        action="store_true",
        default=False,
        help="Run eval-marked tests (dataset downloads from HuggingFace, API keys)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-eval"):
        return
    skip_eval = pytest.mark.skip(reason="need --run-eval option to run (network/dataset downloads)")
    for item in items:
        if "eval" in item.keywords:
            item.add_marker(skip_eval)
