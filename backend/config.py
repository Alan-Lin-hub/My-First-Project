import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

@dataclass
class Config:
    """Configuration settings for the RAG system"""
    # DeepSeek API settings (OpenAI-compatible API)
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"  # DeepSeek-V3, supports function calling
    
    # Embedding model settings
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    
    # Document processing settings
    CHUNK_SIZE: int = 800       # Size of text chunks for vector storage
    CHUNK_OVERLAP: int = 100     # Characters to overlap between chunks
    MAX_RESULTS: int = 5         # Maximum search results to return
    MAX_HISTORY: int = 2         # Number of conversation messages to remember
    MAX_SESSIONS: int = 1000     # Cap on retained in-memory sessions (LRU-evicted)
    # Max ChromaDB distance (default L2 squared) for a fuzzy course name to count
    # as a match in _resolve_course_name. Above this, the name is treated as "no
    # such course" instead of silently snapping to the nearest title. Tune to your
    # corpus; see the calibration note in vector_store._resolve_course_name.
    # Calibrated on the 4-course sample corpus, where legit names land at
    # ~0.8-1.66 ("MCP"=1.55, "Introduction"=1.66) and unrelated queries at >=1.72
    # ("cooking pasta"=1.72). Separation is narrow — re-tune if the corpus changes.
    COURSE_NAME_MATCH_MAX_DISTANCE: float = 1.7
    
    # Database paths
    CHROMA_PATH: str = "./chroma_db"  # ChromaDB storage location

    # Login brute-force protection: after LOGIN_MAX_FAILURES failed attempts from
    # one client within LOGIN_FAILURE_WINDOW_SECONDS, further attempts are blocked
    # (HTTP 429) until the window rolls off. A successful login clears the counter.
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_FAILURE_WINDOW_SECONDS: int = 60

    # Max accepted upload size (bytes) for /api/courses/upload. Files are streamed
    # to disk and rejected (HTTP 413) once this is exceeded, so an oversized upload
    # can't exhaust memory or fill the disk.
    MAX_UPLOAD_SIZE: int = 20 * 1024 * 1024  # 20 MB

    # Authentication / RBAC settings
    JWT_SECRET: str = os.getenv("JWT_SECRET", "")          # REQUIRED in production; signs JWTs
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "720"))  # 12h
    USERS_DB_PATH: str = os.getenv("USERS_DB_PATH", "./users.db")
    # Initial admin seeded on startup if no admin exists yet
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

config = Config()


