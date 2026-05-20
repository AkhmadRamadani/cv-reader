from fastapi import APIRouter, File, UploadFile, HTTPException, Request
from fastapi.responses import JSONResponse
import tempfile
import os
from app.services.cv_parser import cv_reader
from app.services.llm_service import llm_service
from app.core.nlp import get_nlp
from app.core.limiter import limiter
from app.utils import dataclass_to_dict

router = APIRouter()

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc'}


@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "CV Reader API",
        "version": "2.0.0",
        "endpoints": {
            "POST /parse-cv": "Upload and parse a CV/Resume (PDF or DOCX) using regex",
            "POST /parse-cv-llm": "Upload and parse a CV/Resume using LLM (provider-agnostic)",
            "POST /extract-text": "Upload a CV and get raw extracted text",
            "GET /health": "Check API health status"
        }
    }


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    nlp = get_nlp()
    return {
        "status": "healthy",
        "spacy_loaded": nlp is not None
    }


@router.post("/parse-cv")
@limiter.limit("10/minute")
async def parse_cv(request: Request, file: UploadFile = File(...)):
    """
    Parse a CV/Resume and extract structured information.
    Supports: PDF, DOCX
    Rate limit: 10 requests per minute
    """
    # Check file extension
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
        temp_path = temp_file.name

        try:
            content = await file.read()

            # Validate file size (max 10MB)
            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail="File too large. Maximum size is 10MB."
                )

            temp_file.write(content)
            temp_file.flush()

            # Parse CV
            cv_data = cv_reader.parse_cv(temp_path)

            # Convert to dictionary (exclude raw_text from response)
            result = dataclass_to_dict(cv_data)
            result.pop('raw_text', None)

            return JSONResponse(content={
                "success": True,
                "filename": filename,
                "data": result
            })

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error parsing CV: {str(e)}"
            )
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


@router.post("/extract-text")
@limiter.limit("10/minute")
async def extract_text(request: Request, file: UploadFile = File(...)):
    """
    Extract raw text from a CV/Resume file.
    Returns the full text content without any parsing/structuring.
    Supports: PDF, DOCX
    Rate limit: 10 requests per minute
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
        temp_path = temp_file.name

        try:
            content = await file.read()

            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail="File too large. Maximum size is 10MB."
                )

            temp_file.write(content)
            temp_file.flush()

            # Extract text only
            text = cv_reader.extract_text(temp_path)

            return JSONResponse(content={
                "success": True,
                "filename": filename,
                "text": text
            })

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error extracting text: {str(e)}"
            )
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


@router.post("/parse-cv-llm")
@limiter.limit("10/minute")
async def parse_cv_llm(request: Request, file: UploadFile = File(...)):
    """
    Parse a CV/Resume using LLM for structured extraction.
    Provider-agnostic: works with Gemini, OpenAI, Anthropic, Groq, Ollama, etc.
    Configure via LLM_MODEL env var.
    Rate limit: 10 requests per minute
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as temp_file:
        temp_path = temp_file.name

        try:
            content = await file.read()

            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail="File too large. Maximum size is 10MB."
                )

            temp_file.write(content)
            temp_file.flush()

            # Step 1: Extract raw text
            raw_text = cv_reader.extract_text(temp_path)

            # Step 2: Send to LLM for structured extraction
            result = llm_service.extract_cv_structured(raw_text)

            return JSONResponse(content={
                "success": True,
                "filename": filename,
                "model": llm_service.get_model_info(),
                "data": result
            })

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error parsing CV with LLM: {str(e)}"
            )
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
