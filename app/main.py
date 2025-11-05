"""
FastAPI main application for Superclaims AI Processor.

AI Tool Used: Cursor AI + ChatGPT for FastAPI best practices
Prompt: "Create a production-ready FastAPI application with async endpoints,
error handling, CORS, and multipart file upload support"
"""
import uuid
import time
from typing import List
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.schemas import ProcessClaimResponse, ErrorResponse, ErrorDetail, DocumentType
from app.orchestrator import get_orchestrator
from app.utils.logging import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("application_startup", version=settings.app_version)
    
    # Initialize services (lazy-loaded on first use)
    # Pre-warm the orchestrator
    try:
        orchestrator = get_orchestrator()
        logger.info("orchestrator_prewarmed")
    except Exception as e:
        logger.error("orchestrator_prewarm_failed", error=str(e))
    
    yield
    
    logger.info("application_shutdown")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered medical insurance claim document processor",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Middleware
# ============================================================================

@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add correlation ID to all requests for tracking."""
    correlation_id = request.headers.get(
        settings.correlation_id_header,
        str(uuid.uuid4())
    )
    
    # Add to structlog context
    import structlog
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    
    response = await call_next(request)
    response.headers[settings.correlation_id_header] = correlation_id
    
    return response


# ============================================================================
# Exception Handlers
# ============================================================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors."""
    errors = []
    for error in exc.errors():
        errors.append(ErrorDetail(
            code="validation_error",
            message=error["msg"],
            field=".".join(str(loc) for loc in error["loc"])
        ))
    
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="Validation Error",
            details=errors,
            request_id=request.headers.get(settings.correlation_id_header)
        ).model_dump()
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            details=[],
            request_id=request.headers.get(settings.correlation_id_header)
        ).model_dump()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors."""
    logger.error(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path
    )
    
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal Server Error",
            details=[ErrorDetail(
                code="internal_error",
                message=str(exc) if settings.debug else "An unexpected error occurred"
            )],
            request_id=request.headers.get(settings.correlation_id_header)
        ).model_dump()
    )


# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint - API information."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "online",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": settings.app_version,
    }


@app.post("/process-claim", response_model=ProcessClaimResponse)
async def process_claim(
    request: Request,
    files: List[UploadFile] = File(..., description="PDF documents to process")
):
    """
    Process insurance claim documents.
    
    This endpoint accepts multiple PDF files (bill, discharge summary, ID card),
    classifies them, extracts structured data, validates consistency,
    and makes a final approval/rejection decision.
    
    **AI Tools Used:**
    - Cursor AI: For FastAPI endpoint structure and async handling
    - Claude: For request validation logic and error handling
    - ChatGPT: For OpenAPI documentation
    
    **Example Usage:**
    ```bash
    curl -X POST "http://localhost:8000/process-claim" \\
      -H "Content-Type: multipart/form-data" \\
      -F "files=@bill.pdf" \\
      -F "files=@discharge_summary.pdf"
    ```
    
    Args:
        files: List of PDF files (1-10 files)
    
    Returns:
        ProcessClaimResponse with classification, validation, and decision
    
    Raises:
        HTTPException: If validation fails or processing errors occur
    """
    start_time = time.time()
    request_id = request.headers.get(settings.correlation_id_header, str(uuid.uuid4()))
    
    logger.info(
        "process_claim_started",
        request_id=request_id,
        file_count=len(files)
    )
    
    # ========================================================================
    # Input Validation
    # ========================================================================
    
    # Validate file count
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > settings.max_files_per_request:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files. Maximum {settings.max_files_per_request} files allowed"
        )
    
    # Validate file types and sizes
    validated_files = []
    for file in files:
        # Check extension
        if not file.filename:
            raise HTTPException(status_code=400, detail="File has no name")
        
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type for {file.filename}. Only PDF files are allowed"
            )
        
        # Read file content
        content = await file.read()
        
        # Check size
        if len(content) > settings.max_file_size:
            raise HTTPException(
                status_code=400,
                detail=f"File {file.filename} exceeds maximum size of {settings.max_file_size} bytes"
            )
        
        if len(content) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"File {file.filename} is empty"
            )
        
        validated_files.append((file.filename, content))
    
    logger.info("files_validated", count=len(validated_files))
    
    # ========================================================================
    # Process Claim through Orchestrator
    # ========================================================================
    
    try:
        orchestrator = get_orchestrator()
        
        # Run the workflow
        final_state = await orchestrator.process_claim(
            files=validated_files,
            request_id=request_id,
        )
        
        # ====================================================================
        # Build Response
        # ====================================================================
        
        # Convert processed documents to response format
        documents_response = []
        for doc in final_state["processed_docs"]:
            doc_dict = {
                "filename": doc.filename,
                "type": doc.type,
                **doc.data
            }
            documents_response.append(doc_dict)
        
        # Calculate processing time
        processing_time_ms = (time.time() - start_time) * 1000
        
        # Build metadata
        metadata = {
            "files_processed": len(validated_files),
            "documents_classified": len(final_state["classified_docs"]),
            "errors": final_state["errors"] if final_state["errors"] else [],
        }
        
        # Ensure we have validation and decision
        if not final_state["validation"] or not final_state["decision"]:
            raise HTTPException(
                status_code=500,
                detail="Processing incomplete. Check logs for details."
            )
        
        response = ProcessClaimResponse(
            request_id=request_id,
            documents=documents_response,
            validation=final_state["validation"],
            claim_decision=final_state["decision"],
            processing_time_ms=processing_time_ms,
            metadata=metadata,
        )
        
        logger.info(
            "process_claim_completed",
            request_id=request_id,
            status=response.claim_decision.status,
            processing_time_ms=processing_time_ms
        )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "process_claim_error",
            request_id=request_id,
            error=str(e),
            error_type=type(e).__name__
        )
        raise HTTPException(
            status_code=500,
            detail=f"Claim processing failed: {str(e)}"
        )


# ============================================================================
# Admin/Debug Endpoints (optional)
# ============================================================================

@app.get("/debug/config")
async def debug_config():
    """Debug endpoint to view current configuration (disable in production)."""
    if not settings.debug:
        raise HTTPException(status_code=404, detail="Not found")
    
    return {
        "llm_provider": settings.default_llm_provider,
        "gemini_model": settings.gemini_model,
        "openai_model": settings.openai_model,
        "max_file_size": settings.max_file_size,
        "max_files": settings.max_files_per_request,
        "redis_enabled": settings.redis_enabled,
        "postgres_enabled": settings.postgres_enabled,
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
