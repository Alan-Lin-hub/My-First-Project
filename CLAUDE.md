# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A Retrieval-Augmented Generation (RAG) system that answers questions about course materials. Course documents are chunked and embedded into ChromaDB; user queries are answered by **DeepSeek** (via its OpenAI-compatible API) using a **tool-based search** approach (the model decides whether to search, rather than results being stuffed into the prompt).

## Commands

```bash
# Install dependencies (uses uv, requires Python 3.13+)
uv sync

# Run the app (serves API + frontend on http://localhost:8000)
./run.sh
# or manually:
cd backend && uv run uvicorn app:app --reload --port 8000

# Run the tests (mocked — no API key/network needed)
uv run pytest
# Include the integration tests (real DeepSeek API + ChromaDB):
RUN_INTEGRATION=1 uv run pytest        # or set DEEPSEEK_API_KEY
```

- **Always use `uv` to run the server and manage dependencies — never invoke `pip` directly.**
- Requires `DEEPSEEK_API_KEY` in a `.env` file at the repo root (copy from `.env.example`). The LLM is DeepSeek's OpenAI-compatible API (`config.DEEPSEEK_BASE_URL`, model `deepseek-chat`).
- Tests live in `backend/tests/` (pytest). Unit tests mock the DeepSeek client and a fake vector store; tests marked `integration` are skipped unless `RUN_INTEGRATION=1` or `DEEPSEEK_API_KEY` is set. No linter or build step exists.
- `main.py` at the root is an unused placeholder — the real entrypoint is `backend/app.py`.

## Architecture

### Request flow (a query end-to-end)

`frontend/script.js` (`sendMessage`) → `POST /api/query` → `backend/app.py` (`query_documents`) → `RAGSystem.query` → `AIGenerator.generate_response` → **DeepSeek API (call 1, with tools)** → if the response has `message.tool_calls`, `CourseSearchTool.execute` → `VectorStore.search` (ChromaDB) → **DeepSeek API (call 2, no tools)** to synthesize the answer → response returned with `sources`.

`RAGSystem` (`backend/rag_system.py`) is the central orchestrator that wires together all components in its constructor.

### Two-phase, two-collection vector search

`VectorStore` (`backend/vector_store.py`) maintains **two ChromaDB collections**, and search is two-step:
1. `course_catalog` — course metadata (title, instructor, lessons as JSON). A fuzzy course name like "MCP" is first **semantically resolved** to a full course title here (`_resolve_course_name`).
2. `course_content` — the actual text chunks. The resolved title + optional lesson number become a filter (`_build_filter`) for the content query.

### Tool-based search is single-pass

`AIGenerator` (`backend/ai_generator.py`) makes **exactly two sequential DeepSeek calls** when a tool is used (`_handle_tool_execution`): one to trigger the search, one to synthesize. There is **no tool-call loop** — the model can search at most once per query (also enforced by the system prompt). Multi-step retrieval (e.g. comparing two courses) is not currently possible; this is the main extension point.

DeepSeek uses the **OpenAI-compatible** chat-completions API (the `openai` SDK pointed at `DEEPSEEK_BASE_URL`). The tools in `search_tools.py` still return **Anthropic-style** definitions (`input_schema`); `AIGenerator._to_openai_tools` converts them to OpenAI `function`/`parameters` format at call time, so `search_tools.py` stays API-agnostic. Tool-call arguments come back as a JSON string and are `json.loads`-ed before dispatch.

Tools are pluggable via the `Tool` ABC and `ToolManager` in `backend/search_tools.py`. Sources for the UI are tracked as side-state on the tool (`last_sources`), retrieved by `RAGSystem.query` after generation, then reset.

### Document ingestion

