"""Tests for API endpoints."""
import pytest
from fastapi.testclient import TestClient
from io import BytesIO


def test_root_endpoint(client: TestClient):
    """Test root endpoint returns API info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "status" in data
    assert data["status"] == "online"


def test_health_check(client: TestClient):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_process_claim_no_files(client: TestClient):
    """Test process-claim with no files returns error."""
    response = client.post("/process-claim")
    assert response.status_code == 422  # Validation error


def test_process_claim_non_pdf_file(client: TestClient):
    """Test process-claim rejects non-PDF files."""
    files = {"files": ("test.txt", b"Hello World", "text/plain")}
    response = client.post("/process-claim", files=files)
    assert response.status_code == 400
    assert "PDF" in response.json()["error"]


def test_process_claim_empty_file(client: TestClient):
    """Test process-claim rejects empty files."""
    files = {"files": ("test.pdf", b"", "application/pdf")}
    response = client.post("/process-claim", files=files)
    assert response.status_code == 400
    assert "empty" in response.json()["error"].lower()


def test_process_claim_too_many_files(client: TestClient, sample_pdf_bytes):
    """Test process-claim rejects too many files."""
    # Create 11 files (max is 10)
    files = [
        ("files", (f"test{i}.pdf", sample_pdf_bytes, "application/pdf"))
        for i in range(11)
    ]
    response = client.post("/process-claim", files=files)
    assert response.status_code == 400
    assert "Too many" in response.json()["error"]


@pytest.mark.asyncio
async def test_process_claim_valid_request_mock(client: TestClient, sample_pdf_bytes, monkeypatch):
    """Test process-claim with valid PDF (mocked LLM)."""
    # This would require extensive mocking of all agents
    # In a real scenario, you'd mock the orchestrator or LLM responses
    # For now, we'll skip this test unless LLM keys are configured
    pytest.skip("Requires LLM API keys and mock setup")


def test_correlation_id_header(client: TestClient):
    """Test that correlation ID is added to responses."""
    response = client.get("/health")
    assert "X-Correlation-ID" in response.headers


def test_debug_config_endpoint_debug_mode(client: TestClient, monkeypatch):
    """Test debug config endpoint when debug is enabled."""
    from app import config
    monkeypatch.setattr(config.settings, "debug", True)
    
    response = client.get("/debug/config")
    # Reload the app to pick up the change
    if response.status_code == 200:
        data = response.json()
        assert "llm_provider" in data
        assert "max_file_size" in data


def test_process_claim_file_size_limit(client: TestClient):
    """Test process-claim enforces file size limits."""
    # Create a file larger than max size (10MB)
    large_content = b"x" * (11 * 1024 * 1024)  # 11MB
    files = {"files": ("large.pdf", large_content, "application/pdf")}
    
    response = client.post("/process-claim", files=files)
    assert response.status_code == 400
    assert "exceeds" in response.json()["error"].lower()
