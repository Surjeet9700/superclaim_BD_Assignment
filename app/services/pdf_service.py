"""PDF text extraction service."""
import asyncio
from typing import Optional
from io import BytesIO
import PyPDF2
import pdfplumber
from app.utils.logging import get_logger

logger = get_logger(__name__)


class PDFExtractionService:
    """
    Service for extracting text from PDF files.
    
    AI Tool Used: ChatGPT for extraction strategy
    Prompt: "Create a robust PDF text extraction service that tries multiple methods
    (PyPDF2, pdfplumber) and handles various PDF formats including scanned documents"
    """
    
    @staticmethod
    async def extract_text_pypdf2(pdf_bytes: bytes) -> str:
        """Extract text using PyPDF2 (fast but limited)."""
        try:
            pdf_file = BytesIO(pdf_bytes)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            text_parts = []
            for page in pdf_reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            
            result = "\n\n".join(text_parts)
            
            logger.debug(
                "pypdf2_extraction_success",
                pages=len(pdf_reader.pages),
                text_length=len(result)
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "pypdf2_extraction_error",
                error=str(e),
                error_type=type(e).__name__
            )
            return ""
    
    @staticmethod
    async def extract_text_pdfplumber(pdf_bytes: bytes) -> str:
        """Extract text using pdfplumber (better for tables and layout)."""
        try:
            pdf_file = BytesIO(pdf_bytes)
            
            def _extract():
                with pdfplumber.open(pdf_file) as pdf:
                    text_parts = []
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            text_parts.append(text)
                        
                        # Also try to extract tables
                        tables = page.extract_tables()
                        for table in tables:
                            if table:  # Only process non-empty tables
                                table_text = "\n".join(
                                    " | ".join(str(cell) if cell else "" for cell in row)
                                    for row in table if row
                                )
                                if table_text.strip():  # Only add if table has content
                                    text_parts.append(f"\n[TABLE]\n{table_text}\n[/TABLE]\n")
                    
                    return "\n\n".join(text_parts)
            
            # Run in thread pool since pdfplumber is sync
            result = await asyncio.to_thread(_extract)
            
            logger.debug(
                "pdfplumber_extraction_success",
                text_length=len(result)
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "pdfplumber_extraction_error",
                error=str(e),
                error_type=type(e).__name__
            )
            return ""
    
    @classmethod
    async def _extract_with_ocr(cls, pdf_bytes: bytes, filename: str) -> str:
        """Extract text using OCR (Tesseract + pdf2image)."""
        try:
            import pdf2image
            import pytesseract
            import os
            from pathlib import Path
            
            # Auto-detect poppler path on Windows
            poppler_path = None
            
            # Check if we have local poppler installation
            local_poppler = Path(__file__).parent.parent.parent / "poppler-windows" / "poppler-23.08.0" / "Library" / "bin"
            if local_poppler.exists():
                poppler_path = str(local_poppler)
                logger.info("ocr_using_local_poppler", path=poppler_path)
            
            # Fallback: Check common Windows installation paths
            if not poppler_path:
                common_paths = [
                    "C:\\Program Files\\poppler\\bin",
                    "C:\\poppler\\bin",
                    "C:\\tools\\poppler\\bin",
                ]
                for path in common_paths:
                    if Path(path).exists():
                        poppler_path = path
                        break
            
            # Auto-detect Tesseract path on Windows
            tesseract_path = None
            common_tesseract_paths = [
                "C:\\Program Files\\Tesseract-OCR\\tesseract.exe",
                "C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe",
            ]
            for path in common_tesseract_paths:
                if Path(path).exists():
                    tesseract_path = path
                    break
            
            if tesseract_path:
                pytesseract.pytesseract.tesseract_cmd = tesseract_path
                
            logger.info("ocr_extraction_started", 
                       filename=filename, 
                       tesseract_path=tesseract_path,
                       poppler_path=poppler_path)
            
            # Convert PDF to images with high DPI for better OCR
            images = await asyncio.to_thread(
                pdf2image.convert_from_bytes,
                pdf_bytes,
                dpi=300,
                fmt='RGB',
                poppler_path=poppler_path,
                first_page=1,
                last_page=5  # Limit to first 5 pages to avoid timeouts
            )
            
            extracted_text = ""
            for i, image in enumerate(images):
                # Extract text from image using Tesseract
                page_text = await asyncio.to_thread(
                    pytesseract.image_to_string,
                    image,
                    lang='eng',
                    config='--psm 6'  # Uniform block of text
                )
                extracted_text += f"\n[PAGE {i+1}]\n{page_text}\n"
            
            logger.info("ocr_extraction_completed", 
                       filename=filename, 
                       pages_processed=len(images),
                       text_length=len(extracted_text))
            
            return extracted_text.strip()
            
        except Exception as e:
            logger.error("ocr_extraction_error", 
                        filename=filename, 
                        error=str(e), 
                        error_type=type(e).__name__)
            return ""
    
    @classmethod
    async def extract_text(cls, pdf_bytes: bytes, filename: str = "") -> str:
        """
        Extract text from PDF using multiple methods.
        
        Args:
            pdf_bytes: PDF file content as bytes
            filename: Original filename (for logging)
        
        Returns:
            Extracted text content
        """
        logger.info(
            "pdf_extraction_started",
            filename=filename,
            size_bytes=len(pdf_bytes)
        )
        
        # Try pdfplumber first (better quality)
        text = await cls.extract_text_pdfplumber(pdf_bytes)
        
        # Fallback to PyPDF2 if pdfplumber fails or returns empty
        if not text or len(text.strip()) < 500:  # Increased threshold for table-heavy PDFs
            logger.warning(
                "pdfplumber_insufficient_fallback_to_pypdf2",
                filename=filename,
                text_length=len(text)
            )
            text = await cls.extract_text_pypdf2(pdf_bytes)
            
        # OCR fallback for image-based PDFs 
        if not text or len(text.strip()) < 500:  # Trigger OCR for poor extractions
            logger.warning(
                "pypdf2_insufficient_attempting_ocr",
                filename=filename,
                text_length=len(text)
            )
            text = await cls._extract_with_ocr(pdf_bytes, filename)
        
        # Final check
        if not text or len(text.strip()) < 10:
            logger.warning(
                "pdf_extraction_insufficient_text",
                filename=filename,
                text_length=len(text)
            )
            return "No readable text found. This PDF may be an image or corrupted."
        
        logger.info(
            "pdf_extraction_completed",
            filename=filename,
            text_length=len(text),
            preview=text[:200].replace("\n", " ")
        )
        
        return text
    
    @classmethod
    async def extract_metadata(cls, pdf_bytes: bytes) -> dict:
        """Extract PDF metadata."""
        try:
            pdf_file = BytesIO(pdf_bytes)
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            
            metadata = pdf_reader.metadata
            
            return {
                "title": metadata.get("/Title", ""),
                "author": metadata.get("/Author", ""),
                "subject": metadata.get("/Subject", ""),
                "creator": metadata.get("/Creator", ""),
                "producer": metadata.get("/Producer", ""),
                "pages": len(pdf_reader.pages),
            }
        except Exception as e:
            logger.error("pdf_metadata_extraction_error", error=str(e))
            return {}


# Global service instance
_pdf_service: Optional[PDFExtractionService] = None


def get_pdf_service() -> PDFExtractionService:
    """Get or create global PDF extraction service instance."""
    global _pdf_service
    
    if _pdf_service is None:
        _pdf_service = PDFExtractionService()
    
    return _pdf_service
