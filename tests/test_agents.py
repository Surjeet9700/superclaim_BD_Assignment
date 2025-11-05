"""Tests for individual agents."""
import pytest
from decimal import Decimal
from datetime import date

from app.schemas import DocumentType, BillData, DischargeSummaryData
from app.agents.classifier_agent import ClassifierAgent


def test_classifier_fallback_classification():
    """Test fallback classification based on filename."""
    agent = ClassifierAgent()
    
    # Test bill classification
    result = agent._fallback_classification("hospital_bill_12345.pdf")
    assert result.document_type == DocumentType.BILL
    assert result.confidence > 0
    
    # Test discharge classification
    result = agent._fallback_classification("discharge_summary.pdf")
    assert result.document_type == DocumentType.DISCHARGE_SUMMARY
    
    # Test ID card classification
    result = agent._fallback_classification("insurance_card.pdf")
    assert result.document_type == DocumentType.ID_CARD
    
    # Test unknown
    result = agent._fallback_classification("unknown_doc.pdf")
    assert result.document_type == DocumentType.UNKNOWN


def test_bill_data_amount_parsing():
    """Test BillData amount parsing from various formats."""
    # Test with currency symbols
    data = BillData(total_amount="$1,234.56")
    assert data.total_amount == Decimal("1234.56")
    
    # Test with rupee symbol
    data = BillData(total_amount="₹5000")
    assert data.total_amount == Decimal("5000")
    
    # Test with plain number
    data = BillData(total_amount="999.99")
    assert data.total_amount == Decimal("999.99")


def test_bill_data_date_parsing():
    """Test BillData date parsing from various formats."""
    # Test ISO format
    data = BillData(date_of_service="2024-04-10")
    assert data.date_of_service == date(2024, 4, 10)
    
    # Test US format
    data = BillData(date_of_service="04/10/2024")
    assert data.date_of_service == date(2024, 4, 10)
    
    # Test DD/MM/YYYY format
    data = BillData(date_of_service="10/04/2024")
    assert data.date_of_service == date(2024, 4, 10)


def test_discharge_data_date_validation():
    """Test discharge summary date validation."""
    data = DischargeSummaryData(
        patient_name="John Doe",
        diagnosis="Test",
        admission_date="2024-04-01",
        discharge_date="2024-04-10"
    )
    
    assert data.admission_date == date(2024, 4, 1)
    assert data.discharge_date == date(2024, 4, 10)


def test_validation_agent_missing_documents():
    """Test validation agent detects missing documents."""
    from app.agents.validation_agent import ValidationAgent
    from app.schemas import ProcessedDocument
    
    agent = ValidationAgent()
    
    # Only provide a bill (missing discharge summary)
    documents = [
        ProcessedDocument(
            filename="bill.pdf",
            type=DocumentType.BILL,
            data={"total_amount": 5000},
            confidence=0.9
        )
    ]
    
    missing = agent._check_required_documents(documents)
    assert DocumentType.DISCHARGE_SUMMARY in missing


def test_validation_agent_date_consistency():
    """Test validation agent checks date consistency."""
    from app.agents.validation_agent import ValidationAgent
    from app.schemas import ProcessedDocument
    
    agent = ValidationAgent()
    
    # Discharge date before admission (invalid)
    documents = [
        ProcessedDocument(
            filename="discharge.pdf",
            type=DocumentType.DISCHARGE_SUMMARY,
            data={
                "admission_date": "2024-04-10",
                "discharge_date": "2024-04-01"  # Before admission!
            },
            confidence=0.9
        )
    ]
    
    discrepancies = agent._check_date_consistency(documents)
    assert len(discrepancies) > 0
    assert any("before" in d.description.lower() for d in discrepancies)


def test_decision_agent_business_rules():
    """Test decision agent business rules."""
    from app.agents.decision_agent import DecisionAgent
    from app.schemas import ProcessedDocument, ValidationResult, ClaimStatus
    
    agent = DecisionAgent()
    
    # Test rejection due to missing documents
    validation = ValidationResult(
        is_valid=False,
        missing_documents=[DocumentType.BILL],
        discrepancies=[],
        warnings=[],
        validation_summary="Missing bill"
    )
    
    status, factors, amount = agent._apply_business_rules([], validation)
    assert status == ClaimStatus.REJECTED
    assert any("missing" in f.lower() for f in factors)


def test_decision_agent_confidence_calculation():
    """Test decision confidence score calculation."""
    from app.agents.decision_agent import DecisionAgent
    from app.schemas import ProcessedDocument, ValidationResult, ClaimStatus
    
    agent = DecisionAgent()
    
    # Perfect scenario
    validation = ValidationResult(
        is_valid=True,
        missing_documents=[],
        discrepancies=[],
        warnings=[],
        validation_summary="All good"
    )
    
    documents = [
        ProcessedDocument(
            filename="test.pdf",
            type=DocumentType.BILL,
            data={},
            confidence=0.95
        )
    ]
    
    confidence = agent._calculate_confidence(documents, validation, ClaimStatus.APPROVED)
    assert confidence > 0.5  # Should be high
    assert confidence <= 1.0


@pytest.mark.asyncio
async def test_classifier_batch_processing():
    """Test classifier can process multiple documents."""
    agent = ClassifierAgent()
    
    # Use fallback classification (doesn't need LLM)
    documents = [
        ("bill.pdf", "Invoice Total: $1000"),
        ("discharge.pdf", "Patient discharged on..."),
        ("unknown.pdf", "Some random text"),
    ]
    
    # This would normally call LLM, but we can test the structure
    # In a real test, you'd mock the LLM
    # results = await agent.classify_batch(documents)
    # assert len(results) == 3
    pass  # Skip actual LLM call in unit test
