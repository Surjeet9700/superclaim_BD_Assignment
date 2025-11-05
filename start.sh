#!/bin/bash
# Quick start script for Superclaims AI Processor

echo "🏥 Superclaims AI Processor - Quick Start"
echo "=========================================="
echo ""

# Check if Python is installed
if ! command -v python &> /dev/null; then
    echo "❌ Python is not installed. Please install Python 3.11+ first."
    exit 1
fi

echo "✓ Python found: $(python --version)"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment exists"
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source venv/Scripts/activate
else
    source venv/bin/activate
fi

# Install dependencies
echo "📚 Installing dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt
echo "✓ Dependencies installed"
echo ""

# Check for .env file
if [ ! -f ".env" ]; then
    echo "⚙️ Creating .env file from template..."
    cp .env.example .env
    echo "✓ .env file created"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env file and add your API keys:"
    echo "   - GOOGLE_API_KEY (for Gemini)"
    echo "   - OR OPENAI_API_KEY (for GPT-4)"
    echo ""
    read -p "Press Enter after adding your API key to .env..."
else
    echo "✓ .env file exists"
fi

echo ""
echo "🚀 Starting application..."
echo "   API will be available at: http://localhost:8000"
echo "   Docs available at: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

# Run the application
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
