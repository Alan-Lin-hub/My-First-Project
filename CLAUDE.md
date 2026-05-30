# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Retrieval-Augmented Generation (RAG) system that answers questions about course materials. Course documents are chunked and embedded into ChromaDB; user queries are answered by Claude using a **tool-based search** approach (Claude decides whether to search, rather than results being stuffed into the prompt).

## Commands

```bash
# Install dependencies (uses uv, requires Python 3.13+)
uv sync

# Run the app (serves API + frontend on http://localhost:8000)
./run.sh
# or manually:
cd backend && uv run uvicorn app:app --reload --port 8000
```

- **Always use `uv` to run the server and manage dependencies — never invoke `pip` directly.**
- Requires `ANTHROPIC_API_KEY` in a `.env` file at the repo root (copy from `.env.example`).
- No test suite, linter, or build step exists in this repo.
- `main.py` at the root is an unused placeholder — the real entrypoint is `backend/app.py`.

## Architecture

### Request flow (a query end-to-end)

`frontend/script.js` (`sendMessage`) → `POST /api/query` → `backend/app.py` (`query_documents`) → `RAGSystem.query` → `AIGenerator.generate_response` → **Claude API (call 1, with tools)** → if `stop_reason == "tool_use"`, `CourseSearchTool.execute` → `VectorStore.search` (ChromaDB) → **Claude API (call 2, no tools)** to synthesize the answer → response returned with `sources`.

`RAGSystem` (`backend/rag_system.py`) is the central orchestrator that wires together all components in its constructor.

### Two-phase, two-collection vector search

`VectorStore` (`backend/vector_store.py`) maintains **two ChromaDB collections**, and search is two-step:
1. `course_catalog` — course metadata (title, instructor, lessons as JSON). A fuzzy course name like "MCP" is first **semantically resolved** to a full course title here (`_resolve_course_name`).
2. `course_content` — the actual text chunks. The resolved title + optional lesson number become a filter (`_build_filter`) for the content query.

### Tool-based search is single-pass

`AIGenerator` (`backend/ai_generator.py`) makes **exactly two sequential Claude calls** when a tool is used (`_handle_tool_execution`): one to trigger the search, one to synthesize. There is **no tool-call loop** — Claude can search at most once per query (also enforced by the system prompt). Multi-step retrieval (e.g. comparing two courses) is not currently possible; this is the main extension point.

Tools are pluggable via the `Tool` ABC and `ToolManager` in `backend/search_tools.py`. Sources for the UI are tracked as side-state on the tool (`last_sources`), retrieved by `RAGSystem.query` after generation, then reset.

### Document ingestion

Documents in `docs/` are loaded on startup (`app.py` `startup_event`) and processed by `DocumentProcessor` (`backend/document_processor.py`):
- Expected format: first 3 lines are `Course Title:` / `Course Link:` / `Course Instructor:`, followed by `Lesson N:` markers (each optionally followed by `Lesson Link:`).
- Text is split into ~800-char sentence-based chunks with ~100-char overlap (`CHUNK_SIZE` / `CHUNK_OVERLAP` in `config.py`), and each chunk is prefixed with course/lesson context before embedding.
- **Deduplication is by course title** (the title is also the ChromaDB ID). Existing courses are skipped on reload unless `clear_existing=True`.

### Sessions

`SessionManager` (`backend/session_manager.py`) holds conversation history **in memory only** (lost on restart), keyed by `session_id`. Defaults to remembering the last `MAX_HISTORY=2` exchanges. The frontend stores `currentSessionId` and passes it back on each query to maintain context.

## Conventions & gotchas

- **Config is centralized** in `backend/config.py` (`config` singleton): model name, chunk sizes, `MAX_RESULTS`, `MAX_HISTORY`, ChromaDB path. Change behavior here, not by hardcoding elsewhere.
- **Backend imports are flat** (e.g. `from vector_store import ...`), so the app must be run from inside `backend/`.
- In `app.py`, `/api/*` routes are registered **before** the static file mount at `/` — keep that order or the SPA handler will swallow API routes.
- ChromaDB persists to `backend/chroma_db/` (gitignored). Delete it to force a full re-ingest.
- The chunk context-prefix format is **inconsistent** between intermediate and final lessons in `document_processor.py` (`process_course_document`) — a known minor quirk.
