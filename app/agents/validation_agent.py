"""Validation agent for cross-checking document data."""
from typing import List, Dict, Any
from datetime import date, timedelta
from decimal import Decimal
from app.schemas import (
    DocumentType,
    ValidationResult,
    Discrepancy,
    ProcessedDocument,
    BillData,
    DischargeSummaryData,
    IDCardData,
)
from app.services.llm_service import get_llm_service
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ValidationAgent:
    """
    Agent for validating and cross-checking document data.
    
    AI Tool Used: Claude for validation logic design
    Prompt: "Design comprehensive validation rules for insurance claims that check
    for data consistency across bills, discharge summaries, and ID cards"
    """
    
    SYSTEM_PROMPT = """You are an insurance claim validation specialist.
Analyze the provided documents and identify any inconsistencies, missing information,
or suspicious patterns that would affect claim processing.

Consider:
- Patient name consistency across documents
- Date alignment and logical ordering
- Amount reasonability
- Required document presence
- Data completeness"""
    
    def __init__(self):
        """Initialize validation agent."""
        self.llm = get_llm_service()
        logger.info("validation_agent_initialized")
    
    def _check_required_documents(
        self,
        documents: List[ProcessedDocument]
    ) -> List[DocumentType]:
        """Check if all required documents are present."""
        present_types = {doc.type for doc in documents}  # doc.type is already a string
        
        # Minimum required: bill and discharge_summary (use string values for comparison)
        required = {"bill", "discharge_summary"}
        
        missing = []
        for req_type_str in required:
            if req_type_str not in present_types:
                missing.append(DocumentType(req_type_str))  # Convert back to enum for return
        
        return missing
    
    def _check_patient_name_consistency(
        self,
        documents: List[ProcessedDocument]
    ) -> List[Discrepancy]:
        """Check if patient names are consistent across documents."""
        discrepancies = []
        
        names = {}
        for doc in documents:
            data = doc.data
            name = None
            
            if doc.type == "bill":
                name = data.get("patient_name")
            elif doc.type == "discharge_summary":
                name = data.get("patient_name")
            elif doc.type == "id_card":
                name = data.get("policy_holder_name")
            
            if name:
                names[doc.filename] = name.strip().lower()
        
        # Check if all names match (allowing minor variations)
        if len(names) > 1:
            name_values = list(names.values())
            first_name = name_values[0]
            
            for filename, name in names.items():
                if name != first_name and not self._names_similar(first_name, name):
                    discrepancies.append(Discrepancy(
                        field="patient_name",
                        description=f"Patient name mismatch: '{name}' in {filename} vs '{first_name}' in other documents",
                        severity="critical",
                        documents_involved=[filename]
                    ))
        
        return discrepancies
    
    def _names_similar(self, name1: str, name2: str) -> bool:
        """Check if two names are similar (handles minor variations)."""
        # Simple similarity check - can be enhanced
        name1_parts = set(name1.split())
        name2_parts = set(name2.split())
        
        # If they share at least 2 name parts, consider similar
        common = name1_parts & name2_parts
        return len(common) >= 2 or name1 == name2
    
    def _check_date_consistency(
        self,
        documents: List[ProcessedDocument]
    ) -> List[Discrepancy]:
        """Check for date-related inconsistencies."""
        discrepancies = []
        admission_date = None
        discharge_date = None
        service_date = None
        
        for doc in documents:
            data = doc.data
            
            if doc.type == "discharge_summary":
                admission_date = data.get("admission_date")
                discharge_date = data.get("discharge_date")
            elif doc.type == "bill":
                service_date = data.get("date_of_service")
        
        # Helper function to safely parse dates
        def safe_parse_date(d):
            """Parse date from string or return date object."""
            if d is None:
                return None
            if isinstance(d, date):
                return d
            if isinstance(d, str):
                # Try multiple formats
                from datetime import datetime
                for fmt in ['%Y-%m-%d', '%d-%b-%Y', '%d/%b/%Y', '%m/%d/%Y', '%d/%m/%Y', '%d-%m-%Y']:
                    try:
                        return datetime.strptime(d, fmt).date()
                    except:
                        continue
            return None
        
        # Convert dates safely
        admission_date = safe_parse_date(admission_date)
        discharge_date = safe_parse_date(discharge_date)
        service_date = safe_parse_date(service_date)
        
        # Check admission before discharge
        if admission_date and discharge_date:
            
            if discharge_date < admission_date:
                discrepancies.append(Discrepancy(
                    field="dates",
                    description=f"Discharge date ({discharge_date}) is before admission date ({admission_date})",
                    severity="critical",
                    documents_involved=["discharge_summary"]
                ))
        
        # Check service date is within admission period
        if service_date and admission_date and discharge_date:
            # Allow service date to be slightly before admission or after discharge
            buffer = timedelta(days=2)
            if service_date < (admission_date - buffer) or service_date > (discharge_date + buffer):
                discrepancies.append(Discrepancy(
                    field="date_of_service",
                    description=f"Service date ({service_date}) is outside admission period ({admission_date} to {discharge_date})",
                    severity="warning",
                    documents_involved=["bill", "discharge_summary"]
                ))
        
        return discrepancies
    
    def _check_amount_reasonability(
        self,
        documents: List[ProcessedDocument]
    ) -> List[Discrepancy]:
        """Check if bill amounts are reasonable."""
        discrepancies = []
        
        for doc in documents:
            if doc.type == "bill":
                data = doc.data
                amount = data.get("total_amount")
                
                if amount is not None:
                    if isinstance(amount, str):
                        try:
                            amount = Decimal(amount)
                        except:
                            amount = None
                    
                    if amount is not None:
                        # Flag suspicious amounts
                        if amount <= 0:
                            discrepancies.append(Discrepancy(
                                field="total_amount",
                                description=f"Bill amount is zero or negative: {amount}",
                                severity="critical",
                                documents_involved=[doc.filename]
                            ))
                        elif amount > 1000000:  # Very large amount
                            discrepancies.append(Discrepancy(
                                field="total_amount",
                                description=f"Bill amount is unusually high: {amount}",
                                severity="warning",
                                documents_involved=[doc.filename]
                            ))
        
        return discrepancies
    
    def _check_data_completeness(
        self,
        documents: List[ProcessedDocument]
    ) -> List[Discrepancy]:
        """Check if critical fields are present."""
        discrepancies = []
        
        for doc in documents:
            data = doc.data
            missing_fields = []
            
            if doc.type == "bill":
                if not data.get("hospital_name"):
                    missing_fields.append("hospital_name")
                if not data.get("total_amount"):
                    missing_fields.append("total_amount")
                if not data.get("date_of_service"):
                    missing_fields.append("date_of_service")
            
            elif doc.type == "discharge_summary":
                if not data.get("patient_name"):
                    missing_fields.append("patient_name")
                if not data.get("diagnosis"):
                    missing_fields.append("diagnosis")
                if not data.get("admission_date"):
                    missing_fields.append("admission_date")
                if not data.get("discharge_date"):
                    missing_fields.append("discharge_date")
            
            if missing_fields:
                discrepancies.append(Discrepancy(
                    field=", ".join(missing_fields),
                    description=f"Missing critical fields in {doc.filename}: {', '.join(missing_fields)}",
                    severity="warning",
                    documents_involved=[doc.filename]
                ))
        
        return discrepancies
    
    async def _llm_validation(
        self,
        documents: List[ProcessedDocument],
        rule_based_discrepancies: List[Discrepancy]
    ) -> str:
        """Use LLM for additional validation insights."""
        try:
            # Skip LLM validation if no discrepancies (saves time)
            if not rule_based_discrepancies:
                return "All rule-based validations passed. No additional concerns identified."
            
            # Prepare concise document summary (only key fields to reduce tokens)
            doc_summary = []
            for doc in documents:
                if doc.type == "bill":
                    doc_summary.append(f"Bill: patient={doc.data.get('patient_name')}, amount={doc.data.get('total_amount')}, date={doc.data.get('date_of_service')}")
                elif doc.type == "discharge_summary":
                    doc_summary.append(f"Discharge: patient={doc.data.get('patient_name')}, dates={doc.data.get('admission_date')}-{doc.data.get('discharge_date')}")
                elif doc.type == "id_card":
                    doc_summary.append(f"ID Card: holder={doc.data.get('policy_holder_name')}, policy={doc.data.get('policy_number')}")
            
            # Summarize discrepancies
            critical_count = sum(1 for d in rule_based_discrepancies if d.severity == "critical")
            warning_count = sum(1 for d in rule_based_discrepancies if d.severity == "warning")
            
            prompt = f"""Analyze this insurance claim validation:

Documents: {', '.join(doc_summary)}

Issues Found: {critical_count} critical, {warning_count} warnings
Key Issues: {', '.join(d.description for d in rule_based_discrepancies[:3])}

Provide a 1-2 sentence summary: Overall data quality assessment and whether the claim should proceed."""
            
            summary = await self.llm.generate(
                prompt=prompt,
                system_prompt=self.SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=300,  # Increased for proper validation summary
            )
            
            return summary.strip()
            
        except Exception as e:
            logger.error("llm_validation_error", error=str(e))
            return "Unable to perform additional LLM validation."
    
    async def validate(
        self,
        documents: List[ProcessedDocument]
    ) -> ValidationResult:
        """
        Perform comprehensive validation of processed documents.
        
        Args:
            documents: List of processed documents with extracted data
        
        Returns:
            ValidationResult with findings
        """
        try:
            logger.info("validation_started", document_count=len(documents))
            
            # Collect all discrepancies
            discrepancies = []
            warnings = []
            
            # Check required documents
            missing_docs = self._check_required_documents(documents)
            
            # Check patient name consistency
            discrepancies.extend(self._check_patient_name_consistency(documents))
            
            # Check date consistency
            discrepancies.extend(self._check_date_consistency(documents))
            
            # Check amount reasonability
            discrepancies.extend(self._check_amount_reasonability(documents))
            
            # Check data completeness
            discrepancies.extend(self._check_data_completeness(documents))
            
            # Get LLM validation summary
            validation_summary = await self._llm_validation(documents, discrepancies)
            
            # Determine if valid (no critical discrepancies and no missing required docs)
            critical_issues = [d for d in discrepancies if d.severity == "critical"]
            is_valid = len(critical_issues) == 0 and len(missing_docs) == 0
            
            # Collect warnings
            warnings = [d.description for d in discrepancies if d.severity == "warning"]
            
            result = ValidationResult(
                is_valid=is_valid,
                missing_documents=missing_docs,
                discrepancies=discrepancies,
                warnings=warnings,
                validation_summary=validation_summary,
            )
            
            logger.info(
                "validation_completed",
                is_valid=is_valid,
                discrepancies_count=len(discrepancies),
                missing_docs_count=len(missing_docs)
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "validation_error",
                error=str(e),
                error_type=type(e).__name__
            )
            
            # Return failed validation on error
            return ValidationResult(
                is_valid=False,
                missing_documents=[],
                discrepancies=[Discrepancy(
                    field="validation",
                    description=f"Validation failed due to error: {str(e)}",
                    severity="critical",
                    documents_involved=[]
                )],
                warnings=[],
                validation_summary="Validation process encountered an error."
            )


# Global agent instance
_validation_agent = None


def get_validation_agent() -> ValidationAgent:
    """Get or create global validation agent instance."""
    global _validation_agent
    if _validation_agent is None:
        _validation_agent = ValidationAgent()
    return _validation_agent
