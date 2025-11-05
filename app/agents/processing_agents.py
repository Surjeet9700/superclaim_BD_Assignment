"""Specialized agents for processing different document types."""
from typing import Dict, Any, Optional
from decimal import Decimal
from datetime import date
from app.schemas import BillData, DischargeSummaryData, IDCardData
from app.services.llm_service import get_llm_service
from app.utils.logging import get_logger

logger = get_logger(__name__)


class BillAgent:
    """
    Agent for extracting structured data from hospital bills.
    
    AI Tool Used: Cursor AI for prompt template
    Prompt: "Create a structured extraction prompt for hospital bills that extracts
    hospital name, amounts, dates, and line items in JSON format"
    """
    
    SYSTEM_PROMPT = """You are an expert medical billing data extraction specialist with OCR text understanding capabilities.
Extract structured information from hospital bills and invoices, even from poorly formatted or scanned documents.

**Your Expertise:**
- Reading OCR text with spacing issues (e.g., "M r s . Name" → "Mrs. Name")
- Identifying fields by context, not just labels (total amount may be in summary section without label)
- Parsing tables even when alignment is broken
- Finding patient/bill identifiers across multiple formats
- Handling Indian currency formats (₹, Rs., INR, lakhs, crores)

**Extraction Priorities:**
1. **Hospital Name**: Headers, footers, letterheads, addresses, or filename hints ("Apollo", "Max", "Fortis", "Ganga Ram", etc.)
2. **Total Amount**: Look for largest numerical value near "Total", "Grand Total", "Net Payable", "Amount Due", "Final Bill"
   - Check: Bill summary sections, final rows of tables, payment sections
3. **Bill/Patient IDs**: "IPID", "Bill No", "Invoice No", "Claim No", "Receipt No", "Patient ID", "Registration No"
4. **Patient Name**: After "Patient Name:", "Patient:", "Name:", or before "Age:", "Gender:"
5. **Service Date**: "Date:", "Bill Date:", "Admission Date:", "Discharge Date:", "Service Date:"
6. **Line Items**: Service descriptions + amounts from itemized sections/tables

**Critical Rules:**
- Return null ONLY if field genuinely not present after exhaustive search
- Numbers: Extract digits only (remove ₹, Rs., INR, commas) - e.g., "₹3,32,602.59" → 332602.59
- Dates: Convert to YYYY-MM-DD format (e.g., "03/02/2025" → "2025-02-03", "3-Feb-25" → "2025-02-03")
- Names: Fix OCR spacing if needed ("N ANDI RAWAT" → "NANDI RAWAT")
- Tables: Parse each row even if columns are misaligned
- Be thorough: Check headers, footers, tables, summaries, signatures, stamps, and side notes"""
    
    EXTRACTION_SCHEMA = {
        "hospital_name": "string or null",
        "total_amount": "number or null (without currency symbols)",
        "date_of_service": "string in YYYY-MM-DD format or null",
        "patient_name": "string or null",
        "bill_number": "string or null",
        "line_items": "array of objects or empty array"
    }
    
    def __init__(self):
        """Initialize bill agent."""
        self.llm = get_llm_service()
        logger.info("bill_agent_initialized")
    
    def _fix_ocr_text(self, text: str) -> str:
        """
        Fix common OCR spacing and character issues.
        
        Examples:
        - "M r s . N ANDI RAWAT" → "Mrs. NANDI RAWAT"
        - "3 2 5 6 24" → "325624"
        - "V S L I . 0 000633928" → "VSLI.0000633928"
        """
        import re
        
        # Strategy: Remove spaces between single characters when they form words/numbers
        # 1. Fix spaced digits (bill numbers, amounts, IDs)
        fixed_text = re.sub(r'(\d)\s+(?=\d)', r'\1', text)  # "3 2 5 6" → "3256"
        
        # 2. Fix spaced uppercase letters followed by lowercase (names, titles)
        fixed_text = re.sub(r'([A-Z])\s+([a-z])\s+([a-z])', r'\1\2\3', fixed_text)  # "M r s" → "Mrs"
        
        # 3. Fix spaced uppercase letters (abbreviations, codes)
        fixed_text = re.sub(r'([A-Z])\s+([A-Z])\s+([A-Z])', r'\1\2\3', fixed_text)  # "V S L" → "VSL"
        
        # 4. Fix spaced letters with dots (titles, IDs)
        fixed_text = re.sub(r'([A-Za-z])\s+([A-Za-z])\s+([A-Za-z])\s*\.', r'\1\2\3.', fixed_text)  # "M r s ." → "Mrs."
        
        # 5. Fix spaced names (NANDI RAWAT → keep space, but "N ANDI" → "NANDI")
        # Only remove space if followed by lowercase immediately after (camelCase indicator)
        fixed_text = re.sub(r'([A-Z])\s+([A-Z][a-z])', r'\1\2', fixed_text)  # "N ANDI" → "NANDI"
        
        # 6. Fix OCR character substitutions and artifacts
        ocr_fixes = {
            r'Mate\)': 'Male',  # "Mate)" → "Male"
            r'Femate\)': 'Female',  # "Femate)" → "Female"
            r'(\w+)!_\s+': r'\1 ',  # "KOSG!_ " → "KOSGI "
            r'!_': '',  # Remove !_ artifacts
            r'\s+\)': ')',  # " )" → ")"
            r'\(\s+': '(',  # "( " → "("
            r'\s+:': ':',  # " :" → ":"
            r':\s{2,}': ': ',  # ":  " → ": " (normalize spacing)
        }
        
        for pattern, replacement in ocr_fixes.items():
            fixed_text = re.sub(pattern, replacement, fixed_text)
        
        return fixed_text
    
    def _extract_with_regex(self, text: str, filename: str = "") -> BillData:
        """
        Extract bill data using regex patterns (fast, API-free fallback).
        
        Args:
            text: OCR-fixed text from bill PDF
            filename: Original filename for hospital name hints
        
        Returns:
            BillData with extracted fields (fields may be null if not found)
        """
        import re
        bill_data = BillData()
        
        # DEBUG: Log sample of text to verify OCR output
        logger.debug("regex_extraction_text_sample", 
                    filename=filename, 
                    sample=text[:800],  # First 800 chars to see header/patient info
                    total_length=len(text))
        
        # 1. Extract hospital name from filename first (most reliable)
        if filename:
            filename_lower = filename.lower()
            hospital_mappings = {
                'apollo': 'Apollo Hospitals',
                'appolo': 'Apollo Hospitals',
                'max': 'Max Healthcare',
                'fortis': 'Fortis Healthcare',
                'ganga ram': 'Sir Ganga Ram Hospital',
                'gangaram': 'Sir Ganga Ram Hospital',
                'aiims': 'AIIMS',
                'medanta': 'Medanta',
                'manipal': 'Manipal Hospitals',
            }
            
            for key, hospital_name in hospital_mappings.items():
                if key in filename_lower:
                    bill_data.hospital_name = hospital_name
                    logger.info("bill_hospital_fallback", hospital=hospital_name)
                    break
        
        # 2. If not in filename, try regex extraction from document text
        if not bill_data.hospital_name:
            hospital_patterns = [
                r'(Apollo\s+Hospitals?(?:\s+[\w\s]+)?)',
                r'(Max\s+(?:Healthcare|Hospital|Super\s+Speciality\s+Hospital)(?:\s+[\w\s]+)?)',
                r'(Fortis\s+(?:Healthcare|Hospital)(?:\s+[\w\s]+)?)',
                r'(Sir\s+Ganga\s+Ram\s+Hospital)',
                r'(AIIMS(?:\s+[\w\s]+)?)',
                r'(Medanta(?:\s+[\w\s]+)?)',
                r'(Manipal\s+Hospitals?(?:\s+[\w\s]+)?)',
            ]
            
            for pattern in hospital_patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    bill_data.hospital_name = ' '.join(match.group(1).split())
                    break
        
        # 3. Extract total amount (CRITICAL FIELD - try multiple patterns)
        amount_patterns = [
            # Insurance bill patterns (Fortis, Apollo style) - PRIORITY
            r'payor\s*amount\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+\.?[0-9]*)',
            r'net\s*(?:bill\s*)?amount\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+\.?[0-9]*)',
            r'net\s*payable\s*amount?\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*\(?\s*([0-9,]+\.?[0-9]*)\s*\)?',
            r'bill\s*amount\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+\.?[0-9]*)',
            # Common patterns
            r'(?:total|final)\s*amount\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+\.?[0-9]*)',
            r'grand\s*total\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+\.?[0-9]*)',
            r'amount\s*(?:payable|due)\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([0-9,]+\.?[0-9]*)',
        ]
        
        for pattern in amount_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            if matches:
                amounts = []
                for match in matches:
                    amount_str = match.replace(',', '').replace('₹', '').replace(')', '').replace('(', '').strip()
                    try:
                        amount = float(amount_str)
                        if amount > 1000:  # Must be at least ₹1000
                            amounts.append(amount)
                    except:
                        pass
                if amounts:
                    from decimal import Decimal
                    bill_data.total_amount = Decimal(str(max(amounts)))  # Convert to Decimal
                    logger.info("bill_amount_regex", amount=float(bill_data.total_amount), pattern=pattern[:50])
                    break
        
        # 4. Extract patient name (handle titles like Mrs., Mr., Dr.)
        name_patterns = [
            # Pattern 1: "Patient Name : Mrs. Mary Philo" (most common)
            # Capture title + 1-3 capitalized words, stop at numbers or special patterns
            r'patient\s*name\s*[:\-]?\s*((?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})(?:\s+(?:Bill|UHID|Age|Gender|\d))',
            # Pattern 2: Simpler - title + name without lookahead (may capture extra, we'll strip)
            r'patient\s*name\s*[:\-]?\s*((?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})',
            # Pattern 3: "Patient Name : Mary Philo" (no title)
            r'patient\s*name\s*[:\-]?\s*([A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
        ]
        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean up: Remove common suffixes that shouldn't be in name
                name = re.sub(r'\s+(Bill|UHID|Age|Gender|Episode|Admission).*$', '', name, flags=re.IGNORECASE)
                bill_data.patient_name = name
                logger.debug("patient_name_regex_match", pattern=pattern[:50], name=name)
                break
        
        # 5. Extract date of service (multiple formats)
        date_patterns = [
            # Date with month name: "07-Feb-2025" or "7-Feb-25" (common in Indian hospitals)
            r'(\d{1,2}[-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-/]\d{2,4})',
            # Common numeric formats with clear labels
            r'(?:bill|invoice)\s*date\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'date\s*of\s*(?:service|admission|bill)\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(?:service|admission)\s*date\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            # Date after "Admitted" keyword (common in bills)
            r'admitted\s*(?:on)?\s*[:\-]?\s*(\d{1,2}[-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-/]\d{2,4})',
            r'admitted\s*(?:on)?\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'discharge\s*(?:date|on)?\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            # Very loose: any date in header - but EXCLUDE episode numbers
            r'(?<!Episode)(?<!episode)(?<!No)(?<!/)\s(\d{1,2}[-/]\d{1,2}[-/]\d{4})(?![/\d])',  # Must have 4-digit year, not part of longer sequence
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)  # Search FULL text (not just [:1500])
            if match:
                extracted_date = match.group(1)
                # Validate it looks like a real date (day <= 31, month <= 12)
                try:
                    parts = re.split(r'[-/]', extracted_date)
                    if len(parts) == 3:
                        # Check if month is a name (Jan, Feb, etc.) or number
                        if parts[1].isalpha():
                            # Month name - valid, no need to validate numbers
                            bill_data.date_of_service = extracted_date
                            logger.debug("date_regex_match", pattern=pattern[:50], date=extracted_date, format="dd-MMM-yyyy")
                            break
                        else:
                            # Numeric month - validate day/month range
                            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                            if 1 <= day <= 31 and 1 <= month <= 12 and (year >= 2000 or year >= 24):
                                bill_data.date_of_service = extracted_date
                                logger.debug("date_regex_match", pattern=pattern[:50], date=extracted_date, format="dd/mm/yyyy")
                                break
                except:
                    pass  # Invalid date format, try next pattern
        
        # 6. Extract bill number
        bill_number_patterns = [
            r'(?:bill|invoice|receipt)\s*(?:no|number|#)\s*[:\-]?\s*([A-Z0-9\-/]+)',
            r'IPID\s*[:\-]?\s*([A-Z0-9\-/]+)',
        ]
        for pattern in bill_number_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                bill_data.bill_number = match.group(1).strip()
                break
        
        return bill_data
    
    async def extract(self, text: str, filename: str = "") -> BillData:
        """
        Extract structured data from bill text.
        
        Args:
            text: Extracted text from bill PDF (full document)
            filename: Original filename
        
        Returns:
            BillData with extracted fields
        """
        try:
            logger.info("bill_extraction_started", filename=filename)
            
            # Check if we have any meaningful text to process
            if not text or len(text.strip()) < 10:
                logger.warning("bill_extraction_no_text", filename=filename, text_length=len(text))
                return BillData()  # Return empty data, no hallucination
            
            # Fix OCR spacing issues (common in scanned PDFs)
            fixed_text = self._fix_ocr_text(text)
            
            # ======================================================
            # HYBRID APPROACH: Try REGEX FIRST, then LLM if needed
            # This saves API quota and is faster for simple bills
            # ======================================================
            bill_data = self._extract_with_regex(fixed_text, filename)
            
            # Check if we have critical fields from regex
            has_critical_fields = (
                bill_data.total_amount is not None and 
                bill_data.total_amount > 1000 and
                bill_data.patient_name is not None
            )
            
            if has_critical_fields:
                logger.info(
                    "bill_extraction_regex_success",
                    filename=filename,
                    hospital=bill_data.hospital_name,
                    amount=bill_data.total_amount,
                    patient=bill_data.patient_name
                )
                return bill_data
            
            # If regex extraction incomplete, use LLM as fallback
            logger.info("bill_extraction_using_llm_fallback", filename=filename)
            
            # For long documents, use smart chunking to stay within token limits
            # Gemini 1.5 Flash 8B: ~1M input tokens but 8K output tokens
            # Aim for 15K chars max (~3750 tokens at 4 chars/token) to leave room for response
            text_len = len(fixed_text)
            if text_len > 15000:
                # Strategy: Beginning (header) + Tables + End (footer) where totals often appear
                # Look for table sections specifically
                table_start = fixed_text.find('[TABLE]')
                table_end = fixed_text.rfind('[/TABLE]')
                
                if table_start != -1 and table_end != -1:
                    # We found table markers - prioritize table content
                    header = fixed_text[:min(3000, table_start)]
                    table_content = fixed_text[table_start:table_end + 8]  # Include [/TABLE]
                    footer = fixed_text[max(table_end + 8, text_len - 2000):]
                    sampled_text = f"{header}\n\n{table_content}\n\n{footer}"
                else:
                    # No tables - sample strategically (header, middle, footer)
                    sampled_text = f"{fixed_text[:8000]}\n\n... [middle section omitted] ...\n\n{fixed_text[-7000:]}"
                
                logger.info("bill_text_chunked", original_len=text_len, sampled_len=len(sampled_text))
            else:
                sampled_text = fixed_text
            
            prompt = f"""<DOCUMENT_ANALYSIS_TASK>

**Document Metadata:**
- Filename: {filename}
- Original Length: {text_len} characters
- Processed Length: {len(sampled_text)} characters
- Document Type: Hospital Bill / Medical Invoice

**Document Content:**
---BEGIN DOCUMENT---
{sampled_text}
---END DOCUMENT---

**Required JSON Output Format:**
{self.EXTRACTION_SCHEMA}

**DETAILED EXTRACTION INSTRUCTIONS:**

🏥 **Hospital Name** (hospital_name: string | null):
   - PRIMARY SOURCE: Filename analysis (e.g., "max health.pdf" → "Max Healthcare")
   - SECONDARY: Document header/footer/letterhead
   - PATTERNS: Look for hospital keywords + proper noun (e.g., "Apollo Hospitals", "Max Super Speciality Hospital")
   - CONTEXT CLUES: Near address, phone numbers, email, website
   - COMMON NAMES: Apollo, Max Healthcare, Fortis, Manipal, Medanta, AIIMS, Ganga Ram Hospital

💰 **Total Amount** (total_amount: number | null):
   - PRIMARY SOURCE: Final bill summary section (usually at bottom)
   - SEARCH TERMS: "Total Amount", "Grand Total", "Net Payable", "Amount Due", "Final Bill", "Payable Amount"
   - STRATEGY: Find ALL numbers near these terms, take the LARGEST (that's typically the final billable amount)
   - FORMAT: Extract digits only - remove ₹, Rs., INR, commas, spaces
   - EXAMPLES: "₹3,32,602.59" → 332602.59 | "Rs. 1,50,000" → 150000 | "INR 2.5 Lakh" → 250000
   - VERIFICATION: Should be larger than individual line items

📋 **Bill Number** (bill_number: string | null):
   - SEARCH TERMS: "Bill No", "Invoice No", "Receipt No", "IPID", "Bill ID", "Claim Number", "Reference No"
   - LOCATION: Usually in header/top-right corner
   - FORMAT: Alphanumeric (may include dashes, slashes)
   - EXAMPLES: "IPID: 325624", "Bill No: INV-2025-001234", "Receipt: RCP/2025/45678"

👤 **Patient Name** (patient_name: string | null):
   - SEARCH TERMS: "Patient Name:", "Name:", "Patient:", followed by name
   - CONTEXT: Often near "Age:", "Gender:", "Registration No:", "Patient ID:"
   - FORMAT: Proper case (e.g., "Mrs. Nandi Rawat", "Mr. John Doe")
   - OCR FIX: If spaced ("N ANDI RAWAT"), combine to "NANDI RAWAT"

📅 **Date of Service** (date_of_service: string YYYY-MM-DD | null):
   - SEARCH TERMS: "Date:", "Bill Date:", "Service Date:", "Admission Date:", "Date of Admission:"
   - FORMAT: Convert ANY date format to YYYY-MM-DD
   - EXAMPLES: "03/02/2025" → "2025-02-03" | "3-Feb-2025" → "2025-02-03" | "Feb 3, 2025" → "2025-02-03"
   - PRIORITY: Prefer "Bill Date" or "Date of Service" over "Print Date"

📊 **Line Items** (line_items: array | []):
   - SOURCE: Itemized billing table (usually largest table in document)
   - COLUMNS: Look for "Service/Description", "Quantity/Qty", "Rate/Price", "Amount"
   - PARSE STRATEGY: Extract each row as object: {{description: string, quantity: number, rate: number, amount: number}}
   - TABLE MARKERS: Text between [TABLE] and [/TABLE] tags contains structured data
   - ALIGNMENT: Rows may be misaligned - use context clues (item descriptions are usually longer text, amounts are numbers)
   - LIMIT: Extract up to 50 line items (focus on major services if more)

**CRITICAL RULES:**
✅ **Thoroughness**: Search entire document (header, body, tables, footer, signatures, stamps)
✅ **Fallback Search**: If primary term not found, try synonyms (e.g., "Total" → "Grand Total" → "Net Amount")
✅ **Context Awareness**: Use surrounding text (labels, colons, alignment) to identify fields
✅ **Number Extraction**: Extract only digits and decimal points (strip ALL formatting)
✅ **Date Standardization**: ALWAYS convert to YYYY-MM-DD format
✅ **Null Policy**: Use null ONLY if field genuinely absent after exhaustive search (don't guess/invent data)
✅ **OCR Tolerance**: Handle spacing issues, character substitution (e.g., "0" vs "O", "1" vs "l")

**OUTPUT FORMAT:**
Return ONLY valid JSON matching the schema above. No explanations, no markdown, no additional text.

</DOCUMENT_ANALYSIS_TASK>"""
            
            response = await self.llm.generate_structured(
                prompt=prompt,
                system_prompt=self.SYSTEM_PROMPT,
                max_tokens=8000,  # Increased for complex bills with many line items
            )
            
            # Parse into BillData model (with validation)
            bill_data = BillData(**response)
            
            logger.info(
                "bill_extraction_completed",
                filename=filename,
                hospital=bill_data.hospital_name,
                amount=str(bill_data.total_amount) if bill_data.total_amount else None
            )
            
            return bill_data
            
        except Exception as e:
            logger.error(
                "bill_extraction_error",
                filename=filename,
                error=str(e),
                error_type=type(e).__name__
            )
            
            # CRITICAL FALLBACK: If LLM fails, use regex extraction
            # This ensures we always return SOMETHING even if API fails
            try:
                fixed_text = self._fix_ocr_text(text)
                bill_data = self._extract_with_regex(fixed_text, filename)
                logger.info("bill_fallback_regex_used", filename=filename, hospital=bill_data.hospital_name)
                return bill_data
            except:
                # If even regex fails, return empty data (don't hallucinate)
                return BillData()


