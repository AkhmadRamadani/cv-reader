from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.endpoints import router
from app.core.config import settings
from app.core.nlp import load_nlp
from app.core.limiter import limiter

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Extract structured information from CV/Resume PDFs",
    version=settings.VERSION
)

# Initialize Limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Load spacy model on startup"""
    load_nlp()

app.include_router(router)
