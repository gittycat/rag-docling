"""The judge against a real OpenAI-compatible HTTP endpoint.

These tests drive the whole transport — llama-index client, openai-python,
httpx, socket — against `tests/openai_stub.py` rather than mocking `acomplete`.
That is deliberate: the defects this unit closes (a dropped `temperature`, an
unreachable `base_url`, a free-text parser pointed at an open-weight model) are
all invisible to a mock, because a mock never serializes a request.

Scope limit, stated plainly: passing here means the judge speaks the OpenAI
chat-completions contract correctly. It does not mean a given vLLM release
accepts it. That needs a smoke test against a running server on a GPU host and is
not attempted anywhere in this suite.
"""

import json

import pytest

from evals.cache import ResponseCache
from evals.config import JudgeConfig
from evals.judges.llm_judge import JudgeError, LLMJudge, _usage_tokens
from evals.pricing import UsageTotals
from evals.judges.outputs import (
    JUDGE_SCORE_SCHEMA,
    JudgeParseError,
    judge_response_format,
    parse_judge_response,
    parse_structured_response,
    supports_structured_output,
)
from openai_stub import (
    OpenAICompatibleStub,
    Reply,
    json_reply,
    text_reply,
    unsupported_response_format,
)

from infrastructure.llm.config import LLMConfig as ClientConfig, LLMProvider
from infrastructure.llm.factory import create_llm_client


def _judge(stub: OpenAICompatibleStub, cache=None, usage_sink=None, **overrides) -> LLMJudge:
    """A judge wired to the stub the same way _create_llm wires a real one."""
    config = JudgeConfig(
        provider="vllm",
        model="Qwen/Qwen3-32B-AWQ",
        base_url=stub.base_url,
        temperature=0.0,
        timeout=10.0,
        execution_boundary="customer_managed",
        **overrides,
    )
    judge = LLMJudge(config, cache=cache, usage_sink=usage_sink)
    judge._llm = create_llm_client(
        ClientConfig(
            provider=LLMProvider.VLLM,
            model=config.model,
            base_url=config.base_url,
            timeout=config.timeout,
            temperature=config.temperature,
        )
    )
    return judge


@pytest.fixture
def stub():
    with OpenAICompatibleStub() as running:
        yield running


class TestRequestShape:
    async def test_the_request_reaches_the_configured_base_url(self, stub):
        await _judge(stub).evaluate_relevancy(answer="a", question="q")

        assert stub.call_count == 1
        assert stub.last_request.path == "/v1/chat/completions"

    async def test_temperature_reaches_the_wire(self, stub):
        # The determinism claim is only true if the value leaves the process.
        await _judge(stub).evaluate_relevancy(answer="a", question="q")

        assert stub.last_request.body["temperature"] == 0.0

    async def test_model_id_is_sent_verbatim(self, stub):
        await _judge(stub).evaluate_relevancy(answer="a", question="q")

        assert stub.last_request.body["model"] == "Qwen/Qwen3-32B-AWQ"

    async def test_keyless_endpoint_still_gets_an_auth_header(self, stub):
        # OpenAILike would refuse to construct without one; vLLM ignores it.
        await _judge(stub).evaluate_relevancy(answer="a", question="q")

        assert stub.last_request.headers["authorization"] == "Bearer none"

    async def test_prompt_carries_the_rubric_and_the_format_contract(self, stub):
        await _judge(stub).evaluate_faithfulness(answer="a", context="ctx")

        text = stub.last_request.prompt_text
        assert "faithfulness" in text.lower()
        assert "ctx" in text
        assert '"score"' in text  # structured instructions, not SCORE:/REASONING:


