"""Pydantic schemas for data validation and serialization."""
from typing import List, Optional, Literal, Dict, Any
from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator, ConfigDict
from enum import Enum


class DocumentType(str, Enum):
    """Supported document types."""
    BILL = "bill"
    DISCHARGE_SUMMARY = "discharge_summary"
    ID_CARD = "id_card"
    UNKNOWN = "unknown"


class ClaimStatus(str, Enum):
    """Claim decision statuses."""
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING_REVIEW = "pending_review"


# ============================================================================
# Document Classification Schemas
# ============================================================================

class ClassifiedDocument(BaseModel):
    """Result of document classification."""
    model_config = ConfigDict(use_enum_values=True)
    
    filename: str
    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0, description="Classification confidence score")
    reasoning: Optional[str] = Field(None, description="Why this classification was chosen")


# ============================================================================
# Extracted Data Schemas (per document type)
# ============================================================================

class BillData(BaseModel):
    """Extracted data from hospital bill."""
    model_config = ConfigDict(use_enum_values=True)
    
    hospital_name: Optional[str] = Field(None, description="Name of the hospital or clinic")
    total_amount: Optional[Decimal] = Field(None, ge=0, description="Total bill amount")
    date_of_service: Optional[date] = Field(None, description="Date of service or bill date")
    patient_name: Optional[str] = Field(None, description="Patient name on the bill")
    bill_number: Optional[str] = Field(None, description="Invoice or bill number")
    line_items: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Individual charges")
    
    @field_validator('total_amount', mode='before')
    @classmethod
    def parse_amount(cls, v):
        """Parse amount from string if needed."""
        if v is None:
            return None
        if isinstance(v, str):
            # Remove currency symbols and commas
            cleaned = v.replace('$', '').replace(',', '').replace('₹', '').strip()
            try:
                return Decimal(cleaned)
            except:
                return None
        return v
    
    @field_validator('date_of_service', mode='before')
    @classmethod
    def parse_date(cls, v):
        """Parse date from various formats."""
        if v is None or isinstance(v, date):
            return v
        if isinstance(v, str):
            # Try common date formats (including Indian format with month names)
            for fmt in [
                '%Y-%m-%d',           # 2025-02-07 (ISO format)
                '%d-%b-%Y',           # 07-Feb-2025 (Indian format)
                '%d/%b/%Y',           # 07/Feb/2025
                '%m/%d/%Y',           # 02/07/2025 (US format)
                '%d/%m/%Y',           # 07/02/2025 (European format)
                '%d-%m-%Y',           # 07-02-2025
            ]:
                try:
                    return datetime.strptime(v, fmt).date()
                except:
                    continue
        return None


class DischargeSummaryData(BaseModel):
    """Extracted data from discharge summary."""
    model_config = ConfigDict(use_enum_values=True)
    
    patient_name: Optional[str] = Field(None, description="Full name of the patient")
    diagnosis: Optional[str] = Field(None, description="Primary diagnosis or condition")
    admission_date: Optional[date] = Field(None, description="Date of hospital admission")
    discharge_date: Optional[date] = Field(None, description="Date of discharge")
    treating_physician: Optional[str] = Field(None, description="Name of the doctor")
    procedures: Optional[List[str]] = Field(default_factory=list, description="Medical procedures performed")
    medications: Optional[List[str]] = Field(default_factory=list, description="Prescribed medications")
    
    @field_validator('admission_date', 'discharge_date', mode='before')
    @classmethod
    def parse_date(cls, v):
        """Parse date from various formats."""
        if v is None or isinstance(v, date):
            return v
        if isinstance(v, str):
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%d-%m-%Y']:
                try:
                    return datetime.strptime(v, fmt).date()
                except:
                    continue
        return None


class IDCardData(BaseModel):
    """Extracted data from insurance ID card."""
    model_config = ConfigDict(use_enum_values=True)
    
    policy_holder_name: Optional[str] = Field(None, description="Name on the insurance card")
    policy_number: Optional[str] = Field(None, description="Insurance policy number")
    insurance_provider: Optional[str] = Field(None, description="Name of insurance company")
    coverage_details: Optional[str] = Field(None, description="Coverage information")
    valid_from: Optional[date] = Field(None, description="Policy start date")
    valid_until: Optional[date] = Field(None, description="Policy expiry date")
    
    @field_validator('valid_from', 'valid_until', mode='before')
    @classmethod
    def parse_date(cls, v):
        """Parse date from various formats."""
        if v is None or isinstance(v, date):
            return v
        if isinstance(v, str):
            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%d-%m-%Y']:
                try:
                    return datetime.strptime(v, fmt).date()
                except:
                    continue
        return None


# ============================================================================
# Processed Document Schema
# ============================================================================

class ProcessedDocument(BaseModel):
    """A document after classification and data extraction."""
    model_config = ConfigDict(use_enum_values=True)
    
    filename: str
    type: DocumentType
    data: Dict[str, Any] = Field(default_factory=dict, description="Extracted structured data")
    raw_text: Optional[str] = Field(None, description="Original extracted text")
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    processing_errors: List[str] = Field(default_factory=list)


# ============================================================================
# Validation Schemas
# ============================================================================

class Discrepancy(BaseModel):
    """A data inconsistency found during validation."""
    field: str = Field(description="Field name where discrepancy was found")
    description: str = Field(description="Description of the discrepancy")
    severity: Literal["critical", "warning", "info"] = Field(default="warning")
    documents_involved: List[str] = Field(default_factory=list, description="Files with this issue")


class ValidationResult(BaseModel):
    """Result of cross-document validation."""
    is_valid: bool = Field(description="Whether validation passed")
    missing_documents: List[DocumentType] = Field(default_factory=list, description="Required docs not provided")
    discrepancies: List[Discrepancy] = Field(default_factory=list, description="Data inconsistencies found")
    warnings: List[str] = Field(default_factory=list, description="Non-critical warnings")
    validation_summary: str = Field(description="Human-readable validation summary")


# ============================================================================
# Claim Decision Schema
# ============================================================================

class ClaimDecision(BaseModel):
    """Final claim approval/rejection decision."""
    model_config = ConfigDict(use_enum_values=True)
    
    status: ClaimStatus = Field(description="Claim decision status")
    reason: str = Field(description="Detailed explanation for the decision")
    approved_amount: Optional[Decimal] = Field(None, ge=0, description="Approved claim amount if applicable")
    confidence: float = Field(ge=0.0, le=1.0, description="Decision confidence score")
    decision_factors: List[str] = Field(default_factory=list, description="Key factors in decision")


# ============================================================================
# API Response Schema
# ============================================================================

class ProcessClaimResponse(BaseModel):
    """Complete response for /process-claim endpoint."""
    model_config = ConfigDict(use_enum_values=True)
    
    request_id: str = Field(description="Unique request identifier for tracking")
    documents: List[Dict[str, Any]] = Field(description="Processed document data")
    validation: ValidationResult = Field(description="Validation results")
    claim_decision: ClaimDecision = Field(description="Final claim decision")
    processing_time_ms: float = Field(ge=0, description="Total processing time in milliseconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


# ============================================================================
# Error Response Schema
# ============================================================================

class ErrorDetail(BaseModel):
    """Error detail structure."""
    code: str
    message: str
    field: Optional[str] = None


class ErrorResponse(BaseModel):
    """API error response."""
    error: str
    details: List[ErrorDetail] = Field(default_factory=list)
    request_id: Optional[str] = None
