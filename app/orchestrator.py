"""
Claim processing orchestrator using LangGraph.

AI Tool Used: Claude + Cursor for LangGraph implementation
Prompt: "Design a LangGraph StateGraph for orchestrating a multi-agent document
processing pipeline with states for classification, extraction, processing, validation, and decision"
"""
from typing import List, Dict, Any, TypedDict, Annotated
import asyncio
from decimal import Decimal
from langgraph.graph import StateGraph, END
from fastapi import UploadFile

from app.schemas import (
    DocumentType,
    ProcessedDocument,
    ValidationResult,
    ClaimDecision,
)
from app.services.pdf_service import get_pdf_service
from app.agents.classifier_agent import get_classifier_agent
from app.agents.processing_agents import (
    get_bill_agent,
    get_discharge_agent,
    get_idcard_agent,
)
from app.agents.validation_agent import get_validation_agent
from app.agents.decision_agent import get_decision_agent
from app.utils.logging import get_logger

logger = get_logger(__name__)


class WorkflowState(TypedDict):
    """
    State shared across all nodes in the workflow.
    
    This state is passed through the entire processing pipeline.
    """
    # Input
    files: List[tuple[str, bytes]]  # (filename, content)
    request_id: str
    
    # Intermediate results
    extracted_texts: Dict[str, str]  # filename -> text
    classified_docs: List[Dict[str, Any]]  # classification results
    processed_docs: List[ProcessedDocument]  # processed with extracted data
    
    # Final results
    validation: ValidationResult | None
    decision: ClaimDecision | None
    
    # Metadata
    errors: List[str]
    processing_metadata: Dict[str, Any]