class TestSchemaConstrainedRequests:
    async def test_response_format_carries_the_judge_schema(self, stub):
        await _judge(stub).evaluate_relevancy(answer="a", question="q")

        sent = stub.last_request.body["response_format"]
        assert sent["type"] == "json_schema"
        assert sent["json_schema"]["strict"] is True
        assert sent["json_schema"]["schema"] == JUDGE_SCORE_SCHEMA

    async def test_a_schema_constrained_reply_is_parsed(self, stub):
        stub.replies.append(json_reply(0.25, "one claim unsupported"))

        result = await _judge(stub).evaluate_faithfulness(answer="a", context="c")

        assert result.score == 0.25
        assert result.reasoning == "one claim unsupported"
        assert result.metadata["structured_output"] is True

    async def test_anthropic_judges_are_not_sent_a_response_format(self):
        # Anthropic expresses schemas through tool use, not response_format; asking
        # for one would fail every call.
        assert supports_structured_output("anthropic") is False
        assert supports_structured_output("vllm") is True
        assert supports_structured_output("openai") is True

    async def test_judge_token_usage_survives_the_transport(self, stub):
        result = await _judge(stub).evaluate_relevancy(answer="a", question="q")

        assert result.metadata["token_usage"]["prompt_tokens"] == 11
        assert result.metadata["token_usage"]["completion_tokens"] == 7


class TestUsageAccounting:
    """What CostPerQuery prices judging with.

    The sink used to be assigned by the runner and never called, so every run
    billed judging — the larger half of an eval's token volume — at exactly $0
    while reporting a confident cost figure.
    """

    async def test_a_call_reports_its_tokens_to_the_sink(self, stub):
        totals = UsageTotals(model="Qwen/Qwen3-32B-AWQ")

        await _judge(stub, usage_sink=totals.record).evaluate_relevancy(
            answer="a", question="q"
        )

        assert totals.calls == 1
        assert totals.prompt_tokens == 11
        assert totals.completion_tokens == 7
        assert totals.has_usage

    async def test_every_call_accumulates(self, stub):
        totals = UsageTotals()
        judge = _judge(stub, usage_sink=totals.record)

        await judge.evaluate_relevancy(answer="a", question="q")
        await judge.evaluate_relevancy(answer="b", question="q")

        assert totals.calls == 2
        assert totals.prompt_tokens == 22

    async def test_a_cache_hit_reports_nothing(self, stub, tmp_path):
        # A replayed verdict costs nothing; charging for it would inflate the
        # cost of exactly the runs the cache was added to make cheap.
        totals = UsageTotals()
        cache = ResponseCache(tmp_path)
        judge = _judge(stub, cache=cache, usage_sink=totals.record)

        await judge.evaluate_relevancy(answer="a", question="q")
        await judge.evaluate_relevancy(answer="a", question="q")

        assert stub.call_count == 1
        assert totals.calls == 1

    async def test_an_unparseable_reply_still_reports_its_tokens(self, stub):
        # The retry consumed them whether or not the answer parsed.
        totals = UsageTotals()
        stub.replies.extend([Reply(content="no score here"), json_reply(0.75)])

        await _judge(stub, usage_sink=totals.record).evaluate_relevancy(
            answer="a", question="q"
        )

        assert totals.calls == 2
        assert totals.prompt_tokens == 22

    async def test_a_provider_reporting_no_usage_counts_the_call(self, stub):
        # Distinguishes "the sink never fired" from "the endpoint said nothing",
        # which otherwise both look like a $0 judge bill.
        totals = UsageTotals()
        stub.replies.append(Reply(content=json.dumps({"score": 1.0, "reasoning": "x"}), usage={}))

        await _judge(stub, usage_sink=totals.record).evaluate_relevancy(
            answer="a", question="q"
        )

        assert totals.calls == 1
        assert totals.calls_without_usage == 1
        assert totals.has_usage is False

    async def test_a_broken_sink_does_not_fail_the_judgement(self, stub):
        def explode(prompt: int, completion: int) -> None:
            raise RuntimeError("accounting is down")

        result = await _judge(stub, usage_sink=explode).evaluate_relevancy(
            answer="a", question="q"
        )

        # The verdict survives; only the accounting is lost.
        assert result.score == pytest.approx(0.75)

    async def test_anthropic_style_usage_keys_are_understood(self):
        # Anthropic says input/output where OpenAI says prompt/completion.
        assert _usage_tokens({"input_tokens": 30, "output_tokens": 4}) == (30, 4)
        assert _usage_tokens({"prompt_tokens": 30, "completion_tokens": 4}) == (30, 4)
        assert _usage_tokens({"total_tokens": 34}) is None
        assert _usage_tokens(None) is None


