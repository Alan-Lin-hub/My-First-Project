import warnings
warnings.filterwarnings("ignore", message="resource_tracker: There appear to be.*")

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from typing import List, Optional
import os
import openai

# Where uploaded course documents are stored (also auto-loaded on startup)
DOCS_PATH = "../docs"
ALLOWED_UPLOAD_EXTENSIONS = (".txt", ".pdf", ".docx")

from config import config
from rag_system import RAGSystem

# Initialize FastAPI app
app = FastAPI(title="Course Materials RAG System", root_path="")

# Add trusted host middleware for proxy
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]
)

# Enable CORS with proper settings for proxy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Initialize RAG system
rag_system = RAGSystem(config)

# Pydantic models for request/response
class QueryRequest(BaseModel):
    """Request model for course queries"""
    query: str
    session_id: Optional[str] = None

class QueryResponse(BaseModel):
    """Response model for course queries"""
    answer: str
    sources: List[str]
    session_id: str

class CourseStats(BaseModel):
    """Response model for course statistics"""
    total_courses: int
    course_titles: List[str]

class CourseUploadResponse(BaseModel):
    """Response model for a course document upload"""
    course_title: str
    lessons: int
    chunks: int
    replaced: bool
    filename: str

# API Endpoints

@app.post("/api/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest):
    """Process a query and return response with sources"""
    # Fail fast with a clear message if the API key is not configured
    if not config.DEEPSEEK_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="DEEPSEEK_API_KEY is not configured — copy .env.example to .env and add your DeepSeek API key, then restart the server."
        )
    try:
        # Create session if not provided
        session_id = request.session_id
        if not session_id:
            session_id = rag_system.session_manager.create_session()

        # Process query using RAG system
        answer, sources = rag_system.query(request.query, session_id)

        return QueryResponse(
            answer=answer,
            sources=sources,
            session_id=session_id
        )
    except openai.AuthenticationError:
        raise HTTPException(
            status_code=502,
            detail="DeepSeek rejected the API key (authentication failed). Check DEEPSEEK_API_KEY in your .env file."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/courses", response_model=CourseStats)
async def get_course_stats():
    """Get course analytics and statistics"""
    try:
        analytics = rag_system.get_course_analytics()
        return CourseStats(
            total_courses=analytics["total_courses"],
            course_titles=analytics["course_titles"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/courses/upload", response_model=CourseUploadResponse)
async def upload_course(file: UploadFile = File(...)):
    """Upload a course document, save it to docs/, and ingest it immediately."""
    # Validate file type (use only the basename to avoid path traversal)
    filename = os.path.basename(file.filename or "")
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided.")
    if not filename.lower().endswith(ALLOWED_UPLOAD_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_UPLOAD_EXTENSIONS)}"
        )

    # Persist the file into docs/ so it also survives restarts
    os.makedirs(DOCS_PATH, exist_ok=True)
    dest_path = os.path.join(DOCS_PATH, filename)
    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")
        with open(dest_path, "wb") as f:
            f.write(contents)

        # Process and ingest immediately (replaces an existing same-title course)
        summary = rag_system.add_or_update_course_document(dest_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to ingest document: {e}")

    return CourseUploadResponse(filename=filename, **summary)

@app.on_event("startup")
async def startup_event():
    """Load initial documents on startup"""
    if not config.DEEPSEEK_API_KEY:
        print("WARNING: DEEPSEEK_API_KEY is not set — queries will fail until you add it to .env (see .env.example).")

    docs_path = "../docs"
    if os.path.exists(docs_path):
        print("Loading initial documents...")
        try:
            courses, chunks = rag_system.add_course_folder(docs_path, clear_existing=False)
            print(f"Loaded {courses} courses with {chunks} chunks")
        except Exception as e:
            print(f"Error loading documents: {e}")

# Custom static file handler with no-cache headers for development
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pathlib import Path


class DevStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if isinstance(response, FileResponse):
            # Add no-cache headers for development
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response
    
    
# Serve static files for the frontend
app.mount("/", StaticFiles(directory="../frontend", html=True), name="static")