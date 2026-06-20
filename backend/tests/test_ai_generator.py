"""Tests for AIGenerator: does it call the DeepSeek API and the search tool correctly?

The OpenAI client is patched, so no API key or network is needed.
"""
from unittest.mock import MagicMock, patch

import pytest
import openai

import ai_generator
from ai_generator import AIGenerator
from search_tools import ToolManager, CourseSearchTool


def build_generator(create_mock):
    """Construct an AIGenerator whose OpenAI client is a mock.

    create_mock becomes client.chat.completions.create.
    """
    with patch.object(ai_generator, "OpenAI") as MockOpenAI:
        client = MagicMock()
        client.chat.completions.create = create_mock
        MockOpenAI.return_value = client
        return AIGenerator(api_key="fake", model="deepseek-chat")


def make_tool_manager(store):
    tm = ToolManager()
    tm.register_tool(CourseSearchTool(store))
    return tm


def test_direct_response_without_tools(text_response):
    create = MagicMock(return_value=text_response("Paris is the capital of France."))
    gen = build_generator(create)

    out = gen.generate_response("What is the capital of France?")

    assert out == "Paris is the capital of France."
    assert create.call_count == 1


def test_tools_and_tool_choice_passed_in_request(text_response, fake_store):
    create = MagicMock(return_value=text_response("ok"))
    gen = build_generator(create)
    tm = make_tool_manager(fake_store)

    gen.generate_response("hi", tools=tm.get_tool_definitions(), tool_manager=tm)

    kwargs = create.call_args.kwargs
    assert kwargs["tool_choice"] == "auto"
    # Anthropic-style defs were converted to OpenAI/DeepSeek function format
    fn = kwargs["tools"][0]
    assert fn["type"] == "function"
    assert fn["function"]["name"] == "search_course_content"
    assert fn["function"]["parameters"]["required"] == ["query"]


def test_tool_use_executes_tool_then_synthesizes(text_response, tool_use_response, tool_call, fake_store):
    first = tool_use_response([tool_call("search_course_content", '{"query": "MCP servers"}')])
    second = text_response("MCP servers expose tools to clients.")
    create = MagicMock(side_effect=[first, second])
    gen = build_generator(create)
    tm = make_tool_manager(fake_store)

    out = gen.generate_response("What are MCP servers?",
                                tools=tm.get_tool_definitions(),
                                tool_manager=tm)

    # Final synthesized text is returned
    assert out == "MCP servers expose tools to clients."
    # Two sequential calls: trigger search, then synthesize
    assert create.call_count == 2
    # The tool actually ran against the store with the model-supplied args
    assert fake_store.calls[0]["query"] == "MCP servers"
    # The second call still offers tools (the model simply chose not to search
    # again and returned text) — that's how the loop terminates.
    final_messages = create.call_args_list[1].kwargs["messages"]
    assert any(m.get("role") == "tool" for m in final_messages if isinstance(m, dict))


def test_multi_step_two_searches_then_synthesize(text_response, tool_use_response, tool_call, fake_store):
    """The model can search twice (e.g. compare two courses) before answering."""
    r1 = tool_use_response([tool_call("search_course_content", '{"query": "course A"}', "c1")])
    r2 = tool_use_response([tool_call("search_course_content", '{"query": "course B"}', "c2")])
    r3 = text_response("A and B both cover MCP, but differ on transport.")
    create = MagicMock(side_effect=[r1, r2, r3])
    gen = build_generator(create)
    tm = make_tool_manager(fake_store)

    out = gen.generate_response("Compare course A and course B.",
                                tools=tm.get_tool_definitions(), tool_manager=tm)

    assert out == "A and B both cover MCP, but differ on transport."
    assert create.call_count == 3                       # search, search, synthesize
    assert fake_store.calls[0]["query"] == "course A"
    assert fake_store.calls[1]["query"] == "course B"


def test_tool_loop_caps_rounds_and_forces_final(tool_use_response, tool_call, text_response, fake_store):
    """If the model never stops searching, we cap rounds and force a final answer."""
    def wants_tool():
        return tool_use_response([tool_call("search_course_content", '{"query": "x"}')])
    create = MagicMock(side_effect=[wants_tool(), wants_tool(), text_response("forced answer")])
    gen = build_generator(create)
    gen.max_tool_rounds = 2
    tm = make_tool_manager(fake_store)

    out = gen.generate_response("loop forever", tools=tm.get_tool_definitions(), tool_manager=tm)

    assert out == "forced answer"
    assert create.call_count == 3                       # 2 capped rounds + 1 forced synthesis
    # The forced final call carries no tools.
    assert "tools" not in create.call_args_list[2].kwargs


def test_generic_api_error_propagates():
    """generate_response must not swallow client errors (this is what causes the 500)."""
    create = MagicMock(side_effect=RuntimeError("network down"))
    gen = build_generator(create)

    with pytest.raises(RuntimeError):
        gen.generate_response("hi")


def test_authentication_error_propagates():
    """A bad/missing key surfaces as openai.AuthenticationError → endpoint returns an error."""
    import httpx

    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(401, request=request)
    auth_error = openai.AuthenticationError("Invalid API key", response=response, body=None)

    create = MagicMock(side_effect=auth_error)
    gen = build_generator(create)

    with pytest.raises(openai.AuthenticationError):
        gen.generate_response("hi")


@pytest.mark.integration
def test_real_deepseek_call_returns_text():
    """End-to-end against the real DeepSeek API (needs DEEPSEEK_API_KEY)."""
    from config import config

    if not config.DEEPSEEK_API_KEY:
        pytest.skip("DEEPSEEK_API_KEY not set")

    gen = AIGenerator(config.DEEPSEEK_API_KEY, config.DEEPSEEK_MODEL, config.DEEPSEEK_BASE_URL)
    out = gen.generate_response("Say the word 'pong' and nothing else.")
    assert isinstance(out, str) and out
