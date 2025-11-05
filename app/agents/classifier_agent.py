"""Document classification agent."""
from typing import List, Optional
from app.schemas import DocumentType, ClassifiedDocument
from app.services.llm_service import get_llm_service
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ClassifierAgent:
    """
    Agent responsible for classifying uploaded documents.
    
    AI Tool Used: Claude for prompt engineering
    Prompt: "Design a few-shot classification prompt for medical insurance documents
    that can identify bills, discharge summaries, and ID cards from filename and content"
    """
    
    # Classification prompt template
    CLASSIFICATION_SYSTEM_PROMPT = """You are a medical insurance document classifier.
Your task is to identify the PRIMARY document type based on its filename and content samples.

**IMPORTANT**: Medical PDFs often contain MULTIPLE sections. You will see samples from the 
beginning, middle, and end of the document. Classify based on the DOMINANT content.

Document Types:
1. **bill** - Hospital bills, invoices, medical bills, payment receipts
2. **discharge_summary** - Hospital discharge summaries, medical reports, treatment summaries  
3. **id_card** - Insurance ID cards, policy cards, member cards
4. **unknown** - Cannot determine or doesn't fit the above categories

Key Indicators:
- Bill: Invoice numbers, itemized charges, billing amounts, payment details
- Discharge Summary: Diagnosis, admission/discharge dates, treatment procedures, surgeon names
- ID Card: Member ID, policy numbers, insurance company branding

Consider the ENTIRE document content provided, not just the first page."""
    
    CLASSIFICATION_EXAMPLES = """
Examples:

Filename: "apollo_hospital_bill_12345.pdf"
Content: "INVOICE... Patient Name... Total Amount... Consultation Charges..."
Type: bill
Reason: Contains invoice terminology and billing information

Filename: "discharge_summary_john_doe.pdf"  
Content: "DISCHARGE SUMMARY... Diagnosis: Fracture... Admission Date... Treatment provided..."
Type: discharge_summary
Reason: Contains clinical information and discharge details

Filename: "insurance_card_front.pdf"
Content: "MEMBER ID: 123456... Policy Number... Valid Through..."
Type: id_card
Reason: Contains insurance policy information

Filename: "document_001.pdf"
Content: "..."
Type: unknown
Reason: Insufficient information to classify"""
    
    def __init__(self):
        """Initialize classifier agent."""
        self.llm = get_llm_service()
        logger.info("classifier_agent_initialized")
    
    def _build_classification_prompt(
        self,
        filename: str,
        content_preview: str,
    ) -> str:
        """Build the classification prompt with strategic sampling."""
        # Sample from beginning, middle, and end to catch multi-section documents
        content_len = len(content_preview)
        
        if content_len > 6000:
            # For long documents, sample strategically but use less content
            start = content_preview[:2000]  # Reduced from 3000
            middle_pos = content_len // 2
            middle = content_preview[middle_pos:middle_pos + 1500]  # Reduced from 2000
            end = content_preview[-2000:]  # Reduced from 3000
            
            sampled = f"""=== BEGINNING ===
{start}

=== MIDDLE ===
{middle}

=== END ===
{end}"""
        else:
            # For shorter documents, use full content
            sampled = content_preview
        
        prompt = f"""Classify this document:

Filename: {filename}

Content:
{sampled}

Respond ONLY with valid JSON (no markdown):
{{
    "document_type": "bill|discharge_summary|id_card|unknown",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""
        return prompt
    
    async def classify_document(
        self,
        filename: str,
        content: str,
    ) -> ClassifiedDocument:
        """
        Classify a single document.
        
        Args:
            filename: Original filename
            content: Extracted text content
        
        Returns:
            ClassifiedDocument with type and confidence
        """
        try:
            logger.info(
                "classifying_document",
                filename=filename,
                content_length=len(content)
            )
            
            # Build prompt
            prompt = self._build_classification_prompt(filename, content)
            
            # Get classification from LLM
            response = await self.llm.generate_structured(
                prompt=prompt,
                system_prompt=self.CLASSIFICATION_SYSTEM_PROMPT + "\n\n" + self.CLASSIFICATION_EXAMPLES,
                max_tokens=500,  # Enough for classification JSON response
            )
            
            # Parse response
            doc_type_str = response.get("document_type", "unknown").lower()
            
            # Map to enum
            try:
                doc_type = DocumentType(doc_type_str)
            except ValueError:
                logger.warning(
                    "invalid_document_type",
                    filename=filename,
                    type=doc_type_str
                )
                doc_type = DocumentType.UNKNOWN
            
            confidence = float(response.get("confidence", 0.5))
            reasoning = response.get("reasoning", "")
            
            result = ClassifiedDocument(
                filename=filename,
                document_type=doc_type,
                confidence=confidence,
                reasoning=reasoning,
            )
            
            logger.info(
                "document_classified",
                filename=filename,
                type=doc_type.value,
                confidence=confidence
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "classification_error",
                filename=filename,
                error=str(e),
                error_type=type(e).__name__
            )
            
            # Fallback: classify by content and filename patterns
            return self._fallback_classification(filename, content)
    
    def _fallback_classification(self, filename: str, content: str = "") -> ClassifiedDocument:
        """Fallback classification based on filename and content patterns."""
        filename_lower = filename.lower()
        content_lower = content.lower()[:5000]  # Check first 5000 chars
        
        # Count keywords in content
        bill_keywords = ["bill no", "invoice", "billing", "gross amount", "net amount", "total amount", "payment", "receipt"]
        discharge_keywords = ["discharge summary", "diagnosis", "admission date", "discharge date", "surgeon", "procedure", "medication", "treatment"]
        
        bill_count = sum(1 for kw in bill_keywords if kw in content_lower)
        discharge_count = sum(1 for kw in discharge_keywords if kw in content_lower)
        
        # Classify based on content keywords first
        if bill_count >= 3:
            doc_type = DocumentType.BILL
            confidence = 0.7
            reasoning = f"Found {bill_count} billing keywords in content"
        elif discharge_count >= 3:
            doc_type = DocumentType.DISCHARGE_SUMMARY
            confidence = 0.7
            reasoning = f"Found {discharge_count} discharge keywords in content"
        # Then try filename patterns
        elif any(kw in filename_lower for kw in ["bill", "invoice", "receipt", "payment"]):
            doc_type = DocumentType.BILL
            confidence = 0.6
            reasoning = "Filename contains billing keywords"
        elif any(kw in filename_lower for kw in ["discharge", "summary", "report", "medical"]):
            doc_type = DocumentType.DISCHARGE_SUMMARY
            confidence = 0.6
            reasoning = "Filename contains discharge keywords"
        elif any(kw in filename_lower for kw in ["card", "id", "insurance", "policy"]):
            doc_type = DocumentType.ID_CARD
            confidence = 0.6
            reasoning = "Filename contains ID card keywords"
        else:
            doc_type = DocumentType.UNKNOWN
            confidence = 0.3
            reasoning = "No clear indicators found in filename or content"
        
        logger.info(
            "fallback_classification_used",
            filename=filename,
            type=doc_type.value,
            confidence=confidence
        )
        
        return ClassifiedDocument(
            filename=filename,
            document_type=doc_type,
            confidence=confidence,
            reasoning=reasoning
        )
    
    async def classify_batch(
        self,
        documents: List[tuple[str, str]],
    ) -> List[ClassifiedDocument]:
        """
        Classify multiple documents in parallel.
        
        Args:
            documents: List of (filename, content) tuples
        
        Returns:
            List of ClassifiedDocument results
        """
        import asyncio
        
        logger.info("batch_classification_started", count=len(documents))
        
        tasks = [
            self.classify_document(filename, content)
            for filename, content in documents
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and log them
        classified = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "batch_classification_item_failed",
                    index=i,
                    filename=documents[i][0],
                    error=str(result)
                )
                # Add fallback
                classified.append(self._fallback_classification(documents[i][0]))
            else:
                classified.append(result)
        
        logger.info("batch_classification_completed", count=len(classified))
        
        return classified


# Global agent instance
_classifier_agent: Optional[ClassifierAgent] = None


def get_classifier_agent() -> ClassifierAgent:
    """Get or create global classifier agent instance."""
    global _classifier_agent
    
    if _classifier_agent is None:
        _classifier_agent = ClassifierAgent()
    
    return _classifier_agent
