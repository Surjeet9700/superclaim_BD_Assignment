# 🚀 Quick Installation Guide

## Prerequisites (Install First!)

### 1. Python 3.12+
```bash
python --version  # Should show 3.12 or higher
```

### 2. Tesseract OCR (Required for scanned PDFs)

**Windows:**
```bash
winget install --id UB-Mannheim.TesseractOCR
# Then verify:
tesseract --version
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

**Mac:**
```bash
brew install tesseract poppler
```

---

## Installation Steps

### Step 1: Clone & Setup Virtual Environment
```bash
cd superclaims_Assignment

# Create virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate

# Linux/Mac:
source venv/bin/activate
```

### Step 2: Install Python Dependencies
```bash
pip install -r requirements.txt
```

**Expected output:**
- Installing ~50 packages
- Takes 2-5 minutes
- No errors (warnings are OK)

### Step 3: Configure Environment
```bash
# Copy example
cp .env.example .env

# Edit .env and add your Gemini API key
# Get key from: https://makersuite.google.com/app/apikey
```

**.env file:**
```bash
GOOGLE_API_KEY=your_actual_api_key_here
DEFAULT_LLM_PROVIDER=google
GEMINI_MODEL=gemini-2.0-flash-lite
```

### Step 4: Verify Setup
```bash
python verify_setup.py
```

**Expected output:**
```
✅ PASS - Python Version
✅ PASS - Python Packages
✅ PASS - Tesseract OCR
✅ PASS - Poppler
✅ PASS - Environment Config

🎉 All checks passed! You're ready to run the application.
```

### Step 5: Start the Server
```bash
python -m uvicorn app.main:app --reload
```

**Server running at:**
- API: http://localhost:8000
- Docs: http://localhost:8000/docs

---

## Quick Test

```bash
curl -X POST "http://localhost:8000/api/v1/claims/process" \
  -F "files=@test_data/Fortis_Healthcare_Bill.pdf"
```

---

## Troubleshooting

### ❌ "GOOGLE_API_KEY not set"
- Check `.env` file exists
- Verify API key is valid
- Get key from: https://makersuite.google.com/app/apikey

### ❌ "Tesseract not found"
**Windows:**
```bash
# Check installation
where tesseract

# If not found, reinstall
winget install --id UB-Mannheim.TesseractOCR

# Add to PATH (may need restart)
setx PATH "%PATH%;C:\Program Files\Tesseract-OCR"
```

**Linux/Mac:**
```bash
which tesseract
# If not found:
sudo apt-get install tesseract-ocr  # Linux
brew install tesseract              # Mac
```

### ❌ "Module not found" errors
```bash
# Make sure venv is activated
# Windows: venv\Scripts\activate
# Linux/Mac: source venv/bin/activate

# Reinstall dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### ❌ "Port 8000 already in use"
```bash
# Use different port
python -m uvicorn app.main:app --reload --port 8001
```

---

## System Requirements

- **RAM:** 4GB minimum, 8GB recommended
- **Disk:** 500MB for dependencies + space for PDFs
- **Network:** Internet connection for Gemini API calls
- **OS:** Windows 10+, Ubuntu 20.04+, macOS 12+

---

## What Gets Installed

### Python Packages (57 total)
- FastAPI 0.109.0 - Web framework
- LangGraph 0.6.11 - Agent orchestration
- google-generativeai 0.8.5 - Gemini API
- pytesseract 0.3.10 - OCR binding
- pdf2image 1.16.3 - PDF to image
- pdfplumber 0.10.3 - PDF parsing
- ... and 51 more (see requirements.txt)

### System Binaries (Install separately)
- Tesseract OCR v5.0+ - OCR engine
- Poppler v23.0+ - PDF rendering

---

## Verification Commands

After installation, run these to verify:

```bash
# Python version
python --version

# Virtual environment active (should show venv path)
which python  # Linux/Mac
where python  # Windows

# Packages installed
pip list | grep fastapi
pip list | grep langraph
pip list | grep pytesseract

# Tesseract working
tesseract --version

# Full verification
python verify_setup.py
```

---

## Next Steps

1. ✅ Install prerequisites (Python, Tesseract)
2. ✅ Create virtual environment
3. ✅ Install requirements.txt
4. ✅ Configure .env with API key
5. ✅ Run verify_setup.py
6. ✅ Start server
7. 🎉 Process your first claim!

**For detailed documentation, see:** `README.md`
