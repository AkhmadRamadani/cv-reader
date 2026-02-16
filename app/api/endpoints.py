from fastapi import APIRouter, File, UploadFile, HTTPException, Request
from fastapi.responses import JSONResponse
import tempfile
import os
from typing import Dict, List, Optional
from dataclasses import asdict
from app.services.cv_parser import cv_reader
from app.core.nlp import get_nlp
from app.core.limiter import limiter
from app.utils import dataclass_to_dict
from app.models.cv import CVData

router = APIRouter()

@router.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "CV Reader API",
        "version": "1.0.0",
        "endpoints": {
            "POST /parse-cv": "Upload and parse a CV/Resume PDF",
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
@limiter.limit("5/minute")
async def parse_cv(request: Request, file: UploadFile = File(...)):
    """
    Parse a CV/Resume PDF and extract structured information
    Rate limit: 5 requests per minute
    """
    # Check file extension
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Create temporary file to save uploaded PDF
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
        temp_path = temp_file.name

        try:
            # Read and save uploaded file
            content = await file.read()
            temp_file.write(content)
            temp_file.flush()

            # Parse CV
            cv_data = cv_reader.parse_cv(temp_path)

            # Convert to dictionary
            result = dataclass_to_dict(cv_data)

            return JSONResponse(content={
                "success": True,
                "filename": file.filename,
                "data": result
            })

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error parsing CV: {str(e)}")

        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
