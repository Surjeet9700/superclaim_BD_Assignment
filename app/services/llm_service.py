"""LLM service abstraction layer with retry logic."""
import asyncio
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import google.generativeai as genai
from openai import AsyncOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.schema import HumanMessage, SystemMessage
from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text from the LLM."""
        pass
    
    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate structured JSON output from the LLM."""
        pass


class GeminiProvider(LLMProvider):
    """Google Gemini LLM provider with retry logic."""
    
    def __init__(self):
        """Initialize Gemini client."""
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY not set in environment")
        
        genai.configure(api_key=settings.google_api_key)
        self.model_name = settings.gemini_model
        self.temperature = settings.llm_temperature
        
        logger.info(
            "gemini_provider_initialized",
            model=self.model_name,
            temperature=self.temperature
        )
    
    @retry(
        stop=stop_after_attempt(settings.llm_max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using Gemini with retry logic."""
        try:
            temp = temperature if temperature is not None else self.temperature
            
            # Combine system prompt and user prompt
            full_prompt = prompt
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            
            model = genai.GenerativeModel(
                self.model_name,
                generation_config={
                    "temperature": temp,
                    "max_output_tokens": max_tokens or 8192,  # Increased default for complex validations
                },
                safety_settings={
                    genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
                    genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
                    genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
                    genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
                }
            )
            
            logger.debug(
                "gemini_generate_request",
                model=self.model_name,
                temperature=temp,
                prompt_length=len(full_prompt)
            )
            
            # Run in thread pool since genai is sync
            response = await asyncio.to_thread(
                model.generate_content,
                full_prompt
            )
            
            # Check if response was blocked by safety filters
            if not response.candidates:
                logger.error("gemini_no_candidates", message="Response blocked by safety filters")
                raise ValueError("Response blocked by safety filters")
            
            candidate = response.candidates[0]
            # FinishReason enum: 1=STOP, 2=MAX_TOKENS, 3=SAFETY, 4=RECITATION
            if candidate.finish_reason == 2:  # MAX_TOKENS
                logger.warning("gemini_max_tokens", finish_reason=candidate.finish_reason, message="Response truncated - increase max_output_tokens")
                # Don't raise - try to use partial response
            elif candidate.finish_reason == 3:  # SAFETY
                logger.error("gemini_safety_block", finish_reason=candidate.finish_reason)
                raise ValueError("Response blocked by safety filters")
            elif candidate.finish_reason == 4:  # RECITATION  
                logger.error("gemini_recitation_block", finish_reason=candidate.finish_reason)
                raise ValueError("Response blocked due to recitation")
            elif candidate.finish_reason != 1:  # Not STOP (normal completion)
                logger.warning("gemini_unusual_finish", finish_reason=candidate.finish_reason)
                
            result = response.text
            
            logger.debug(
                "gemini_generate_response",
                response_length=len(result)
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "gemini_generate_error",
                error=str(e),
                error_type=type(e).__name__
            )
            raise
    
    async def generate_structured(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate structured JSON output."""
        import json
        
        # Add JSON formatting instruction to prompt
        json_instruction = "\n\nIMPORTANT: Respond ONLY with valid JSON. No markdown, no explanations, just the JSON object."
        
        if schema:
            json_instruction += f"\n\nUse this schema:\n{json.dumps(schema, indent=2)}"
        
        full_prompt = prompt + json_instruction
        
        response = await self.generate(
            full_prompt,
            system_prompt,
            max_tokens=max_tokens
        )
        
        # Clean up response - remove markdown code blocks if present
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(
                "json_parse_error",
                error=str(e),
                response=cleaned[:500]
            )
            # Try to extract JSON from text with better regex
            import re
            
            # Fix truncated strings - complete the last incomplete string value
            if "Unterminated string" in str(e):
                # Find the last complete field before truncation
                # Remove everything after the last complete value
                last_complete = cleaned.rfind('",')
                if last_complete > 0:
                    # Truncate to last complete field and close JSON
                    truncated = cleaned[:last_complete + 2] + '\n}'
                    try:
                        logger.info("attempting_json_repair_truncation")
                        return json.loads(truncated)
                    except:
                        pass
            
            # Try to find complete JSON object (handles nested objects and multiline strings)
            json_match = re.search(r'\{[^}]*(?:\{[^}]*\}[^}]*)*\}', cleaned, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            
            # Try to fix common JSON issues (unescaped newlines in strings)
            try:
                # Replace actual newlines within string values with \n
                fixed = re.sub(r':\s*"([^"]*)\n([^"]*)"', r': "\1\\n\2"', cleaned)
                return json.loads(fixed)
            except:
                pass
                
            raise ValueError(f"Failed to parse JSON response: {e}")


class OpenAIProvider(LLMProvider):
    """OpenAI GPT LLM provider with retry logic."""
    
    def __init__(self):
        """Initialize OpenAI client."""
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not set in environment")
        
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model_name = settings.openai_model
        self.temperature = settings.llm_temperature
        
        logger.info(
            "openai_provider_initialized",
            model=self.model_name,
            temperature=self.temperature
        )
    
    @retry(
        stop=stop_after_attempt(settings.llm_max_retries),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,)),
        reraise=True,
    )
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text using OpenAI GPT."""
        try:
            messages = []
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            messages.append({"role": "user", "content": prompt})
            
            temp = temperature if temperature is not None else self.temperature
            
            logger.debug(
                "openai_generate_request",
                model=self.model_name,
                temperature=temp,
                messages_count=len(messages)
            )
            
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temp,
                max_tokens=max_tokens or 2048,
            )
            
            result = response.choices[0].message.content
            
            logger.debug(
                "openai_generate_response",
                response_length=len(result) if result else 0
            )
            
            return result or ""
            
        except Exception as e:
            logger.error(
                "openai_generate_error",
                error=str(e),
                error_type=type(e).__name__
            )
            raise
    
    async def generate_structured(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate structured JSON output using response_format."""
        import json
        
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        json_instruction = "\n\nIMPORTANT: Respond ONLY with valid JSON."
        if schema:
            json_instruction += f"\n\nUse this schema:\n{json.dumps(schema, indent=2)}"
        
        messages.append({"role": "user", "content": prompt + json_instruction})
        
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=self.temperature,
                response_format={"type": "json_object"},
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from OpenAI")
            
            return json.loads(content)
            
        except Exception as e:
            logger.error("openai_structured_error", error=str(e))
            raise


class LLMService:
    """
    Unified LLM service that abstracts provider details.
    
    AI Tool Used: Claude helped design this abstraction layer
    Prompt: "Design a unified LLM service that supports both Google Gemini and OpenAI GPT,
    with retry logic, structured output, and provider fallback"
    """
    
    def __init__(self, provider_name: Optional[str] = None):
        """Initialize LLM service with specified provider."""
        provider_name = provider_name or settings.default_llm_provider
        
        self.provider: LLMProvider
        
        if provider_name == "google":
            self.provider = GeminiProvider()
        elif provider_name == "openai":
            self.provider = OpenAIProvider()
        else:
            raise ValueError(f"Unsupported LLM provider: {provider_name}")
        
        self.provider_name = provider_name
        
        logger.info(
            "llm_service_initialized",
            provider=provider_name
        )
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate text response."""
        return await self.provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    
    async def generate_structured(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Generate structured JSON response."""
        return await self.provider.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            schema=schema,
            max_tokens=max_tokens,
        )


# Global LLM service instance
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Get or create global LLM service instance."""
    global _llm_service
    
    if _llm_service is None:
        _llm_service = LLMService()
    
    return _llm_service
