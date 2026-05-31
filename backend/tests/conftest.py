"""Shared pytest fixtures and fakes for the backend test suite.

These tests mock the DeepSeek (OpenAI-compatible) API and use a fake vector
store, so they need no API key and make no network calls. Tests marked
`integration` are skipped by default; set RUN_INTEGRATION=1 (or DEEPSEEK_API_KEY)
to run them.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# backend/ uses flat imports (from vector_store import ...). pytest's
# `pythonpath = ["backend"]` config handles this, but add it defensively too.
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from vector_store import SearchResults  # noqa: E402


# --------------------------------------------------------------------------- #
# Fake vector store
# --------------------------------------------------------------------------- #
class FakeVectorStore:
    """Stand-in for VectorStore that returns canned SearchResults and records calls."""

    DEFAULT = SearchResults(
        documents=["Chunk about MCP servers.", "Chunk about MCP clients."],
        metadata=[
            {"course_title": "MCP: Build Rich-Context AI Apps", "lesson_number": 1},
            {"course_title": "MCP: Build Rich-Context AI Apps", "lesson_number": 2},
        ],
        distances=[0.1, 0.2],
    )

    def __init__(self, results=None):
        self._results = results if results is not None else FakeVectorStore.DEFAULT
        self.calls = []

    def search(self, query, course_name=None, lesson_number=None, limit=None):
        self.calls.append({
            "query": query,
            "course_name": course_name,
            "lesson_number": lesson_number,
            "limit": limit,
        })
        return self._results


@pytest.fixture
def fake_store():
    """A FakeVectorStore preloaded with two MCP content chunks."""
    return FakeVectorStore()


@pytest.fixture
def store_factory():
    """Return the FakeVectorStore class so tests can build stores with custom results."""
    return FakeVectorStore


# --------------------------------------------------------------------------- #
# Fake DeepSeek / OpenAI-compatible responses
# --------------------------------------------------------------------------- #
def _text_response(text):
    """Build a chat-completion response carrying a plain text answer (no tool call)."""
    message = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


def _tool_call(name, arguments, call_id="call_1"):
    """Build one tool_call object (arguments is a JSON string, as DeepSeek returns)."""
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _tool_use_response(tool_calls):
    """Build a chat-completion response that asks to call one or more tools."""
    message = SimpleNamespace(content=None, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="tool_calls")])


@pytest.fixture
def text_response():
    return _text_response


@pytest.fixture
def tool_call():
    return _tool_call


@pytest.fixture
def tool_use_response():
    return _tool_use_response


# --------------------------------------------------------------------------- #
# Skip integration tests unless explicitly enabled
# --------------------------------------------------------------------------- #
def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_INTEGRATION") or os.getenv("DEEPSEEK_API_KEY"):
        return
    skip = pytest.mark.skip(
        reason="integration test — set RUN_INTEGRATION=1 or DEEPSEEK_API_KEY to run"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
