"""Decision agent for final claim approval/rejection."""
from typing import List
from decimal import Decimal
from app.schemas import (
    ClaimStatus,
    ClaimDecision,
    ValidationResult,
    ProcessedDocument,
    DocumentType,
)
from app.services.llm_service import get_llm_service
from app.utils.logging import get_logger

logger = get_logger(__name__)


class DecisionAgent:
    """
    Agent for making final claim approval/rejection decisions.
    
    AI Tool Used: ChatGPT for decision logic
    Prompt: "Design a decision-making system for insurance claims that combines
    rule-based logic with LLM reasoning to approve/reject claims with explanations"
    """
    
    SYSTEM_PROMPT = """You are an insurance claim adjudication specialist.
Make final decisions on insurance claims based on document validation results.

Decision Criteria:
1. All required documents must be present
2. No critical data discrepancies
3. Patient information must be consistent
4. Dates must be logical and aligned
5. Bill amounts must be reasonable

When approving, state the approved amount.
When rejecting, clearly explain the reasons.
When uncertain, recommend manual review."""
    
    def __init__(self):
        """Initialize decision agent."""
        self.llm = get_llm_service()
        logger.info("decision_agent_initialized")
    
    def _apply_business_rules(
        self,
        documents: List[ProcessedDocument],
        validation: ValidationResult,
    ) -> tuple[ClaimStatus, List[str], Decimal | None]:
        """
        Apply rule-based decision logic.
        
        Returns:
            (status, decision_factors, approved_amount)
        """
        factors = []
        
        # Rule 1: Missing required documents -> REJECT
        if validation.missing_documents:
            missing = [doc.value for doc in validation.missing_documents]
            factors.append(f"Missing required documents: {', '.join(missing)}")
            return ClaimStatus.REJECTED, factors, None
        
        # Rule 2: Critical discrepancies -> REJECT
        critical = [d for d in validation.discrepancies if d.severity == "critical"]
        if critical:
            for disc in critical:
                factors.append(f"Critical issue: {disc.description}")
            return ClaimStatus.REJECTED, factors, None
        
        # Rule 3: Check if we have a bill with amount
        bill_amount = None
        for doc in documents:
            if doc.type == DocumentType.BILL:
                amount = doc.data.get("total_amount")
                if amount:
                    if isinstance(amount, str):
                        try:
                            bill_amount = Decimal(amount)
                        except:
                            pass
                    else:
                        bill_amount = amount
                    break
        
        if bill_amount is None or bill_amount <= 0:
            factors.append("No valid bill amount found")
            return ClaimStatus.REJECTED, factors, None
        
        # Rule 4: Warnings present -> PENDING_REVIEW (for manual review)
        warning_discs = [d for d in validation.discrepancies if d.severity == "warning"]
        if len(warning_discs) >= 3:  # Too many warnings
            for disc in warning_discs[:3]:
                factors.append(f"Warning: {disc.description}")
            factors.append(f"Multiple warnings require manual review")
            return ClaimStatus.PENDING_REVIEW, factors, bill_amount
        
        # Rule 5: All checks passed -> APPROVE
        factors.append("All required documents present")
        factors.append("No critical discrepancies found")
        factors.append(f"Bill amount: {bill_amount}")
        
        if validation.warnings:
            factors.append(f"Minor warnings noted but acceptable")
        
        return ClaimStatus.APPROVED, factors, bill_amount
    
    async def _get_llm_reasoning(
        self,
        documents: List[ProcessedDocument],
        validation: ValidationResult,
        rule_based_status: ClaimStatus,
        factors: List[str],
    ) -> str:
        """Get LLM-powered reasoning for the decision."""
        try:
            # Prepare document summary
            doc_summary = []
            for doc in documents:
                doc_summary.append(f"- {doc.type}: {list(doc.data.keys())}")
            
            # Create action-specific prompt based on status
            if rule_based_status == ClaimStatus.APPROVED:
                action_instruction = "APPROVED. Explain why this claim meets all requirements and is approved for payment."
            elif rule_based_status == ClaimStatus.REJECTED:
                action_instruction = "REJECTED. Explain why this claim does not meet requirements and must be rejected."
            else:
                action_instruction = "PENDING MANUAL REVIEW. Explain why this claim requires additional human review."
            
            prompt = f"""This insurance claim has been {action_instruction}

Documents Submitted:
{chr(10).join(doc_summary)}

Validation Results:
- Valid: {validation.is_valid}
- Missing: {[d.value for d in validation.missing_documents]}
- Issues: {len(validation.discrepancies)}

Decision Factors:
{chr(10).join(f"- {f}" for f in factors)}

Write a clear, professional 2-3 sentence explanation that:
1. States the decision upfront (Approved/Rejected/Pending)
2. Explains the key reasons supporting this decision
3. Uses the decision factors provided above

Response format: "This claim is [status]. [Reasoning based on factors]"
"""
            
            reasoning = await self.llm.generate(
                prompt=prompt,
                system_prompt=self.SYSTEM_PROMPT,
                temperature=0.2,
                max_tokens=500,  # Increased for proper explanation
            )
            
            # Ensure reasoning starts with decision status
            reasoning = reasoning.strip()
            if not any(reasoning.lower().startswith(word) for word in ["approved", "rejected", "pending", "this claim"]):
                # Prepend status if not present
                reasoning = f"This claim is {rule_based_status.value}. {reasoning}"
            
            return reasoning
            
        except Exception as e:
            logger.error("llm_reasoning_error", error=str(e))
            # Fallback to rule-based reasoning
            return f"This claim is {rule_based_status.value}. " + " ".join(factors)
    
    async def decide(
        self,
        documents: List[ProcessedDocument],
        validation: ValidationResult,
    ) -> ClaimDecision:
        """
        Make final claim decision.
        
        Args:
            documents: List of processed documents
            validation: Validation results
        
        Returns:
            ClaimDecision with status and reasoning
        """
        try:
            logger.info("decision_started", document_count=len(documents))
            
            # Apply business rules
            status, factors, approved_amount = self._apply_business_rules(
                documents, validation
            )
            
            # Get LLM reasoning
            reasoning = await self._get_llm_reasoning(
                documents, validation, status, factors
            )
            
            # Calculate confidence score
            confidence = self._calculate_confidence(
                documents, validation, status
            )
            
            decision = ClaimDecision(
                status=status,
                reason=reasoning,
                approved_amount=approved_amount if status == ClaimStatus.APPROVED else None,
                confidence=confidence,
                decision_factors=factors,
            )
            
            logger.info(
                "decision_completed",
                status=status.value,
                confidence=confidence,
                approved_amount=str(approved_amount) if approved_amount else None
            )
            
            return decision
            
        except Exception as e:
            logger.error(
                "decision_error",
                error=str(e),
                error_type=type(e).__name__
            )
            
            # Return rejection on error
            return ClaimDecision(
                status=ClaimStatus.REJECTED,
                reason=f"Claim decision failed due to processing error: {str(e)}",
                approved_amount=None,
                confidence=0.0,
                decision_factors=["Processing error occurred"],
            )
    
    def _calculate_confidence(
        self,
        documents: List[ProcessedDocument],
        validation: ValidationResult,
        status: ClaimStatus,
    ) -> float:
        """Calculate confidence score for the decision."""
        confidence = 0.5  # Base confidence
        
        # Boost for complete documents
        if not validation.missing_documents:
            confidence += 0.15
        
        # Boost for no discrepancies
        if not validation.discrepancies:
            confidence += 0.2
        
        # Boost for valid data
        if validation.is_valid:
            confidence += 0.15
        
        # Penalty for warnings
        warning_count = len([d for d in validation.discrepancies if d.severity == "warning"])
        confidence -= (warning_count * 0.05)
        
        # Penalty for low extraction confidence
        avg_doc_confidence = sum(doc.confidence for doc in documents) / len(documents) if documents else 0
        confidence += (avg_doc_confidence - 0.5) * 0.2
        
        # Clamp to [0, 1]
        return max(0.0, min(1.0, confidence))


# Global agent instance
_decision_agent = None


def get_decision_agent() -> DecisionAgent:
    """Get or create global decision agent instance."""
    global _decision_agent
    if _decision_agent is None:
        _decision_agent = DecisionAgent()
    return _decision_agent
