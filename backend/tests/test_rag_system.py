"""Tests for RAGSystem.query handling of content questions.

The AIGenerator is mocked, so no API key/network is needed. A temporary
ChromaDB path keeps the repo clean (these tests don't query real content).
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config import config
from rag_system import RAGSystem


@pytest.fixture
def rag(tmp_path):
    """A RAGSystem wired to an isolated temp ChromaDB."""
    original = config.CHROMA_PATH
    config.CHROMA_PATH = str(tmp_path / "chroma")
    try:
        yield RAGSystem(config)
    finally:
        config.CHROMA_PATH = original


def test_query_forwards_tools_and_returns_answer(rag):
    rag.ai_generator.generate_response = MagicMock(return_value="An answer about MCP.")
    rag.search_tool.last_sources = [
        {"text": "MCP: Build Rich-Context AI Apps - Lesson 1", "link": None}
    ]

    answer, sources = rag.query("What is MCP?")

    assert answer == "An answer about MCP."
    assert sources == [{"text": "MCP: Build Rich-Context AI Apps - Lesson 1", "link": None}]

    kwargs = rag.ai_generator.generate_response.call_args.kwargs
    # The tool definitions and tool_manager are handed to the generator
    assert kwargs["tools"]
    assert kwargs["tools"][0]["name"] == "search_course_content"
    assert kwargs["tool_manager"] is rag.tool_manager


def test_query_resets_sources_afterwards(rag):
    rag.ai_generator.generate_response = MagicMock(return_value="x")
    rag.search_tool.last_sources = ["some source"]

    rag.query("any question")

    # Sources are read once then cleared for the next query
    assert rag.tool_manager.get_last_sources() == []


def test_query_passes_session_history(rag):
    rag.ai_generator.generate_response = MagicMock(return_value="hello again")
    session_id = rag.session_manager.create_session()
    rag.session_manager.add_exchange(session_id, "earlier q", "earlier a")

    rag.query("follow-up question", session_id=session_id)

    kwargs = rag.ai_generator.generate_response.call_args.kwargs
    assert kwargs["conversation_history"] is not None


@pytest.mark.integration
def test_content_query_end_to_end():
    """Full real query against DeepSeek + the populated ChromaDB."""
    if not config.DEEPSEEK_API_KEY:
        pytest.skip("DEEPSEEK_API_KEY not set")

    original = config.CHROMA_PATH
    config.CHROMA_PATH = str(Path(__file__).resolve().parent.parent / "chroma_db")
    try:
        rag = RAGSystem(config)
        answer, sources = rag.query("What is MCP?")
        assert isinstance(answer, str) and answer
    finally:
        config.CHROMA_PATH = original
