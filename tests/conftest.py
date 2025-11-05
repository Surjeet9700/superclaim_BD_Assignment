"""Pytest configuration and fixtures."""
import pytest
import asyncio
from typing import AsyncGenerator
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import app
from app.config import settings


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncGenerator:
    """Create an async test client."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing."""
    return {
        "document_type": "bill",
        "confidence": 0.95,
        "reasoning": "Contains billing information"
    }


@pytest.fixture
def sample_bill_data():
    """Sample extracted bill data."""
    return {
        "hospital_name": "Test Hospital",
        "total_amount": "5000.00",
        "date_of_service": "2024-04-10",
        "patient_name": "John Doe",
        "bill_number": "INV-12345"
    }


@pytest.fixture
def sample_discharge_data():
    """Sample extracted discharge summary data."""
    return {
        "patient_name": "John Doe",
        "diagnosis": "Fracture",
        "admission_date": "2024-04-01",
        "discharge_date": "2024-04-10",
        "treating_physician": "Dr. Smith"
    }


@pytest.fixture
def sample_pdf_bytes():
    """Create a minimal valid PDF for testing."""
    # Minimal PDF structure
    pdf_content = b"""%PDF-1.4
1 0 obj
<<
/Type /Catalog
/Pages 2 0 R
>>
endobj
2 0 obj
<<
/Type /Pages
/Kids [3 0 R]
/Count 1
>>
endobj
3 0 obj
<<
/Type /Page
/Parent 2 0 R
/MediaBox [0 0 612 792]
/Contents 4 0 R
>>
endobj
4 0 obj
<<
/Length 44
>>
stream
BT
/F1 12 Tf
100 700 Td
(Test PDF) Tj
ET
endstream
endobj
xref
0 5
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000214 00000 n 
trailer
<<
/Size 5
/Root 1 0 R
>>
startxref
308
%%EOF
"""
    return pdf_content