class TestSchemaRejectionFallback:
    async def test_a_server_without_guided_decoding_downgrades_to_text(self, stub):
        stub.replies.extend([unsupported_response_format(), text_reply(0.5)])

        judge = _judge(stub)
        result = await judge.evaluate_relevancy(answer="a", question="q")

        assert result.score == 0.5
        assert result.metadata["structured_output"] is False
        assert judge._structured_output is False

    async def test_the_retry_after_a_rejection_drops_the_schema(self, stub):
        stub.replies.extend([unsupported_response_format(), text_reply(0.5)])

        await _judge(stub).evaluate_relevancy(answer="a", question="q")

        assert "response_format" in stub.requests[0].body
        assert "response_format" not in stub.requests[1].body

    async def test_the_downgrade_switches_the_prompt_instructions(self, stub):
        stub.replies.extend([unsupported_response_format(), text_reply(0.5)])

        judge = _judge(stub)
        await judge.evaluate_relevancy(answer="a", question="q")
        await judge.evaluate_relevancy(answer="b", question="q")

        assert "SCORE:" in stub.requests[-1].prompt_text

    async def test_the_downgrade_is_not_retried_on_every_call(self, stub):
        stub.replies.extend([unsupported_response_format(), text_reply(0.5)])

        judge = _judge(stub)
        await judge.evaluate_relevancy(answer="a", question="q")
        before = stub.call_count
        await judge.evaluate_relevancy(answer="b", question="q")

        assert stub.call_count == before + 1  # one call, no rejected attempt


class TestRetries:
    async def test_an_unparseable_reply_is_retried(self, stub):
        stub.replies.extend([Reply(content="I think it's fine, honestly."), json_reply(0.9)])

        judge = _judge(stub)
        result = await judge.evaluate_correctness(answer="a", expected_answer="b", question="q")

        assert result.score == 0.9
        assert stub.call_count == 2
        assert result.metadata["attempt"] == 2

    async def test_exhausted_retries_raise_rather_than_score_zero(self, stub):
        # A 0.0 here is indistinguishable from a genuine "not grounded" verdict.
        stub.replies.append(Reply(content="no score anywhere"))

        with pytest.raises(JudgeError):
            await _judge(stub, max_retries=3).evaluate_relevancy(answer="a", question="q")

        assert stub.call_count == 3

    async def test_a_server_error_is_retried_then_raises(self, stub):
        stub.replies.append(Reply(status=400, error_message="bad request"))

        with pytest.raises(JudgeError):
            await _judge(stub, max_retries=2).evaluate_relevancy(answer="a", question="q")

        assert stub.call_count == 2


class TestCacheKey:
    """A cached judge score must not outlive the thing that produced it."""

    async def test_an_identical_call_is_served_from_cache(self, stub, tmp_path):
        cache = ResponseCache(tmp_path)

        await _judge(stub, cache=cache).evaluate_relevancy(answer="a", question="q")
        result = await _judge(stub, cache=cache).evaluate_relevancy(answer="a", question="q")

        assert stub.call_count == 1
        assert result.metadata["cached"] is True

    async def test_a_different_endpoint_is_a_different_key(self, stub, tmp_path):
        # Repointing base_url at another container is a different judge; the old
        # key covered only provider/model/temperature/prompt and would have hit.
        cache = ResponseCache(tmp_path)

        await _judge(stub, cache=cache).evaluate_relevancy(answer="a", question="q")
        judge = _judge(stub, cache=cache)
        judge.config.base_url = stub.base_url.replace("/v1", "/v1/other")
        await judge.evaluate_relevancy(answer="a", question="q")

        assert stub.call_count == 2

    async def test_a_different_output_contract_is_a_different_key(self, stub, tmp_path):
        cache = ResponseCache(tmp_path)

        await _judge(stub, cache=cache).evaluate_relevancy(answer="a", question="q")
        judge = _judge(stub, cache=cache)
        judge._structured_output = False
        await judge.evaluate_relevancy(answer="a", question="q")

        assert stub.call_count == 2

    def test_the_key_covers_the_resolved_judge_identity(self, tmp_path):
        judge = LLMJudge(
            JudgeConfig(
                provider="vllm",
                model="m",
                base_url="http://a:8000/v1",
                execution_boundary="customer_managed",
            )
        )
        parts = judge._cache_parts("body", structured=True)

        assert "vllm" in parts
        assert "http://a:8000/v1" in parts
        assert "customer_managed" in parts


