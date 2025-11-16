"""Utilities for LLM provider instantiation and management."""

from typing import Any, Optional

from ..config import settings
from ..logging import get_logger

logger = get_logger(__name__)


def get_llm_instance(
    temperature: float = 0.1,
    max_tokens: int = 2048,
    provider: Optional[str] = None,
    fallback: bool = True
) -> Optional[Any]:
    """
    Get an LLM instance (Groq, OpenAI, or Ollama) based on configuration.
    
    Args:
        temperature: Temperature for LLM sampling (0.0-1.0)
        max_tokens: Maximum tokens in response
        provider: Specific provider ("groq", "openai", "ollama", or None for auto)
        fallback: Whether to fallback to alternate provider if primary fails
    
    Returns:
        LLM instance (ChatGroq, ChatOpenAI, or ChatOllama) or None if no provider available
        
    Example:
        llm = get_llm_instance(temperature=0.3, max_tokens=300)
        response = llm.invoke("Your prompt here")
    """
    try:
        # Auto-detect provider from config if not specified
        if provider is None:
            provider = settings.llm.provider.lower()
        else:
            provider = provider.lower()
        
        # Try Groq first if configured
        if provider == "groq":
            if not settings.llm.groq_api_key.get_secret_value():
                logger.error("Groq API key not configured, checking fallback", fallback=fallback)
                if fallback:
                    logger.info("Attempting fallback to OpenAI")
                    return _get_openai_instance(temperature, max_tokens)
                return None
            
            try:
                from langchain_groq import ChatGroq
                
                llm = ChatGroq(
                    api_key=settings.llm.groq_api_key.get_secret_value(),
                    model_name=settings.llm.groq_model,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                logger.debug("LLM instance created", provider="groq", model=settings.llm.groq_model)
                return llm
                
            except ImportError:
                logger.error("langchain-groq not installed, checking fallback", fallback=fallback)
                if fallback:
                    logger.info("Attempting fallback to OpenAI")
                    return _get_openai_instance(temperature, max_tokens)
                logger.error("langchain-groq not installed and fallback disabled")
                return None
        
        # Try OpenAI if configured
        elif provider == "openai":
            return _get_openai_instance(temperature, max_tokens)
        
        # Try Ollama if configured
        elif provider == "ollama":
            return _get_ollama_instance(temperature, max_tokens)
        
        else:
            logger.error("Unknown LLM provider", provider=provider)
            return None
            
    except Exception as e:
        logger.error("Failed to instantiate LLM", error=str(e), exc_info=True)
        return None


def _get_openai_instance(
    temperature: float,
    max_tokens: int
) -> Optional[Any]:
    """Helper to instantiate OpenAI LLM."""
    try:
        if not settings.llm.openai_api_key.get_secret_value():
            logger.error("OpenAI API key not configured")
            return None
        
        from langchain_openai import ChatOpenAI
        
        llm = ChatOpenAI(
            api_key=settings.llm.openai_api_key.get_secret_value(),
            model_name=settings.llm.openai_model,
            temperature=temperature,
            max_tokens=max_tokens
        )
        logger.debug("LLM instance created", provider="openai", model=settings.llm.openai_model)
        return llm
        
    except ImportError:
        logger.error("langchain-openai not installed")
        return None
    except Exception as e:
        logger.error("Failed to instantiate OpenAI LLM", error=str(e))
        return None


def _get_ollama_instance(
    temperature: float,
    max_tokens: int
) -> Optional[Any]:
    """Helper to instantiate Ollama LLM."""
    try:
        from langchain_ollama import ChatOllama
        
        # Get Ollama configuration from settings
        ollama_base_url = getattr(settings.llm, 'ollama_base_url', 'http://localhost:11434')
        ollama_model = getattr(settings.llm, 'ollama_model', 'llama3.1')
        
        llm = ChatOllama(
            base_url=ollama_base_url,
            model=ollama_model,
            temperature=temperature,
            num_predict=max_tokens  # Ollama uses num_predict instead of max_tokens
        )
        logger.debug("LLM instance created", provider="ollama", model=ollama_model, base_url=ollama_base_url)
        return llm
        
    except ImportError:
        logger.error("langchain-ollama not installed")
        return None
    except Exception as e:
        logger.error("Failed to instantiate Ollama LLM", error=str(e))
        return None


def validate_llm_available() -> bool:
    """Check if any LLM provider is properly configured."""
    provider = settings.llm.provider.lower()
    
    if provider == "groq":
        return bool(settings.llm.groq_api_key.get_secret_value())
    elif provider == "openai":
        return bool(settings.llm.openai_api_key.get_secret_value())
    elif provider == "ollama":
        # Ollama doesn't require API key, just check if langchain_ollama is available
        try:
            import langchain_ollama
            return True
        except ImportError:
            logger.error("langchain-ollama not installed")
            return False
    
    return False
