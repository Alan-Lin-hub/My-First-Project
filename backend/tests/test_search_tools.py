"""Tests for CourseSearchTool.execute output.

These exercise the retrieval-formatting layer in isolation (fake vector store,
no ChromaDB, no LLM). They are unaffected by the Anthropic→DeepSeek switch.
"""
import pytest

from search_tools import CourseSearchTool
from vector_store import SearchResults


def test_execute_formats_results_with_headers(fake_store):
    tool = CourseSearchTool(fake_store)
    out = tool.execute("MCP")

    # Each chunk is prefixed with a [Course - Lesson N] header
    assert "[MCP: Build Rich-Context AI Apps - Lesson 1]" in out
    assert "[MCP: Build Rich-Context AI Apps - Lesson 2]" in out
    assert "Chunk about MCP servers." in out
    assert "Chunk about MCP clients." in out


def test_execute_tracks_sources(fake_store):
    tool = CourseSearchTool(fake_store)
    tool.execute("MCP")

    assert tool.last_sources == [
        "MCP: Build Rich-Context AI Apps - Lesson 1",
        "MCP: Build Rich-Context AI Apps - Lesson 2",
    ]


def test_execute_forwards_filters_to_store(fake_store):
    tool = CourseSearchTool(fake_store)
    tool.execute("some topic", course_name="MCP", lesson_number=2)

    assert fake_store.calls == [{
        "query": "some topic",
        "course_name": "MCP",
        "lesson_number": 2,
        "limit": None,
    }]


def test_execute_returns_error_string(store_factory):
    store = store_factory(results=SearchResults.empty("Search error: boom"))
    tool = CourseSearchTool(store)

    assert tool.execute("anything") == "Search error: boom"


def test_execute_empty_results_with_filter_info(store_factory):
    store = store_factory(results=SearchResults(documents=[], metadata=[], distances=[]))
    tool = CourseSearchTool(store)

    out = tool.execute("nothing here", course_name="MCP", lesson_number=3)
    assert "No relevant content found" in out
    assert "course 'MCP'" in out
    assert "lesson 3" in out


def test_tool_definition_schema(fake_store):
    definition = CourseSearchTool(fake_store).get_tool_definition()

    assert definition["name"] == "search_course_content"
    assert definition["input_schema"]["required"] == ["query"]
    assert "query" in definition["input_schema"]["properties"]


@pytest.mark.integration
def test_execute_against_real_chroma_db():
    """Smoke test proving live retrieval is healthy (real ChromaDB, no LLM)."""
    from pathlib import Path
    from config import config
    from vector_store import VectorStore

    chroma_path = Path(__file__).resolve().parent.parent / "chroma_db"
    if not chroma_path.exists():
        pytest.skip("backend/chroma_db not present")

    store = VectorStore(str(chroma_path), config.EMBEDDING_MODEL, config.MAX_RESULTS)
    tool = CourseSearchTool(store)
    out = tool.execute("MCP")

    assert isinstance(out, str)
    assert out and "No relevant content found" not in out
