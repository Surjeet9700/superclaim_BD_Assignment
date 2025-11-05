"""
Example script to test the claim processing API.

Usage:
    python example_request.py
"""
import requests
import json
from pathlib import Path


def process_claim(file_paths: list[str], api_url: str = "http://localhost:8000"):
    """
    Send claim documents to the API for processing.
    
    Args:
        file_paths: List of paths to PDF files
        api_url: Base URL of the API
    """
    endpoint = f"{api_url}/process-claim"
    
    # Prepare files
    files = []
    for file_path in file_paths:
        path = Path(file_path)
        if not path.exists():
            print(f"❌ File not found: {file_path}")
            continue
        
        if not path.suffix.lower() == '.pdf':
            print(f"⚠️  Skipping non-PDF file: {file_path}")
            continue
        
        files.append(('files', (path.name, open(file_path, 'rb'), 'application/pdf')))
        print(f"✅ Added: {path.name}")
    
    if not files:
        print("❌ No valid PDF files to process")
        return
    
    print(f"\n📤 Sending {len(files)} file(s) to {endpoint}...")
    
    try:
        response = requests.post(endpoint, files=files, timeout=120)
        
        # Close file handles
        for _, file_tuple in files:
            file_tuple[1].close()
        
        print(f"📥 Response status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("\n" + "="*70)
            print("✅ CLAIM PROCESSING SUCCESSFUL")
            print("="*70)
            
            # Display results
            print(f"\n📋 Request ID: {result['request_id']}")
            print(f"⏱️  Processing Time: {result['processing_time_ms']:.2f}ms")
            
            print(f"\n📄 Documents Processed: {len(result['documents'])}")
            for doc in result['documents']:
                print(f"  • {doc['filename']} ({doc['type']})")
            
            print(f"\n✔️  Validation Status: {'✅ Valid' if result['validation']['is_valid'] else '❌ Invalid'}")
            if result['validation']['missing_documents']:
                print(f"  Missing: {', '.join(result['validation']['missing_documents'])}")
            if result['validation']['discrepancies']:
                print(f"  Discrepancies: {len(result['validation']['discrepancies'])}")
                for disc in result['validation']['discrepancies'][:3]:  # Show first 3
                    print(f"    - {disc['description']}")
            
            print(f"\n🎯 Decision: {result['claim_decision']['status'].upper()}")
            print(f"   Reason: {result['claim_decision']['reason']}")
            if result['claim_decision']['approved_amount']:
                print(f"   Approved Amount: ${result['claim_decision']['approved_amount']}")
            print(f"   Confidence: {result['claim_decision']['confidence']:.2%}")
            
            # Save full response to file
            output_file = "claim_result.json"
            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\n💾 Full response saved to: {output_file}")
            
        else:
            print(f"\n❌ Error: {response.status_code}")
            print(response.json())
    
    except requests.exceptions.ConnectionError:
        print("❌ Connection failed. Is the server running?")
        print("   Start it with: uvicorn app.main:app --reload")
    except requests.exceptions.Timeout:
        print("❌ Request timed out. Try increasing the timeout or check server logs.")
    except Exception as e:
        print(f"❌ Error: {str(e)}")


def check_health(api_url: str = "http://localhost:8000"):
    """Check if the API is running."""
    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        if response.status_code == 200:
            print("✅ API is healthy and running")
            return True
        else:
            print(f"⚠️  API responded with status: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to API. Is it running?")
        print("   Start it with: uvicorn app.main:app --reload")
        return False


if __name__ == "__main__":
    print("🏥 Superclaims API - Example Request")
    print("="*70)
    
    # Check if API is running
    if not check_health():
        exit(1)
    
    print("\n" + "="*70)
    
    # Example: Process claim with multiple documents
    # Test with the available PDFs
    file_paths = [
        "test_file/25013102111-2_20250427_120738-Appolo.pdf",
        "test_file/25020300401-3_20250427_120739-max health.pdf",
        # "test_file/25020500888-2_20250427_120744-ganga ram.pdf",
        # "test_file/25020701680-2_20250427_120746-fortis.pdf",
    ]
    
    # If no files specified, show usage
    if not file_paths or not any(file_paths):
        print("\n📝 Usage Instructions:")
        print("="*70)
        print("1. Edit this script (example_request.py)")
        print("2. Update the 'file_paths' list with paths to your PDF files")
        print("3. Run: python example_request.py")
        print("\nExample:")
        print('  file_paths = [')
        print('      "documents/hospital_bill.pdf",')
        print('      "documents/discharge_summary.pdf",')
        print('  ]')
        print("\n💡 Or use the Swagger UI at: http://localhost:8000/docs")
        print("="*70)
        
        # Try with a test (empty list will fail gracefully)
        print("\n🧪 Running test with no files (to show error handling)...")
        process_claim([])
    else:
        process_claim(file_paths)