class TestJudgeClientConstruction:
    def test_create_llm_builds_an_openai_compatible_client(self, monkeypatch):
        # _create_llm reads the API key off models_config; a keyless self-hosted
        # judge must still produce a usable client.
        from infrastructure.config import models_config as models_config_module

        class _Eval:
            api_key = None

        class _Config:
            eval = _Eval()

        monkeypatch.setattr(models_config_module, "get_models_config", lambda: _Config())

        judge = LLMJudge(
            JudgeConfig(
                provider="vllm",
                model="Qwen/Qwen3-32B-AWQ",
                base_url="http://vllm:8000/v1",
                temperature=0.0,
                execution_boundary="customer_managed",
            )
        )
        client = judge._create_llm()

        assert client.api_base == "http://vllm:8000/v1"
        assert client.temperature == 0.0
        assert client.is_chat_model is True

    def test_unknown_judge_provider_raises(self):
        judge = LLMJudge(JudgeConfig(provider="not-a-provider", model="m"))

        with pytest.raises(ValueError, match="Unsupported judge provider"):
            judge._create_llm()


class TestOutputParsing:
    """The parser itself, without a server."""

    def test_json_verdict(self):
        parsed = parse_judge_response('{"score": 0.4, "reasoning": "partial"}')
        assert (parsed.score, parsed.reasoning, parsed.structured) == (0.4, "partial", True)

    def test_fenced_json_is_still_json(self):
        parsed = parse_judge_response('```json\n{"score": 1, "reasoning": "ok"}\n```')
        assert parsed.score == 1.0
        assert parsed.structured is True

    def test_text_verdict_still_parses(self):
        parsed = parse_judge_response("SCORE: 0.5\nREASONING: half")
        assert (parsed.score, parsed.reasoning, parsed.structured) == (0.5, "half", False)

    def test_a_model_that_ignores_the_schema_falls_back_to_text(self):
        parsed = parse_judge_response("Sure!\nSCORE: 0.8\nREASONING: grounded")
        assert parsed.score == 0.8
        assert parsed.structured is False

    def test_truncated_json_with_a_score_line_is_recovered(self):
        parsed = parse_judge_response('{"note": "oops"\nSCORE: 0.3\nREASONING: r')
        assert parsed.score == 0.3

    @pytest.mark.parametrize("raw", ['{"score": 2.0}', '{"score": -1}'])
    def test_out_of_range_scores_clamp(self, raw):
        assert parse_structured_response(raw).score in (0.0, 1.0)

    @pytest.mark.parametrize(
        "raw",
        [
            '{"reasoning": "no score"}',
            '{"score": "high"}',
            '{"score": true}',
            "",
            "nothing useful at all",
        ],
    )
    def test_unreadable_verdicts_raise(self, raw):
        with pytest.raises(JudgeParseError):
            parse_judge_response(raw)

    def test_zero_is_a_verdict_not_a_failure(self):
        assert parse_judge_response('{"score": 0, "reasoning": "contradicts"}').score == 0.0

    def test_response_format_is_serializable(self):
        # It travels as JSON in the request body; a non-serializable schema would
        # only fail at call time.
        assert json.loads(json.dumps(judge_response_format()))["json_schema"]["name"]