class DischargeAgent:
    """
    Agent for extracting data from discharge summaries.
    
    AI Tool Used: ChatGPT for medical terminology
    Prompt: "Create an extraction prompt for medical discharge summaries focusing on
    patient demographics, diagnosis, admission/discharge dates, and treatments"
    """
    
    SYSTEM_PROMPT = """You are a medical records data extraction specialist.
Extract structured information from hospital discharge summaries.

Focus on:
- Patient full name
- Primary diagnosis or condition
- Admission date
- Discharge date
- Treating physician name
- Medical procedures performed
- Prescribed medications

Maintain medical accuracy and extract dates in consistent format."""
    
    EXTRACTION_SCHEMA = {
        "patient_name": "string or null",
        "diagnosis": "string or null",
        "admission_date": "string in YYYY-MM-DD format or null",
        "discharge_date": "string in YYYY-MM-DD format or null",
        "treating_physician": "string or null",
        "procedures": "array of strings or empty array",
        "medications": "array of strings or empty array"
    }
    
    def __init__(self):
        """Initialize discharge agent."""
        self.llm = get_llm_service()
        logger.info("discharge_agent_initialized")
    
    async def extract(self, text: str, filename: str = "") -> DischargeSummaryData:
        """
        Extract structured data from discharge summary.
        
        Args:
            text: Extracted text from discharge summary PDF (full document)
            filename: Original filename
        
        Returns:
            DischargeSummaryData with extracted fields
        """
        try:
            logger.info("discharge_extraction_started", filename=filename)
            
            # Check if we have any meaningful text to process
            if not text or len(text.strip()) < 10:
                logger.warning("discharge_extraction_no_text", filename=filename, text_length=len(text))
                return DischargeSummaryData()  # Return empty data, no hallucination
            
            # OCR TEXT PREPROCESSING: Fix common OCR artifacts
            import re
            
            # Fix spaced characters
            fixed_text = re.sub(r'(\d)\s+(?=\d)', r'\1', text)  # "3 2 5 6" → "3256"
            fixed_text = re.sub(r'([A-Z])\s+([a-z])\s+([a-z])', r'\1\2\3', fixed_text)  # "M r s" → "Mrs"
            fixed_text = re.sub(r'([A-Z])\s+([A-Z])\s+([A-Z])', r'\1\2\3', fixed_text)  # "V S L" → "VSL"
            fixed_text = re.sub(r'([A-Za-z])\s+([A-Za-z])\s+([A-Za-z])\s*\.', r'\1\2\3.', fixed_text)  # "M r s ." → "Mrs."
            fixed_text = re.sub(r'([A-Z])\s+([A-Z][a-z])', r'\1\2', fixed_text)  # "N ANDI" → "NANDI"
            
            # Fix OCR character substitutions
            ocr_fixes = {
                r'Mate\)': 'Male',
                r'Femate\)': 'Female',
                r'(\w+)!_\s+': r'\1 ',
                r'!_': '',
                r'\s+\)': ')',
                r'\(\s+': '(',
                r'\s+:': ':',
                r':\s{2,}': ': ',
            }
            
            for pattern, replacement in ocr_fixes.items():
                fixed_text = re.sub(pattern, replacement, fixed_text)
            
            # For long documents, look for discharge summary section specifically
            text_len = len(fixed_text)
            if text_len > 10000:
                # Find "Discharge Summary" section if it exists
                text_lower = fixed_text.lower()
                discharge_pos = text_lower.find("discharge summary")
                
                if discharge_pos > 0:
                    # Extract from discharge summary section onwards (up to 5000 chars)
                    sampled_text = fixed_text[discharge_pos:discharge_pos + 5000]
                    logger.info("discharge_section_found", filename=filename, position=discharge_pos)
                else:
                    # Sample strategically from end where discharge summaries often are
                    sampled_text = f"{fixed_text[:2000]}\n\n... [middle] ...\n\n{fixed_text[-5000:]}"
            else:
                sampled_text = fixed_text
            
            prompt = f"""Extract all relevant information from this medical discharge summary:

Filename: {filename}
Content:
{sampled_text}

Return the data in this JSON format:
{self.EXTRACTION_SCHEMA}

**EXTRACTION INSTRUCTIONS**:
- **[TABLE] Content**: Look INSIDE [TABLE]...[/TABLE] sections for patient information, medical data
- **Patient Name**: Look for "Patient:", "Name:", "Mr.", "Mrs." patterns, often in first table rows
- **Diagnosis**: Look for "Diagnosis:", "Primary Diagnosis:", "Final Diagnosis:", "Condition:" in tables/sections
- **Admission Date**: Look for "Admission Date:", "Admit Date:", "Date of Admission:" - convert to YYYY-MM-DD
- **Discharge Date**: Look for "Discharge Date:", "Date of Discharge:" - convert to YYYY-MM-DD  
- **Treating Physician**: Look for "Consultant:", "Doctor:", "Physician:", "Surgeon:", "Dr." titles
- **Procedures**: Look for "Surgery:", "Procedure:", "Operation:", "Treatment:" sections
- **Medications**: Look for "Medications:", "Prescribed:", "Drugs:", "Medicine:" sections  
- **Date Format**: Convert any date format (DD/MM/YYYY, DD-MM-YYYY) to YYYY-MM-DD
- Process ALL table content systematically for medical information
- Extract even partial information - don't leave fields null if you find ANY related data"""
            
            response = await self.llm.generate_structured(
                prompt=prompt,
                system_prompt=self.SYSTEM_PROMPT,
                max_tokens=6000,  # Increased for comprehensive discharge summaries
            )
            
            # Parse into DischargeSummaryData model
            discharge_data = DischargeSummaryData(**response)
            
            # Fallback extraction if LLM fails - use original text for regex patterns
            if not discharge_data.patient_name or not discharge_data.admission_date or not discharge_data.diagnosis:
                import re
                
                # Extract patient name if missing
                if not discharge_data.patient_name:
                    # Look for "name:" or "patient:" patterns
                    name_patterns = [
                        r'(?:patient\s*name|name)\s*[:\-]\s*([A-Z][A-Za-z\s\.]{3,50}?)(?:\s+(?:age|sex|gender|male|female|yr|mth|\d)|\n)',
                        r'\b(mr|mrs|ms|miss)\.\s+([A-Z][A-Z\s]{5,40})(?:\s+(?:age|sex|male|female|yr|\d)|\n)',
                        r'uhid[:\s]+[A-Z0-9\.]+[^\n]*\n[^\n]*?([A-Z][A-Z\s]{5,40})(?:\s+(?:age|sex|male|female))',
                    ]
                    for pattern in name_patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            # Get the last captured group (the name)
                            name = match.group(match.lastindex) if match.lastindex else match.group(1)
                            discharge_data.patient_name = name.strip()
                            logger.info("patient_name_extracted_from_regex", name=discharge_data.patient_name)
                            break
                
                # Extract dates if missing
                if not discharge_data.admission_date:
                    admission_patterns = [
                        r'admission\s*date\s*[:\-]\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
                        r'admitted\s*on\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
                        r'date\s*of\s*admission\s*[:\-]\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
                    ]
                    for pattern in admission_patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            discharge_data.admission_date = match.group(1)
                            logger.info("admission_date_extracted_from_regex", date=discharge_data.admission_date)
                            break
                
                if not discharge_data.discharge_date:
                    discharge_patterns = [
                        r'discharge\s*date\s*[:\-]\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
                        r'discharged\s*on\s*[:\-]?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
                        r'date\s*of\s*discharge\s*[:\-]\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
                    ]
                    for pattern in discharge_patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            discharge_data.discharge_date = match.group(1)
                            logger.info("discharge_date_extracted_from_regex", date=discharge_data.discharge_date)
                            break
                
                # Extract diagnosis if missing
                if not discharge_data.diagnosis:
                    diagnosis_patterns = [
                        r'diagnosis\s*[:\-]\s*([^\n]{20,200})',
                        r'final\s*diagnosis\s*[:\-]\s*([^\n]{20,200})',
                        r'primary\s*diagnosis\s*[:\-]\s*([^\n]{20,200})',
                    ]
                    for pattern in diagnosis_patterns:
                        match = re.search(pattern, text, re.IGNORECASE)
                        if match:
                            discharge_data.diagnosis = match.group(1).strip()
                            logger.info("diagnosis_extracted_from_regex", diagnosis=discharge_data.diagnosis[:50])
                            break
            
            logger.info(
                "discharge_extraction_completed",
                filename=filename,
                patient=discharge_data.patient_name,
                diagnosis=discharge_data.diagnosis
            )
            
            return discharge_data
            
        except Exception as e:
            logger.error(
                "discharge_extraction_error",
                filename=filename,
                error=str(e),
                error_type=type(e).__name__
            )
            return DischargeSummaryData()


