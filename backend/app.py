import warnings
warnings.filterwarnings("ignore", message="resource_tracker: There appear to be.*")

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
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
from user_store import UserStore
import auth
from auth import get_current_user, require_admin, create_access_token

# Initialize FastAPI app
app = FastAPI(title="Course Materials RAG System", root_path="")

# Add trusted host middleware for proxy
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]
)

# Enable CORS. In production set CORS_ORIGINS to your real frontend origin(s),
# comma-separated, instead of the permissive "*" default.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # We authenticate with Bearer tokens (not cookies), so credentials aren't needed.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Initialize RAG system and user store
rag_system = RAGSystem(config)
user_store = UserStore(config.USERS_DB_PATH)
auth.set_user_store(user_store)

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

class LoginRequest(BaseModel):
    """Request model for login"""
    username: str
    password: str

class TokenResponse(BaseModel):
    """Response model for a successful login"""
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str

class UserOut(BaseModel):
    """Public-safe user representation (never includes the password hash)"""
    id: int
    username: str
    role: str
    created_at: Optional[str] = None

class CreateUserRequest(BaseModel):
    """Request model for admin-created users"""
    username: str
    password: str
    role: str = "user"

class ChangePasswordRequest(BaseModel):
    """Request model for a user changing their own password"""
    old_password: str
    new_password: str

class ResetPasswordRequest(BaseModel):
    """Request model for an admin resetting another user's password"""
    new_password: str

MIN_PASSWORD_LENGTH = 6

def _validate_password(password: str):
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
        )

# API Endpoints

# ---- Auth -------------------------------------------------------------- #
@app.post("/api/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Authenticate with username/password and receive a JWT."""
    user = user_store.verify_login(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(username=user["username"], role=user["role"])
    return TokenResponse(access_token=token, username=user["username"], role=user["role"])

@app.get("/api/auth/me", response_model=UserOut)
async def whoami(current=Depends(get_current_user)):
    """Return the currently authenticated user (drives frontend role gating)."""
    return UserOut(id=current["id"], username=current["username"], role=current["role"])

@app.post("/api/auth/change-password", status_code=204)
async def change_password(request: ChangePasswordRequest, current=Depends(get_current_user)):
    """Change the current user's own password (requires the old password)."""
    if not user_store.verify_login(current["username"], request.old_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    _validate_password(request.new_password)
    user_store.update_password(current["id"], request.new_password)
    return None

# ---- Admin: user management -------------------------------------------- #
@app.get("/api/admin/users", response_model=List[UserOut])
async def list_users(admin=Depends(require_admin)):
    """List all users (admin only)."""
    return [UserOut(**u) for u in user_store.list_users()]

@app.post("/api/admin/users", response_model=UserOut, status_code=201)
async def create_user(request: CreateUserRequest, admin=Depends(require_admin)):
    """Create a new user with a role (admin only)."""
    try:
        user = user_store.create_user(request.username, request.password, request.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return UserOut(**user)

@app.delete("/api/admin/users/{user_id}", status_code=204)
async def delete_user(user_id: int, admin=Depends(require_admin)):
    """Delete a user (admin only). Refuses to remove the last admin."""
    target = next((u for u in user_store.list_users() if u["id"] == user_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["role"] == "admin" and user_store.count_admins() <= 1:
        raise HTTPException(status_code=400, detail="Cannot delete the last admin account")
    user_store.delete_user(user_id)
    return None

@app.post("/api/admin/users/{user_id}/password", status_code=204)
async def reset_user_password(user_id: int, request: ResetPasswordRequest, admin=Depends(require_admin)):
    """Reset another user's password (admin only)."""
    _validate_password(request.new_password)
    if not user_store.update_password(user_id, request.new_password):
        raise HTTPException(status_code=404, detail="User not found")
    return None

@app.post("/api/query", response_model=QueryResponse)
async def query_documents(request: QueryRequest, current=Depends(get_current_user)):
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
async def get_course_stats(current=Depends(get_current_user)):
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
async def upload_course(file: UploadFile = File(...), admin=Depends(require_admin)):
    """Upload a course document, save it to docs/, and ingest it immediately. Admin only."""
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
    """Seed the initial admin and load initial documents on startup"""
    if not config.DEEPSEEK_API_KEY:
        print("WARNING: DEEPSEEK_API_KEY is not set — queries will fail until you add it to .env (see .env.example).")

    if not config.JWT_SECRET:
        print("WARNING: JWT_SECRET is not set — set a strong random secret in .env before deploying.")

    # Seed the initial admin account if none exists yet
    if config.ADMIN_PASSWORD:
        if user_store.seed_admin(config.ADMIN_USERNAME, config.ADMIN_PASSWORD):
            print(f"Seeded initial admin account: {config.ADMIN_USERNAME}")
    elif user_store.count_admins() == 0:
        print("WARNING: no admin exists and ADMIN_PASSWORD is not set — set ADMIN_USERNAME/ADMIN_PASSWORD in .env to create the first admin.")

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