Documents in `docs/` are loaded on startup (`app.py` `startup_event`) and processed by `DocumentProcessor` (`backend/document_processor.py`). They can also be uploaded at runtime via **`POST /api/courses/upload`** (multipart), which saves the file to `docs/` and ingests it immediately (`RAGSystem.add_or_update_course_document`, which **replaces** an existing same-title course rather than erroring on duplicate IDs).
- File types: `.txt`, `.pdf` (via `pypdf`), `.docx` (via `python-docx`). `read_file` dispatches by extension.
- **Structured** format: first 3 lines are `Course Title:` / `Course Link:` / `Course Instructor:`, followed by `Lesson N:` markers (each optionally followed by `Lesson Link:`).
- **Unstructured** docs (no `Course Title:` header — typical for arbitrary PDFs/DOCX): the **filename (without extension) becomes the course title**, no leading lines are dropped, and the whole document is chunked with `lesson_number` unset.
- Text is split into ~800-char sentence-based chunks with ~100-char overlap (`CHUNK_SIZE` / `CHUNK_OVERLAP` in `config.py`), and each chunk is prefixed with course/lesson context before embedding.
- **Deduplication is by course title** (the title is also the ChromaDB ID). On startup reload existing courses are skipped unless `clear_existing=True`; the upload endpoint instead replaces them.
- **ChromaDB metadata cannot be `None`** — `VectorStore.add_course_metadata` / `add_course_content` omit absent fields (instructor, course_link, lesson_number) instead of writing `None`.

### Sessions

`SessionManager` (`backend/session_manager.py`) holds conversation history **in memory only** (lost on restart), keyed by `session_id`. Defaults to remembering the last `MAX_HISTORY=2` exchanges. The frontend stores `currentSessionId` and passes it back on each query to maintain context.

### Authentication & roles (RBAC)

Login is required for everything. `backend/auth.py` + `backend/user_store.py`
implement JWT auth over a stdlib-`sqlite3` user store (`backend/users.db`,
gitignored); passwords are bcrypt-hashed.
- **Flow**: `POST /api/auth/login` → JWT (HS256, signed with `JWT_SECRET`).
  The frontend stores it in `localStorage` and sends `Authorization: Bearer …`
  via `authFetch` in `script.js`; a 401 bounces back to the login view.
- **Dependencies** (FastAPI): `get_current_user` (decode token → load user, else
  401) and `require_admin` (else 403). `/api/query` and `/api/courses` require
  login; `/api/courses/upload` and all `/api/admin/*` require admin.
- **Roles**: `user` (query/browse) and `admin` (+ upload + user management via
  `POST|GET|DELETE /api/admin/users` and `POST /api/admin/users/{id}/password`
  to reset a password). No public registration — the first admin is **seeded on
  startup** from `ADMIN_USERNAME`/`ADMIN_PASSWORD` if no admin exists; admins
  create everyone else. Any logged-in user changes their own password via
  `POST /api/auth/change-password` (min length 6). Note: changing
  `ADMIN_PASSWORD` after the admin exists does NOT re-seed — use change-password
  / admin reset instead.
- **Frontend gating** (`#addCourseSection` shown only for admins) is UX only —
  the server is the real gate.
- **Config/env** (`config.py`): `JWT_SECRET` (required; warns if empty),
  `JWT_EXPIRE_MINUTES`, `ADMIN_USERNAME`/`ADMIN_PASSWORD`, `USERS_DB_PATH`,
  `CORS_ORIGINS` (restrict in production). **Deploy behind HTTPS** — Bearer
  tokens/passwords must not traverse plain HTTP.

## Conventions & gotchas

- **Config is centralized** in `backend/config.py` (`config` singleton): model name, chunk sizes, `MAX_RESULTS`, `MAX_HISTORY`, ChromaDB path. Change behavior here, not by hardcoding elsewhere.
- **Backend imports are flat** (e.g. `from vector_store import ...`), so the app must be run from inside `backend/`.
- In `app.py`, `/api/*` routes are registered **before** the static file mount at `/` — keep that order or the SPA handler will swallow API routes.
- ChromaDB persists to `backend/chroma_db/` (gitignored). Delete it to force a full re-ingest.
- The chunk context-prefix format is **inconsistent** between intermediate and final lessons in `document_processor.py` (`process_course_document`) — a known minor quirk.