class IDCardAgent:
    """
    Agent for extracting data from insurance ID cards.
    
    AI Tool Used: Claude for insurance domain knowledge
    Prompt: "Design an extraction prompt for insurance ID cards that captures
    policy holder information, policy numbers, and coverage details"
    """
    
    SYSTEM_PROMPT = """You are an insurance document data extraction specialist.
Extract structured information from insurance ID cards and policy documents.

Focus on:
- Policy holder name
- Policy/member number
- Insurance provider/company name
- Coverage details or plan type
- Validity dates (start and end)

Extract all identifying information accurately."""
    
    EXTRACTION_SCHEMA = {
        "policy_holder_name": "string or null",
        "policy_number": "string or null",
        "insurance_provider": "string or null",
        "coverage_details": "string or null",
        "valid_from": "string in YYYY-MM-DD format or null",
        "valid_until": "string in YYYY-MM-DD format or null"
    }
    
    def __init__(self):
        """Initialize ID card agent."""
        self.llm = get_llm_service()
        logger.info("idcard_agent_initialized")
    
    async def extract(self, text: str, filename: str = "") -> IDCardData:
        """
        Extract structured data from insurance ID card.
        
        Args:
            text: Extracted text from ID card PDF
            filename: Original filename
        
        Returns:
            IDCardData with extracted fields
        """
        try:
            logger.info("idcard_extraction_started", filename=filename)
            
            prompt = f"""Extract all relevant information from this insurance ID card:

{text[:2000]}

Return the data in this JSON format:
{self.EXTRACTION_SCHEMA}

Important:
- Use YYYY-MM-DD format for dates
- Extract policy/member numbers exactly as shown
- If information is not clearly stated, use null"""
            
            response = await self.llm.generate_structured(
                prompt=prompt,
                system_prompt=self.SYSTEM_PROMPT,
            )
            
            # Parse into IDCardData model
            idcard_data = IDCardData(**response)
            
            logger.info(
                "idcard_extraction_completed",
                filename=filename,
                holder=idcard_data.policy_holder_name,
                policy=idcard_data.policy_number
            )
            
            return idcard_data
            
        except Exception as e:
            logger.error(
                "idcard_extraction_error",
                filename=filename,
                error=str(e),
                error_type=type(e).__name__
            )
            return IDCardData()


# Global agent instances
_bill_agent: Optional[BillAgent] = None
_discharge_agent: Optional[DischargeAgent] = None
_idcard_agent: Optional[IDCardAgent] = None


def get_bill_agent() -> BillAgent:
    """Get or create global bill agent instance."""
    global _bill_agent
    if _bill_agent is None:
        _bill_agent = BillAgent()
    return _bill_agent


def get_discharge_agent() -> DischargeAgent:
    """Get or create global discharge agent instance."""
    global _discharge_agent
    if _discharge_agent is None:
        _discharge_agent = DischargeAgent()
    return _discharge_agent


def get_idcard_agent() -> IDCardAgent:
    """Get or create global ID card agent instance."""
    global _idcard_agent
    if _idcard_agent is None:
        _idcard_agent = IDCardAgent()
    return _idcard_agent