class ClaimOrchestrator:
    """
    Orchestrates the entire claim processing workflow using LangGraph.
    
    Workflow stages:
    1. extract_text: Extract text from all PDFs
    2. classify: Classify each document type
    3. process: Extract structured data based on document type
    4. validate: Cross-check data consistency
    5. decide: Make final approval/rejection decision
    """
    
    def __init__(self):
        """Initialize orchestrator and all agents."""
        self.pdf_service = get_pdf_service()
        self.classifier_agent = get_classifier_agent()
        self.bill_agent = get_bill_agent()
        self.discharge_agent = get_discharge_agent()
        self.idcard_agent = get_idcard_agent()
        self.validation_agent = get_validation_agent()
        self.decision_agent = get_decision_agent()
        
        # Build the workflow graph
        self.workflow = self._build_workflow()
        
        logger.info("claim_orchestrator_initialized")
    
    def _build_workflow(self) -> StateGraph:
        """Build the LangGraph workflow."""
        workflow = StateGraph(WorkflowState)
        
        # Add nodes (processing stages)
        workflow.add_node("extract_text", self._extract_text_node)
        workflow.add_node("classify", self._classify_node)
        workflow.add_node("process", self._process_node)
        workflow.add_node("validate", self._validate_node)
        workflow.add_node("decide", self._decide_node)
        
        # Define edges (workflow transitions)
        workflow.set_entry_point("extract_text")
        workflow.add_edge("extract_text", "classify")
        workflow.add_edge("classify", "process")
        workflow.add_edge("process", "validate")
        workflow.add_edge("validate", "decide")
        workflow.add_edge("decide", END)
        
        return workflow.compile()
    
    async def _extract_text_node(self, state: WorkflowState) -> WorkflowState:
        """
        Node 1: Extract text from all PDF files.
        """
        logger.info("workflow_extract_text_started", file_count=len(state["files"]))
        
        extracted_texts = {}
        
        # Extract text from all files in parallel
        async def extract_one(filename: str, content: bytes):
            try:
                text = await self.pdf_service.extract_text(content, filename)
                return filename, text
            except Exception as e:
                logger.error("text_extraction_failed", filename=filename, error=str(e))
                state["errors"].append(f"Failed to extract text from {filename}: {str(e)}")
                return filename, ""
        
        tasks = [extract_one(fname, content) for fname, content in state["files"]]
        results = await asyncio.gather(*tasks)
        
        for filename, text in results:
            extracted_texts[filename] = text
        
        state["extracted_texts"] = extracted_texts
        
        logger.info("workflow_extract_text_completed", extracted_count=len(extracted_texts))
        
        return state
    
    async def _classify_node(self, state: WorkflowState) -> WorkflowState:
        """
        Node 2: Classify each document type.
        """
        logger.info("workflow_classify_started")
        
        # Prepare documents for classification
        documents = [
            (filename, text)
            for filename, text in state["extracted_texts"].items()
        ]
        
        # Classify all documents
        classified = await self.classifier_agent.classify_batch(documents)
        
        # Convert to dict format (store enum as string for serialization)
        classified_dicts = [
            {
                "filename": c.filename,
                "document_type": c.document_type,  # Already a string due to use_enum_values=True
                "confidence": c.confidence,
                "reasoning": c.reasoning,
            }
            for c in classified
        ]
        
        state["classified_docs"] = classified_dicts
        
        logger.info(
            "workflow_classify_completed",
            classified_count=len(classified_dicts),
            types=[c["document_type"] for c in classified_dicts]
        )
        
        return state
    
    async def _process_node(self, state: WorkflowState) -> WorkflowState:
        """
        Node 3: Process each document with specialized agent.
        """
        logger.info("workflow_process_started")
        
        processed_docs = []
        
        # Process each classified document
        async def process_one(doc_info: Dict[str, Any]):
            filename = doc_info["filename"]
            doc_type_str = doc_info["document_type"]  # This is a string after serialization
            doc_type = DocumentType(doc_type_str)  # Convert string back to enum
            text = state["extracted_texts"].get(filename, "")
            
            results = []  # May return multiple ProcessedDocuments if multi-section detected
            
            try:
                # For bill documents, check if discharge summary is also present FIRST
                should_also_extract_discharge = False
                if doc_type == DocumentType.BILL:
                    discharge_keywords = [
                        "discharge summary", "diagnosis:", "admission date", 
                        "discharge date", "surgery", "procedure done", 
                        "treatment", "surgeon", "anesthesiologist"
                    ]
                    text_lower = text.lower()
                    keyword_count = sum(1 for kw in discharge_keywords if kw in text_lower)
                    
                    if keyword_count >= 3:  # If 3+ discharge keywords found
                        should_also_extract_discharge = True
                        logger.info(
                            "multi_section_document_detected",
                            filename=filename,
                            primary_type="bill",
                            also_contains="discharge_summary",
                            keywords_found=keyword_count
                        )
                
                # Route to appropriate agent
                data = {}
                
                if doc_type == DocumentType.BILL:
                    try:
                        extracted = await self.bill_agent.extract(text, filename)
                        data = extracted.model_dump()
                    except Exception as bill_error:
                        logger.error("bill_extraction_failed", filename=filename, error=str(bill_error))
                        data = {}  # Empty data on failure
                    
                    # Create bill ProcessedDocument (even if extraction partially failed)
                    results.append(ProcessedDocument(
                        filename=filename,
                        type=DocumentType.BILL,
                        data=data,
                        raw_text=text[:1000],
                        confidence=doc_info["confidence"],
                        processing_errors=[],
                    ))
                    
                    # If multi-section detected, also extract discharge summary
                    if should_also_extract_discharge:
                        try:
                            discharge_extracted = await self.discharge_agent.extract(text, filename)
                            discharge_data = discharge_extracted.model_dump()
                            
                            results.append(ProcessedDocument(
                                filename=filename,
                                type=DocumentType.DISCHARGE_SUMMARY,
                                data=discharge_data,
                                raw_text=text[:1000],
                                confidence=0.85,  # Slightly lower confidence for secondary detection
                                processing_errors=[],
                            ))
                            
                            logger.info(
                                "additional_section_extracted",
                                filename=filename,
                                section_type="discharge_summary"
                            )
                        except Exception as e:
                            logger.info(
                                "additional_section_extracted",
                                filename=filename,
                                section_type="discharge_summary"
                            )
                        except Exception as e:
                            logger.warning(
                                "secondary_extraction_failed",
                                filename=filename,
                                section="discharge_summary",
                                error=str(e)
                            )
                
                elif doc_type == DocumentType.DISCHARGE_SUMMARY:
                    extracted = await self.discharge_agent.extract(text, filename)
                    data = extracted.model_dump()
                    
                    results.append(ProcessedDocument(
                        filename=filename,
                        type=doc_type,
                        data=data,
                        raw_text=text[:1000],
                        confidence=doc_info["confidence"],
                        processing_errors=[],
                    ))
                
                elif doc_type == DocumentType.ID_CARD:
                    extracted = await self.idcard_agent.extract(text, filename)
                    data = extracted.model_dump()
                    
                    results.append(ProcessedDocument(
                        filename=filename,
                        type=doc_type,
                        data=data,
                        raw_text=text[:1000],
                        confidence=doc_info["confidence"],
                        processing_errors=[],
                    ))
                
                else:
                    logger.warning("unknown_document_type_skipped", filename=filename)
                
                return results
                
            except Exception as e:
                logger.error("document_processing_failed", filename=filename, error=str(e))
                state["errors"].append(f"Failed to process {filename}: {str(e)}")
                
                return [ProcessedDocument(
                    filename=filename,
                    type=doc_type,
                    data={},
                    raw_text=text[:1000],
                    confidence=doc_info["confidence"],
                    processing_errors=[str(e)],
                )]
        
        # Process all documents in parallel
        tasks = [process_one(doc) for doc in state["classified_docs"]]
        results = await asyncio.gather(*tasks)
        
        # Flatten results (since each can return multiple ProcessedDocuments)
        for result_list in results:
            processed_docs.extend(result_list)
        
        state["processed_docs"] = processed_docs
        
        logger.info("workflow_process_completed", processed_count=len(processed_docs))
        
        return state
    
    async def _validate_node(self, state: WorkflowState) -> WorkflowState:
        """
        Node 4: Validate data consistency across documents.
        """
        logger.info("workflow_validate_started")
        
        try:
            validation = await self.validation_agent.validate(state["processed_docs"])
            state["validation"] = validation
            
            logger.info(
                "workflow_validate_completed",
                is_valid=validation.is_valid,
                discrepancies=len(validation.discrepancies)
            )
            
        except Exception as e:
            logger.error("validation_failed", error=str(e))
            state["errors"].append(f"Validation failed: {str(e)}")
            
            # Create fallback validation result
            from app.schemas import Discrepancy
            state["validation"] = ValidationResult(
                is_valid=False,
                missing_documents=[],
                discrepancies=[Discrepancy(
                    field="validation",
                    description=f"Validation error: {str(e)}",
                    severity="critical",
                    documents_involved=[]
                )],
                warnings=[],
                validation_summary="Validation process failed."
            )
        
        return state
    
    async def _decide_node(self, state: WorkflowState) -> WorkflowState:
        """
        Node 5: Make final claim decision.
        """
        logger.info("workflow_decide_started")
        
        try:
            decision = await self.decision_agent.decide(
                state["processed_docs"],
                state["validation"]
            )
            state["decision"] = decision
            
            logger.info(
                "workflow_decide_completed",
                status=decision.status,
                confidence=decision.confidence
            )
            
        except Exception as e:
            logger.error("decision_failed", error=str(e))
            state["errors"].append(f"Decision failed: {str(e)}")
            
            # Create fallback decision
            from app.schemas import ClaimStatus
            state["decision"] = ClaimDecision(
                status=ClaimStatus.REJECTED,
                reason=f"Decision process failed: {str(e)}",
                approved_amount=None,
                confidence=0.0,
                decision_factors=["Error in decision process"]
            )
        
        return state
    
    async def process_claim(
        self,
        files: List[tuple[str, bytes]],
        request_id: str,
    ) -> WorkflowState:
        """
        Process a claim through the entire workflow.
        
        Args:
            files: List of (filename, content) tuples
            request_id: Unique request identifier
        
        Returns:
            Final workflow state with all results
        """
        logger.info(
            "claim_processing_started",
            request_id=request_id,
            file_count=len(files)
        )
        
        # Initialize state
        initial_state: WorkflowState = {
            "files": files,
            "request_id": request_id,
            "extracted_texts": {},
            "classified_docs": [],
            "processed_docs": [],
            "validation": None,
            "decision": None,
            "errors": [],
            "processing_metadata": {},
        }
        
        try:
            # Run the workflow
            final_state = await self.workflow.ainvoke(initial_state)
            
            logger.info(
                "claim_processing_completed",
                request_id=request_id,
                errors_count=len(final_state["errors"])
            )
            
            return final_state
            
        except Exception as e:
            logger.error(
                "claim_processing_failed",
                request_id=request_id,
                error=str(e),
                error_type=type(e).__name__
            )
            
            # Return state with error
            initial_state["errors"].append(f"Workflow failed: {str(e)}")
            return initial_state


# Global orchestrator instance
_orchestrator: ClaimOrchestrator | None = None


def get_orchestrator() -> ClaimOrchestrator:
    """Get or create global orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ClaimOrchestrator()
    return _orchestrator
