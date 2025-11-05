# 🚀 Quick Setup Guide

## 1. Prerequisites

✅ Python 3.11 or higher
✅ pip (Python package manager)
✅ Git
✅ Google Gemini API Key OR OpenAI API Key

### Get API Keys

**Option 1: Google Gemini (Recommended)**
1. Go to https://makersuite.google.com/app/apikey
2. Create a new API key
3. Copy the key

**Option 2: OpenAI GPT-4**
1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Copy the key

## 2. Installation (5 minutes)

### Option A: Quick Start (Windows)

```bash
# 1. Clone repository
git clone <repository-url>
cd superclaims_Assignment

# 2. Run quick start script
start.bat
```

The script will:
- Create virtual environment
- Install dependencies
- Set up .env file
- Start the server

### Option B: Quick Start (Linux/Mac)

```bash
# 1. Clone repository
git clone <repository-url>
cd superclaims_Assignment

# 2. Make script executable
chmod +x start.sh

# 3. Run quick start script
./start.sh
```

### Option C: Manual Setup

```bash
# 1. Clone repository
git clone <repository-url>
cd superclaims_Assignment

# 2. Create virtual environment
python -m venv venv

# 3. Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Configure environment
cp .env.example .env
# Edit .env and add your API key

# 6. Run the application
uvicorn app.main:app --reload --port 8000
```

## 3. Configure API Key

Edit the `.env` file and add your API key:

```bash
# For Google Gemini
GOOGLE_API_KEY=your_actual_api_key_here
DEFAULT_LLM_PROVIDER=google

# OR for OpenAI
OPENAI_API_KEY=your_actual_api_key_here
DEFAULT_LLM_PROVIDER=openai
```

## 4. Verify Installation

Open your browser and go to:
- **API:** http://localhost:8000
- **Swagger Docs:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health

You should see:
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

## 5. Test with Sample Documents

### Download Sample Documents

Use the sample documents from the Google Drive link provided:
https://drive.google.com/drive/folders/10h_JxEn91Zrhgzr30bvXUmFjS_4y2I8T

### Using Swagger UI (Easiest)

1. Go to http://localhost:8000/docs
2. Click on `POST /process-claim`
3. Click "Try it out"
4. Click "Choose Files" and select your PDFs
5. Click "Execute"
6. View the response below

### Using cURL

```bash
curl -X POST "http://localhost:8000/process-claim" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@path/to/bill.pdf" \
  -F "files=@path/to/discharge_summary.pdf"
```

### Using Python

```python
import requests

url = "http://localhost:8000/process-claim"

files = [
    ('files', open('bill.pdf', 'rb')),
    ('files', open('discharge_summary.pdf', 'rb')),
]

response = requests.post(url, files=files)
print(response.json())
```

### Using Postman

1. Create new POST request to `http://localhost:8000/process-claim`
2. Go to Body tab
3. Select "form-data"
4. Add key "files" (change type to "File")
5. Select your PDF files
6. Click "Send"

## 6. Expected Response

```json
{
  "request_id": "550e8400-e29b-41d4-a716-446655440000",
  "documents": [
    {
      "filename": "bill.pdf",
      "type": "bill",
      "hospital_name": "Apollo Hospital",
      "total_amount": 12500.00,
      "date_of_service": "2024-04-10"
    },
    {
      "filename": "discharge_summary.pdf",
      "type": "discharge_summary",
      "patient_name": "John Doe",
      "diagnosis": "Fracture",
      "admission_date": "2024-04-01",
      "discharge_date": "2024-04-10"
    }
  ],
  "validation": {
    "is_valid": true,
    "missing_documents": [],
    "discrepancies": [],
    "warnings": []
  },
  "claim_decision": {
    "status": "approved",
    "reason": "All documents present with consistent data",
    "approved_amount": 12500.00,
    "confidence": 0.92
  },
  "processing_time_ms": 3542.8
}
```

## 7. Docker Deployment (Optional)

### Using Docker Compose

```bash
# 1. Make sure Docker is installed
docker --version

# 2. Create .env file with API keys
cp .env.example .env
# Edit .env and add your API key

# 3. Start all services
docker-compose up -d

# 4. View logs
docker-compose logs -f api

# 5. Access API
# http://localhost:8000
```

### Using Docker Only

```bash
# 1. Build image
docker build -t superclaims-api .

# 2. Run container
docker run -p 8000:8000 \
  -e GOOGLE_API_KEY=your_key \
  superclaims-api
```

## 8. Running Tests

```bash
# Activate virtual environment first
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# View coverage report
# Open htmlcov/index.html in browser
```

## 9. Troubleshooting

### Issue: "Module not found"
```bash
# Reinstall dependencies
pip install -r requirements.txt
```

### Issue: "GOOGLE_API_KEY not set"
```bash
# Check .env file exists and contains:
GOOGLE_API_KEY=your_actual_key
```

### Issue: "Port 8000 already in use"
```bash
# Use different port
uvicorn app.main:app --port 8001
```

### Issue: "LLM timeout"
```bash
# Increase timeout in .env
LLM_TIMEOUT=120
```

### Issue: "Import error: structlog"
```bash
# Install missing dependency
pip install structlog
```

## 10. Development Mode

For development with auto-reload:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 11. Next Steps

✅ Test with sample documents
✅ Review API documentation at /docs
✅ Check logs for agent decisions
✅ Read ARCHITECTURE.md for system design
✅ Explore the code in /app directory

## 12. Support

- **Documentation:** README.md, ARCHITECTURE.md
- **API Docs:** http://localhost:8000/docs
- **Health Check:** http://localhost:8000/health
- **Debug Config:** http://localhost:8000/debug/config (debug mode only)

---

**Estimated Setup Time:** 5-10 minutes

**First Request Processing Time:** 3-5 seconds (including LLM calls)

**Status Check:** If you can access http://localhost:8000/health and see `"status": "healthy"`, you're all set! 🎉
