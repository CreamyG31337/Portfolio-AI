#!/usr/bin/env python3
"""
Ollama API Client
=================

HTTP client for interacting with Ollama API running in Docker.
Supports streaming responses for real-time chat.
"""

import os
import json
import logging
import time
import threading
from typing import Generator, Optional, List, Dict, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from env_loader import load_project_dotenv

from summary_common import get_summary_system_prompt, parse_summary_response
from prompt_safety import (
    contains_instruction_like_text,
    prepare_untrusted_for_prompt,
    sanitize_for_llm,
)

# Load .env from repo root and web_dashboard (cwd-independent)
load_project_dotenv()

logger = logging.getLogger(__name__)

# Default configuration from environment variables
# Priority: Docker env vars > .env file > Python defaults
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "glm-4.7")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "true").lower() == "true"
# Z.AI / GLM HTTP read timeout (seconds). Article summarization uses this; see docs/GLM_ZAI_SUMMARY_TIMING.md.
GLM_TIMEOUT = int(os.getenv("GLM_TIMEOUT", "180"))

# Keep summarization output bounded so prompt + article + output fits model context.
SUMMARY_MIN_PREDICT = 256
SUMMARY_DEFAULT_PREDICT = 1024
SUMMARY_CONTEXT_MARGIN = 256


def load_model_config() -> Dict[str, Any]:
    """Load model configuration from JSON file.
    
    Returns:
        Dict containing model settings
    """
    try:
        config_path = os.path.join(os.path.dirname(__file__), 'model_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                logger.info(f"Loaded configuration for {len(config.get('models', {}))} models")
                return config
        else:
            logger.warning(f"Model config file not found at {config_path}")
            return {}
    except Exception as e:
        logger.error(f"Error loading model config: {e}")
        return {}


def _fit_summary_num_predict(
    *,
    model: str,
    effective_ctx: int,
    prompt_tokens_est: int,
    article_tokens_est: int,
    requested_num_predict: int,
) -> int:
    """Cap summary output tokens to reduce context overflow failures."""
    # Reserve a small margin for tokenizer variance and response framing overhead.
    available = effective_ctx - prompt_tokens_est - article_tokens_est - SUMMARY_CONTEXT_MARGIN
    if available < SUMMARY_MIN_PREDICT:
        logger.warning(
            "Very tight context budget for model=%s: ctx=%d, system≈%d, article≈%d. "
            "Forcing num_predict=%d.",
            model,
            effective_ctx,
            prompt_tokens_est,
            article_tokens_est,
            SUMMARY_MIN_PREDICT,
        )
        return SUMMARY_MIN_PREDICT

    fitted = min(requested_num_predict, available)
    if fitted < requested_num_predict:
        logger.info(
            "Adjusted summary num_predict for model=%s: %d -> %d (ctx fit)",
            model,
            requested_num_predict,
            fitted,
        )
    return max(SUMMARY_MIN_PREDICT, fitted)


class OllamaClient:
    """Client for interacting with Ollama API."""
    
    def __init__(self, base_url: Optional[str] = None, timeout: Optional[int] = None):
        """Initialize Ollama client.
        
        Args:
            base_url: Ollama API base URL (defaults to environment variable)
            timeout: Request timeout in seconds (defaults to environment variable)
        """
        candidate_url = base_url or OLLAMA_BASE_URL
        
        # Auto-detect correct URL if default is host.docker.internal but we're running on host
        # Similar to SearXNG client - try localhost if host.docker.internal doesn't resolve
        if "host.docker.internal" in candidate_url:
            try:
                import socket
                socket.gethostbyname("host.docker.internal")
            except (socket.gaierror, OSError):
                # Can't resolve host.docker.internal - we're probably running on host, not in Docker
                logger.info("Could not resolve host.docker.internal, falling back to localhost for Ollama")
                candidate_url = candidate_url.replace("host.docker.internal", "localhost")
        
        self.base_url = candidate_url
        self.timeout = timeout or OLLAMA_TIMEOUT
        self.enabled = OLLAMA_ENABLED
        
        logger.info(f"Ollama client initialized: base_url={self.base_url}, timeout={self.timeout}s, enabled={self.enabled}")
        
        # Create session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Load model configuration
        self.model_config = load_model_config()

    def _load_model_config(self) -> Dict[str, Any]:
        """Deprecated: Use global load_model_config() instead."""
        return load_model_config()

    def get_model_settings(self, model_name: str) -> Dict[str, Any]:
        """Get settings for specific model.
        
        Checks database for admin overrides first, then falls back to JSON config.
        
        Args:
            model_name: Name of the model
            
        Returns:
            Dict with settings (num_ctx, temperature, num_predict, etc.)
        """
        models = self.model_config.get('models', {})
        default_config = self.model_config.get('default_config', {})
        
        # Start with JSON defaults (exact match or global defaults)
        if model_name in models:
            settings = models[model_name].copy()
        else:
            settings = default_config.copy()
        
        # Check database for admin overrides
        try:
            from settings import get_system_setting
            
            # Check for temperature override
            db_temp = get_system_setting(f"model_{model_name}_temperature", default=None)
            if db_temp is not None:
                settings['temperature'] = db_temp
            
            # Check for context window override
            db_ctx = get_system_setting(f"model_{model_name}_num_ctx", default=None)
            if db_ctx is not None:
                settings['num_ctx'] = db_ctx
            
            # Check for max tokens override
            db_predict = get_system_setting(f"model_{model_name}_num_predict", default=None)
            if db_predict is not None:
                settings['num_predict'] = db_predict
                
        except Exception as e:
            logger.debug(f"Could not load database overrides for {model_name}: {e}")
        
        return settings
        
    def get_model_description(self, model_name: str) -> str:
        """Get description for a model.
        
        Args:
            model_name: Name of the model
            
        Returns:
            Description string
        """
        settings = self.get_model_settings(model_name)
        return settings.get('desc', '')
    
    def check_health(self) -> bool:
        """Check if Ollama API is available.
        
        Returns:
            True if Ollama is reachable, False otherwise
        """
        if not self.enabled:
            return False
        
        try:
            response = self.session.get(
                f"{self.base_url}/api/tags",
                timeout=5
            )
            if response.status_code == 200:
                return True
            else:
                logger.warning(f"Ollama health check failed: HTTP {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"❌ Ollama health check failed: {e}")
            return False
    
    def list_available_models(self) -> List[str]:
        """List all available models in Ollama (unfiltered).
        
        Returns:
            List of all model names from Ollama
        """
        if not self.enabled:
            logger.debug("Model listing skipped: Ollama disabled")
            return []
        
        try:
            logger.debug(f"Fetching available models from {self.base_url}...")
            response = self.session.get(
                f"{self.base_url}/api/tags",
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            models = [model.get("name", "") for model in data.get("models", [])]
            models = [m for m in models if m]  # Filter out empty strings
            logger.info(f"Found {len(models)} Ollama models: {', '.join(models) if models else 'none'}")
            return models
        except Exception as e:
            logger.error(f"❌ Error listing Ollama models: {e}")
            return []
    
    def get_filtered_models(self, include_hidden: bool = False) -> List[str]:
        """Get list of available models, filtered by JSON config.
        
        Filters out models marked as "hidden": true in model_config.json.
        Models not in the JSON config are included by default (backward compatibility).
        
        Args:
            include_hidden: If True, include models marked as hidden
            
        Returns:
            List of model names (filtered)
        """
        all_models = self.list_available_models()
        config_models = self.model_config.get('models', {})
        
        filtered = []
        for model in all_models:
            # If model not in config, include it (backward compatibility)
            if model not in config_models:
                filtered.append(model)
                continue
            
            # Model is in config - check if it's hidden
            model_config = config_models.get(model, {})
            is_hidden = model_config.get('hidden', False)
            
            # Include if not hidden, or if include_hidden=True
            if not is_hidden or include_hidden:
                filtered.append(model)
        
        logger.debug(f"Filtered {len(all_models)} models to {len(filtered)} visible models")
        return filtered
    
    def query_ollama(
        self,
        prompt: str,
        context: str = "",
        model: str = "glm-4.7",
        stream: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        num_ctx: Optional[int] = None,
        system_prompt: Optional[str] = None,
        json_mode: bool = False,
        streaming_timeout: int = 90
    ) -> Generator[str, None, None]:
        """Query Ollama API with a prompt and optional context.
        
        Args:
            prompt: User prompt/question
            context: Additional context data (formatted portfolio data, etc.)
            model: Model name to use
            stream: Whether to stream the response
            temperature: Model temperature (0.0-1.0). If None, uses model default.
            max_tokens: Maximum tokens in response (num_predict)
            num_ctx: Context window size. If None, uses model default.
            system_prompt: Optional system prompt to set model behavior
            json_mode: Whether to enforce JSON output format
            streaming_timeout: Timeout in seconds for streaming responses (default: 90)
            
        Yields:
            Response chunks as strings (streaming) or full response (non-streaming)
        """
        # Route GLM models to Z.AI transport (independent of Ollama availability).
        if model and str(model).startswith("glm-"):
            yield from self._query_glm(
                prompt=prompt,
                context=context,
                model=model,
                stream=stream,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                json_mode=json_mode,
            )
            return

        # Route web-based AI models to WebAI transport (independent of Ollama availability).
        try:
            from webai_wrapper import is_webai_model

            if model and is_webai_model(model):
                yield from self._query_webai(
                    prompt=prompt,
                    context=context,
                    model=model,
                    system_prompt=system_prompt,
                )
                return
        except ImportError:
            pass

        if not self.enabled:
            logger.warning("Ollama query rejected: AI assistant disabled")
            yield "AI assistant is currently disabled."
            return
        
        # Combine context and prompt
        full_prompt = prompt
        if context:
            full_prompt = f"{context}\n\nUser question: {prompt}"
        
        # Get model-specific defaults if values not provided
        model_settings = self.get_model_settings(model)
        
        # Use provided values, or model specific defaults, or global defaults
        effective_temp = temperature if temperature is not None else model_settings.get('temperature', 0.7)
        effective_ctx = num_ctx if num_ctx is not None else model_settings.get('num_ctx', 4096)
        effective_max_tokens = max_tokens if max_tokens is not None else model_settings.get('num_predict', 2048)
        
        # Prepare request payload
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": stream,
            "options": {
                "temperature": effective_temp,
                "num_predict": effective_max_tokens,
                "num_ctx": effective_ctx
            }
        }
        
        # Add system prompt if provided
        if system_prompt:
            payload["system"] = system_prompt
            
        # Add format if json_mode is enabled
        if json_mode:
            payload["format"] = "json"
        
        # Track request timing
        request_start_time = time.time()
        
        try:
            logger.info(f"[Ollama] query starting: model={model}, temp={effective_temp}, ctx={effective_ctx}, max_tokens={effective_max_tokens}, stream={stream}, timeout={streaming_timeout}s")
            logger.debug(f"Prompt length: {len(full_prompt)} chars")
            
            response = self.session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=stream,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            connection_time = time.time() - request_start_time
            logger.debug(f"Ollama connection established in {connection_time:.2f}s, streaming...")
            
            if stream:
                # Stream response chunks with timeout protection
                timeout_triggered = threading.Event()
                response_iterator = response.iter_lines()
                
                def timeout_handler():
                    """Handler called when streaming timeout is reached"""
                    timeout_triggered.set()
                    logger.error(f"[ERROR] Ollama streaming timeout after {streaming_timeout}s - killing connection")
                
                # Set up timeout timer
                timeout_timer = threading.Timer(streaming_timeout, timeout_handler)
                timeout_timer.daemon = True
                timeout_timer.start()
                
                try:
                    for line in response_iterator:
                        # Check if timeout was triggered
                        if timeout_triggered.is_set():
                            elapsed = time.time() - request_start_time
                            logger.error(f"[ERROR] Ollama streaming timed out after {elapsed:.2f}s")
                            yield f"\n\n[ERROR: Streaming timed out after {elapsed:.1f}s - response may be incomplete]"
                            break
                        
                        if line:
                            try:
                                chunk_data = json.loads(line)
                                if "response" in chunk_data:
                                    yield chunk_data["response"]
                                if chunk_data.get("done", False):
                                    # Cancel timeout timer on successful completion
                                    timeout_timer.cancel()
                                    elapsed = time.time() - request_start_time
                                    logger.info(f"[OK] Ollama streaming completed in {elapsed:.2f}s")
                                    break
                            except json.JSONDecodeError:
                                continue
                finally:
                    # Always cancel the timer when done
                    timeout_timer.cancel()
                    
            else:
                # Non-streaming response
                data = response.json()
                elapsed = time.time() - request_start_time
                logger.info(f"[OK] Ollama request completed in {elapsed:.2f}s")
                yield data.get("response", "")
                
        except requests.exceptions.Timeout:
            elapsed = time.time() - request_start_time
            logger.error(f"[ERROR] Ollama request timed out after {elapsed:.2f}s (timeout setting: {self.timeout}s)")
            yield "Request timed out. Please try again with a shorter prompt or context."
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - request_start_time
            logger.error(f"[ERROR] Cannot connect to Ollama API at {self.base_url} after {elapsed:.2f}s: {e}")
            yield "Cannot connect to AI assistant. Please check if Ollama is running."
        except requests.exceptions.HTTPError as e:
            elapsed = time.time() - request_start_time
            # Provide more helpful error messages for common issues
            if e.response and e.response.status_code == 404:
                # 404 usually means model doesn't exist
                logger.error(f"[ERROR] Ollama API HTTP 404 after {elapsed:.2f}s: Model '{model}' not found. Available models: {', '.join(self.list_available_models()[:5])}")
                yield f"Model '{model}' not found. Please ensure the model is installed: ollama pull {model}"
            else:
                logger.error(f"[ERROR] Ollama API HTTP error after {elapsed:.2f}s: {e}")
                yield f"AI assistant error: {str(e)}"
        except Exception as e:
            elapsed = time.time() - request_start_time
            logger.error(f"[ERROR] Unexpected error querying Ollama after {elapsed:.2f}s: {e}", exc_info=True)
            yield f"An error occurred: {str(e)}"

    def _query_webai(
        self,
        *,
        prompt: str,
        context: str,
        model: str,
        system_prompt: Optional[str],
    ) -> Generator[str, None, None]:
        """Route completion requests to cookie-based WebAI service."""
        try:
            from webai_wrapper import PersistentConversationSession
        except ImportError as e:
            logger.error("WebAI wrapper unavailable: %s", e)
            yield "WebAI backend is not available."
            return

        full_prompt = prompt
        if context:
            full_prompt = f"{context}\n\nUser question: {prompt}"

        # WebAI service currently supports non-streaming sync in this project.
        try:
            session_id = f"chat_{int(time.time())}"
            session = PersistentConversationSession(
                session_id=session_id,
                model=model,
                system_prompt=system_prompt or "",
                auto_refresh=False,
            )
            response = session.send_sync(full_prompt) or ""
            if response:
                yield response
            else:
                yield "WebAI returned an empty response."
            try:
                session.reset_sync()
                session.close_sync()
            except Exception:
                pass
        except Exception as e:
            logger.error("WebAI query failed: %s", e, exc_info=True)
            yield f"WebAI error: {str(e)}"

    def _query_glm(
        self,
        *,
        prompt: str,
        context: str,
        model: str,
        stream: bool,
        temperature: Optional[float],
        max_tokens: Optional[int],
        system_prompt: Optional[str],
        json_mode: bool,
    ) -> Generator[str, None, None]:
        """Route completion requests to Z.AI chat/completions for glm-* models."""
        try:
            from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL
        except ImportError as e:
            logger.error("GLM config unavailable: %s", e)
            yield "GLM backend is not available."
            return

        key = get_zhipu_api_key()
        if not key:
            logger.error("GLM API key not configured")
            yield "GLM API key is not configured."
            return

        full_prompt = prompt
        if context:
            full_prompt = f"{context}\n\nUser question: {prompt}"

        model_settings = self.get_model_settings(model)
        effective_temp = temperature if temperature is not None else model_settings.get("temperature", 0.3)
        effective_max_tokens = max_tokens if max_tokens is not None else model_settings.get("num_predict", 2048)

        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        elif json_mode:
            messages.append(
                {
                    "role": "system",
                    "content": "Return ONLY a valid raw JSON object. No markdown code fences.",
                }
            )
        messages.append({"role": "user", "content": full_prompt})

        url = f"{ZHIPU_BASE_URL.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "max_tokens": effective_max_tokens,
            "temperature": effective_temp,
        }

        request_start = time.time()
        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                stream=stream,
                timeout=GLM_TIMEOUT,
            )
            response.raise_for_status()

            if stream:
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.strip():
                        continue
                    s = line.strip()
                    if not s.startswith("data: "):
                        continue
                    data = s[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        for choice in (obj.get("choices") or [])[:1]:
                            delta = choice.get("delta") or {}
                            part = delta.get("content") or ""
                            if part:
                                yield part
                            if choice.get("finish_reason") == "stop":
                                return
                    except json.JSONDecodeError:
                        continue
            else:
                data = response.json()
                content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                if content:
                    yield content
                else:
                    yield "GLM returned an empty response."
        except requests.exceptions.Timeout:
            elapsed = time.time() - request_start
            logger.error("GLM request timed out after %.2fs", elapsed)
            yield "GLM request timed out. Please try again."
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - request_start
            logger.error("GLM connection error after %.2fs: %s", elapsed, e)
            yield "Cannot connect to GLM API."
        except requests.exceptions.HTTPError as e:
            elapsed = time.time() - request_start
            logger.error("GLM HTTP error after %.2fs: %s", elapsed, e)
            yield f"GLM API error: {str(e)}"
        except Exception as e:
            elapsed = time.time() - request_start
            logger.error("Unexpected GLM query error after %.2fs: %s", elapsed, e, exc_info=True)
            yield f"GLM error: {str(e)}"
    
    def generate_completion(
        self, 
        prompt: str, 
        model: str = "glm-4.7", 
        json_mode: bool = False,
        temperature: Optional[float] = None
    ) -> Optional[str]:
        """Generate a complete response (non-streaming).
        
        Args:
            prompt: User prompt
            model: Model name
            json_mode: Whether to enforce JSON output
            temperature: Model temperature
            
        Returns:
            Full response string or None if failed
        """
        try:
            generator = self.query_ollama(
                prompt=prompt,
                model=model,
                stream=False,
                json_mode=json_mode,
                temperature=temperature
            )
            return next(generator, None)
        except Exception as e:
            logger.error(f"Error generating completion: {e}")
            return None
    def analyze_crowd_sentiment(self, texts: List[str], ticker: str, model: Optional[str] = None) -> Dict[str, Any]:
        """Analyze crowd sentiment from Reddit posts/comments.
        
        Sends top posts/comments to Ollama for sentiment analysis.
        Returns label only (EUPHORIC, BULLISH, NEUTRAL, BEARISH, FEARFUL).
        Python code maps label to score - do NOT ask AI for numeric score.
        
        Args:
            texts: List of post/comment texts to analyze (top 5)
            ticker: Ticker symbol being analyzed (for context)
            model: Model name to use. If None, uses get_summarizing_model() from settings.
            
        Returns:
            Dictionary containing:
            - sentiment: One of "EUPHORIC", "BULLISH", "NEUTRAL", "BEARISH", "FEARFUL"
            - reasoning: Brief explanation of the sentiment classification
            
            Returns empty dict if generation fails or AI is disabled.
        """
        if not self.enabled:
            logger.warning("Ollama crowd sentiment analysis rejected: AI assistant disabled")
            return {}
        
        if not texts:
            logger.warning("No texts provided for crowd sentiment analysis")
            return {"sentiment": "NEUTRAL", "reasoning": "No posts to analyze"}
        
        # Get model from settings if not provided
        if model is None:
            try:
                from settings import get_summarizing_model
                model = get_summarizing_model()
            except Exception as e:
                logger.warning(f"Could not load summarizing model from settings: {e}, using fallback")
                model = "glm-4.7"

        audit_start = time.time()
        result: Dict[str, Any] = {}
        audit_error: Optional[str] = None
        
        # Sanitize + delimit untrusted social posts before prompt interpolation.
        sanitized_blocks = []
        for idx, text in enumerate(texts[:5], 1):
            safe_text = sanitize_for_llm(text, max_chars=900)
            if contains_instruction_like_text(safe_text):
                logger.warning("Instruction-like text detected in %s social block for %s", idx, ticker)
            sanitized_blocks.append(
                prepare_untrusted_for_prompt(safe_text, source=f"social_post_{idx}")
            )

        combined_text = "\n\n---\n\n".join(sanitized_blocks)
        
        # System prompt - Robust crowd sentiment analysis
        system_prompt = f"""You are an expert financial sentiment analyst specializing in social media momentum. Analyze these posts about {ticker}.

TASK:
1. Read the posts and identify the prevailing emotion and conviction.
2. categorize the overall sentiment into exactly ONE of these labels:
   - EUPHORIC: Extreme irrational exuberance, "moon" talk, massive FOMO.
   - BULLISH: Confidence, buying discussion, positive catalysts.
   - NEUTRAL: Mixed opinions, questions, or balanced bull/bear debate.
   - BEARISH: Selling discussion, negative catalysts, doubt.
   - FEARFUL: Panic selling, despair, "it's over" talk.

OUTPUT FORMAT:
Return ONLY a raw JSON object with no markdown formatting or code blocks:
{{
  "sentiment": "LABEL",
  "reasoning": "One concise sentence explaining why (e.g., 'Users are excited about upcoming earnings' or 'Panic due to recent drop')."
}}"""
        
        try:
            from skill_loader import build_enhanced_prompt

            system_prompt = build_enhanced_prompt(
                system_prompt,
                combined_text,
                "crowd_sentiment",
            )
        except Exception as exc:
            logger.warning("Skill injection failed for crowd sentiment prompt (falling back to base): %s", exc)

        # User prompt with the actual posts
        user_prompt = f"Analyze the sentiment for {ticker} based on these posts:\n\n{combined_text}"
        
        try:
            # Calculate dynamic timeout based on text length (min 30s, max 90s)
            dynamic_timeout = max(30, min(90, len(combined_text) // 100))
            
            # Query Ollama (non-streaming for structured response)
            full_response = ""
            for chunk in self.query_ollama(
                prompt=user_prompt,
                model=model,
                stream=True,
                system_prompt=system_prompt,
                temperature=0.1,  # Low temperature for strict JSON adherence
                json_mode=True,   # Enforce JSON mode
                streaming_timeout=dynamic_timeout
            ):
                full_response += chunk
            
            # Parse JSON response
            import re
            # Try to extract JSON from response (handle cases where AI adds extra text)
            json_match = re.search(r'\{[^{}]*"sentiment"[^{}]*\}', full_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = full_response.strip()
            
            # Remove markdown code blocks if present
            json_str = re.sub(r'```json\s*', '', json_str)
            json_str = re.sub(r'```\s*', '', json_str)
            json_str = json_str.strip()
            
            parsed = json.loads(json_str)
            
            # Validate sentiment label
            sentiment = parsed.get("sentiment", "NEUTRAL").strip().upper()
            valid_sentiments = ["EUPHORIC", "BULLISH", "NEUTRAL", "BEARISH", "FEARFUL"]
            
            if sentiment not in valid_sentiments:
                logger.warning(f"Invalid sentiment label '{sentiment}', defaulting to NEUTRAL")
                sentiment = "NEUTRAL"
            
            result = {
                "sentiment": sentiment,
                "reasoning": parsed.get("reasoning", "Sentiment analysis completed")
            }
            return result
            
        except json.JSONDecodeError as e:
            audit_error = str(e)
            logger.error(f"❌ Failed to parse JSON from Ollama response: {e}")
            logger.debug(f"Response was: {full_response[:500]}")
            result = {"sentiment": "NEUTRAL", "reasoning": "Failed to parse AI response"}
            return result
        except Exception as e:
            audit_error = str(e)
            logger.error(f"❌ Error analyzing crowd sentiment: {e}", exc_info=True)
            result = {"sentiment": "NEUTRAL", "reasoning": f"Error: {str(e)}"}
            return result
        finally:
            try:
                from ai_audit import _compute_input_hash, _detect_caller, log_inference

                log_inference(
                    function="analyze_crowd_sentiment",
                    model=model,
                    provider="ollama",
                    input_chars=len(combined_text),
                    input_hash=_compute_input_hash(combined_text),
                    output_summary=json.dumps(result, default=str) if result else "",
                    duration_ms=int((time.time() - audit_start) * 1000),
                    success=bool(result.get("sentiment")),
                    error=audit_error,
                    sentiment=result.get("sentiment"),
                    ticker=ticker,
                    caller=_detect_caller(),
                )
            except Exception:
                pass
    
    def generate_summary(
        self,
        text: str,
        model: Optional[str] = None,
        article_type: str = ""
    ) -> Dict[str, Any]:
        """Generate a comprehensive summary with Chain of Thought analysis, sentiment categorization, and relationship extraction.
        
        Uses a 3-step Chain of Thought process: Identify Claims, Fact Check, Conclusion.
        Also categorizes sentiment (VERY_BULLISH, BULLISH, NEUTRAL, BEARISH, VERY_BEARISH) and
        extracts corporate relationships (GraphRAG edges).
        
        Args:
            text: Text to summarize (will be truncated to ~6000 chars)
            model: Model name to use. If None, uses get_summarizing_model() from settings.
            
        Returns:
            Dictionary containing:
            - summary: Enhanced text summary (5-7+ bullet points)
            - claims: List of specific claims with numbers/dates extracted from article
            - fact_check: Simple fact-checking analysis (filters garbage/clickbait)
            - conclusion: Net impact on ticker(s) with specific implications
            - sentiment: One of "VERY_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "VERY_BEARISH"
            - sentiment_score: Numeric score for calculations (VERY_BULLISH=2.0, BULLISH=1.0, NEUTRAL=0.0, BEARISH=-1.0, VERY_BEARISH=-2.0)
            - logic_check: One of "DATA_BACKED", "HYPE_DETECTED", "NEUTRAL" (for relationship confidence scoring)
            - tickers: List of ticker symbols mentioned (e.g., ["HOOD", "NVDA"])
            - sectors: List of sectors mentioned (e.g., ["Financial Services", "Technology"])
            - key_themes: List of key themes/topics
            - companies: List of company names mentioned
            - relationships: List of relationship dicts with "source", "target", "type" keys (GraphRAG edges)
            
            Returns empty dict if generation fails or AI is disabled.
        """
        if not self.enabled:
            logger.warning("Ollama summary generation rejected: AI assistant disabled")
            return {}
        
        # Get model from settings if not provided
        if model is None:
            try:
                from settings import get_summarizing_model
                model = get_summarizing_model()
            except Exception as e:
                logger.warning(f"Could not load summarizing model from settings: {e}, using fallback")
                model = "glm-4.7"

        # Web-based AI service: use cookie-based service, not Ollama
        try:
            from webai_wrapper import is_webai_model
            if is_webai_model(model):
                return _generate_summary_via_webai(text, model, article_type=article_type, stream=False)
        except ImportError:
            pass
        # GLM: use Z.AI, not Ollama (Ollama would 404 for glm-*)
        if model and str(model).startswith("glm-"):
            return _generate_summary_via_zhipu(text, model, article_type=article_type, stream=False)

        # Truncate text to ~6000 characters
        # TODO: PROMPT-INJECTION - Sanitize scraped article text before LLM ingestion.
        #   Article content from trafilatura/RSS is sent as the raw prompt with no
        #   delimiter-based sandboxing. Hidden text or invisible CSS content in articles
        #   could contain adversarial instructions. Mitigations to add:
        #   1. Strip residual HTML, zero-width chars, and control characters
        #   2. Use structural separation between system instructions and article content
        #   3. Validate that trafilatura output doesn't contain hidden/invisible text artifacts
        max_chars = 6000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            logger.debug(f"Truncated text to {max_chars} characters for summarization")

        system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)

        # Get model settings
        model_settings = self.get_model_settings(model)
        effective_temp = model_settings.get('temperature', 0.3)
        effective_ctx = model_settings.get('num_ctx', 4096)
        requested_max_tokens = model_settings.get("num_predict", SUMMARY_DEFAULT_PREDICT)

        # Warn if skill-enhanced prompt + article + output may overflow context
        prompt_tokens_est = len(system_prompt) // 4
        article_tokens_est = len(text) // 4
        effective_max_tokens = _fit_summary_num_predict(
            model=model,
            effective_ctx=effective_ctx,
            prompt_tokens_est=prompt_tokens_est,
            article_tokens_est=article_tokens_est,
            requested_num_predict=requested_max_tokens,
        )
        total_est = prompt_tokens_est + article_tokens_est + effective_max_tokens
        if total_est > effective_ctx:
            logger.warning(
                "Context window likely exceeded for model=%s: "
                "system≈%d + article≈%d + output=%d = ~%d tokens vs ctx=%d. "
                "Consider increasing num_ctx or reducing skill budget.",
                model, prompt_tokens_est, article_tokens_est,
                effective_max_tokens, total_est, effective_ctx,
            )
        elif total_est > effective_ctx * 0.85:
            logger.info(
                "Context window >85%% full for model=%s: ~%d/%d tokens",
                model, total_est, effective_ctx,
            )

        # Prepare request payload
        payload = {
            "model": model,
            "prompt": text,
            "stream": False,
            "system": system_prompt,
            "options": {
                "temperature": effective_temp,
                "num_predict": effective_max_tokens,
                "num_ctx": effective_ctx
            }
        }
        
        try:
            start_time = time.time()
            logger.info(f"Generating enhanced summary with model {model}")
            response = self.session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            elapsed_time = time.time() - start_time
            logger.info(f"✅ Summary generated in {elapsed_time:.2f}s")
            
            data = response.json()
            raw_response = data.get("response", "").strip()
            
            if not raw_response:
                logger.warning("Empty response from Ollama")
                return {}

            return parse_summary_response(raw_response)

        except requests.exceptions.Timeout:
            logger.error(f"❌ Ollama summary request timed out after {self.timeout}s")
            return {}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] Cannot connect to Ollama API at {self.base_url}: {e}")
            return {}
        except Exception as e:
            logger.error(f"❌ Error generating summary: {e}", exc_info=True)
            return {}
    
    def generate_summary_streaming(
        self,
        text: str,
        model: Optional[str] = None,
        article_type: str = "",
        progress_callback=None
    ) -> Dict[str, Any]:
        """Generate a comprehensive summary with streaming progress updates.

        Same as generate_summary but yields progress updates during generation.
        Use this for Server-Sent Events (SSE) to show real-time progress in the UI.

        Args:
            text: Text to summarize (will be truncated to ~6000 chars)
            model: Model name to use. If None, uses get_summarizing_model() from settings.
            progress_callback: Optional callback function(tokens_received, estimated_progress) called with progress updates

        Returns:
            Same dictionary as generate_summary
        """
        if model is None:
            try:
                from settings import get_summarizing_model
                model = get_summarizing_model()
            except Exception as e:
                logger.warning(f"Could not load summarizing model from settings: {e}, using fallback")
                model = "glm-4.7"

        # Web-based AI service: use cookie-based service, not Ollama (note: doesn't support streaming)
        try:
            from webai_wrapper import is_webai_model
            if is_webai_model(model):
                return _generate_summary_via_webai(
                    text,
                    model,
                    article_type=article_type,
                    progress_callback=progress_callback,
                    stream=False,
                )
        except ImportError:
            pass
        # GLM: use Z.AI, not Ollama
        if model and str(model).startswith("glm-"):
            return _generate_summary_via_zhipu(
                text,
                model,
                article_type=article_type,
                progress_callback=progress_callback,
                stream=True,
            )

        if not self.enabled:
            logger.warning("Ollama summary generation rejected: AI assistant disabled")
            return {}

        # Truncate text to ~6000 characters
        max_chars = 6000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            logger.debug(f"Truncated text to {max_chars} characters for summarization")
        
        system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)

        # Get model settings
        model_settings = self.get_model_settings(model)
        effective_temp = model_settings.get("temperature", 0.3)
        effective_ctx = model_settings.get("num_ctx", 4096)
        requested_max_tokens = model_settings.get("num_predict", SUMMARY_DEFAULT_PREDICT)

        # Warn if skill-enhanced prompt + article + output may overflow context
        prompt_tokens_est = len(system_prompt) // 4
        article_tokens_est = len(text) // 4
        effective_max_tokens = _fit_summary_num_predict(
            model=model,
            effective_ctx=effective_ctx,
            prompt_tokens_est=prompt_tokens_est,
            article_tokens_est=article_tokens_est,
            requested_num_predict=requested_max_tokens,
        )
        total_est = prompt_tokens_est + article_tokens_est + effective_max_tokens
        if total_est > effective_ctx:
            logger.warning(
                "Context window likely exceeded (streaming) for model=%s: "
                "system≈%d + article≈%d + output=%d = ~%d tokens vs ctx=%d. "
                "Consider increasing num_ctx or reducing skill budget.",
                model, prompt_tokens_est, article_tokens_est,
                effective_max_tokens, total_est, effective_ctx,
            )
        elif total_est > effective_ctx * 0.85:
            logger.info(
                "Context window >85%% full (streaming) for model=%s: ~%d/%d tokens",
                model, total_est, effective_ctx,
            )

        # Prepare streaming request payload
        payload = {
            "model": model,
            "prompt": text,
            "stream": True,  # Enable streaming!
            "system": system_prompt,
            "options": {
                "temperature": effective_temp,
                "num_predict": effective_max_tokens,
                "num_ctx": effective_ctx
            }
        }
        
        try:
            start_time = time.time()
            logger.info(f"Generating streaming summary with model {model}")
            
            response = self.session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=True,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            # Accumulate response while streaming
            raw_response = ""
            tokens_received = 0
            estimated_total_tokens = 800  # Average summary length
            
            for line in response.iter_lines():
                if line:
                    try:
                        chunk_data = json.loads(line)
                        if "response" in chunk_data:
                            chunk_text = chunk_data["response"]
                            raw_response += chunk_text
                            tokens_received += len(chunk_text.split())  # Rough token count
                            
                            # Call progress callback if provided
                            if progress_callback:
                                # Estimate progress (cap at 95% until done)
                                estimated_progress = min(95, int((tokens_received / estimated_total_tokens) * 100))
                                progress_callback(tokens_received, estimated_progress)
                        
                        if chunk_data.get("done", False):
                            # Final callback at 100%
                            if progress_callback:
                                progress_callback(tokens_received, 100)
                            break
                    except json.JSONDecodeError:
                        continue
            
            elapsed_time = time.time() - start_time
            logger.info(f"✅ Streaming summary generated in {elapsed_time:.2f}s ({tokens_received} tokens)")
            
            # Parse the complete response (same logic as generate_summary)
            if not raw_response:
                logger.warning("Empty response from Ollama")
                return {}
            
            return parse_summary_response(raw_response)

        except requests.exceptions.Timeout:
            logger.error(f"❌ Ollama streaming summary timed out after {self.timeout}s")
            return {}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"[ERROR] Cannot connect to Ollama API at {self.base_url}: {e}")
            return {}
        except Exception as e:
            logger.error(f"❌ Error generating streaming summary: {e}", exc_info=True)
            return {}
    
    def generate_embedding(self, text: str, model: str = "nomic-embed-text") -> List[float]:
        """Generate embedding vector for text using Ollama embedding API.
        
        Args:
            text: Text to generate embedding for
            model: Embedding model name (defaults to nomic-embed-text)
            
        Returns:
            List of floats (768 dimensions for nomic-embed-text)
        """
        if not self.enabled:
            logger.warning("Ollama embedding generation rejected: AI assistant disabled")
            return []
        
        # Prepare request payload
        payload = {
            "model": model,
            "prompt": text
        }
        audit_start = time.time()
        embedding: List[float] = []
        audit_error: Optional[str] = None
        
        try:
            logger.debug(f"Generating embedding with model {model}")
            response = self.session.post(
                f"{self.base_url}/api/embeddings",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            embedding = data.get("embedding", [])
            
            if not embedding:
                logger.warning(f"No embedding returned from model {model}")
                return []
            
            logger.debug(f"Generated embedding: {len(embedding)} dimensions")
            return embedding
            
        except requests.exceptions.Timeout:
            audit_error = f"timeout after {self.timeout}s"
            logger.error(f"❌ Ollama embedding request timed out after {self.timeout}s")
            return []
        except requests.exceptions.ConnectionError as e:
            audit_error = str(e)
            logger.error(f"[ERROR] Cannot connect to Ollama API at {self.base_url}: {e}")
            return []
        except Exception as e:
            audit_error = str(e)
            logger.error(f"❌ Error generating embedding: {e}", exc_info=True)
            return []
        finally:
            try:
                from ai_audit import _compute_input_hash, _detect_caller, log_inference

                log_inference(
                    function="generate_embedding",
                    model=model,
                    provider="ollama",
                    input_chars=len(text),
                    input_hash=_compute_input_hash(text),
                    output_summary=f"embedding_dims={len(embedding)}" if embedding else "empty",
                    duration_ms=int((time.time() - audit_start) * 1000),
                    success=bool(embedding),
                    error=audit_error,
                    caller=_detect_caller(),
                )
            except Exception:
                pass
    
    def query_ollama_chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "glm-4.7",
        stream: bool = True,
        temperature: Optional[float] = None,
        max_tokens: int = 2048,
        num_ctx: Optional[int] = None
    ) -> Generator[str, None, None]:
        """Query Ollama using chat API format.
        
        Args:
            messages: List of message dicts with "role" and "content" keys
            model: Model name to use
            stream: Whether to stream the response
            temperature: Model temperature (0.0-1.0). If None, uses model default.
            max_tokens: Maximum tokens in response
            num_ctx: Context window size. If None, uses model default.
            
        Yields:
            Response chunks as strings
        """
        if not self.enabled:
            yield "AI assistant is currently disabled."
            return
        
        # Get model-specific defaults if values not provided
        model_settings = self.get_model_settings(model)
        
        # Use provided values, or model specific defaults, or global defaults
        effective_temp = temperature if temperature is not None else model_settings.get('temperature', 0.7)
        effective_ctx = num_ctx if num_ctx is not None else model_settings.get('num_ctx', 4096)
        effective_max_tokens = max_tokens if max_tokens is not None else model_settings.get('num_predict', 2048)
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": effective_temp,
                "num_predict": effective_max_tokens,
                "num_ctx": effective_ctx
            }
        }
        
        try:
            response = self.session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=stream,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            if stream:
                for line in response.iter_lines():
                    if line:
                        try:
                            chunk_data = json.loads(line)
                            if "message" in chunk_data and "content" in chunk_data["message"]:
                                yield chunk_data["message"]["content"]
                            if chunk_data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
            else:
                data = response.json()
                if "message" in data and "content" in data["message"]:
                    yield data["message"]["content"]
                    
        except Exception as e:
            logger.error(f"Error in chat API: {e}")
            yield f"An error occurred: {str(e)}"


# Global client instance
_ollama_client: Optional[OllamaClient] = None


def get_ollama_client() -> Optional[OllamaClient]:
    """Get or create global Ollama client instance.
    
    Returns:
        OllamaClient instance or None if disabled
    """
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client if _ollama_client.enabled else None


def check_ollama_health() -> bool:
    """Check if Ollama is available.

    Returns:
        True if Ollama is reachable
    """
    client = get_ollama_client()
    return client.check_health() if client else False


def _generate_summary_via_webai(
    text: str,
    model: str,
    *,
    article_type: str = "",
    progress_callback=None,
    stream: bool = False
) -> Dict[str, Any]:
    """Run article summarization via web-based AI service (cookie-based). Used for WebAI models."""
    try:
        from webai_wrapper import PersistentConversationSession
        from summary_common import get_summary_system_prompt, parse_summary_response
    except ImportError:
        logger.warning("webai_wrapper or summary_common not available for web-based AI summary")
        return {}

    max_chars = 6000
    original_len = len(text)
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
        logger.debug(f"Truncated text from {original_len} to {max_chars} characters for web-based AI summarization")

    system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)
    total_chars = len(system_prompt) + len(text)
    logger.debug(f"Web-based AI prompt length: {total_chars} chars (system: {len(system_prompt)}, user: {len(text)})")

    # Note: Web-based AI service doesn't support streaming, so stream parameter is ignored
    if stream and progress_callback:
        progress_callback(0, 10)  # Indicate start

    timeout_sec = GLM_TIMEOUT
    start_time = time.time()
    logger.info(
        f"🤖 Web-based AI summary query starting: model={model}, "
        f"stream=False (not supported), timeout={timeout_sec}s"
    )

    try:
        # Create a temporary session for this summarization task
        # Use a unique session ID based on timestamp to avoid conversation history
        session_id = f"summary_{int(time.time())}"
        session = PersistentConversationSession(
            session_id=session_id,
            model=model,
            system_prompt=system_prompt,
            auto_refresh=False,
        )

        # Combine system prompt and article text (web-based service needs instructions in message)
        full_message = f"{system_prompt}\n\nArticle to analyze:\n\n{text}"

        if progress_callback:
            progress_callback(len(full_message), 30)  # Indicate sending

        conn_start = time.time()
        raw = session.send_sync(full_message)
        connection_time = time.time() - conn_start
        elapsed = time.time() - start_time

        # Clean up session
        try:
            session.reset_sync()
            session.close_sync()
        except Exception:
            pass  # Ignore cleanup errors

        logger.info(f"✅ Web-based AI summary completed in {elapsed:.2f}s (connection: {connection_time:.2f}s)")

        if progress_callback:
            progress_callback(len(raw), 100)

        if not raw or not raw.strip():
            logger.warning("Empty response from web-based AI service")
            return {}
        return parse_summary_response(raw.strip())

    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"❌ Web-based AI summary request failed after {elapsed:.2f}s: {e}",
            exc_info=True,
        )
        return {}


def _generate_summary_via_zhipu(
    text: str,
    model: str,
    *,
    article_type: str = "",
    progress_callback=None,
    stream: bool = False
) -> Dict[str, Any]:
    """Run article summarization via Z.AI /chat/completions. Used when model.startswith('glm-')."""
    try:
        from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL
        from summary_common import get_summary_system_prompt, parse_summary_response
    except ImportError:
        logger.warning("glm_config or summary_common not available for GLM summary")
        return {}

    key = get_zhipu_api_key()
    if not key or not key.strip():
        logger.warning("Z.AI API key not set - cannot generate summary with GLM model")
        return {}

    max_chars = 6000
    original_len = len(text)
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
        logger.debug(f"Truncated text from {original_len} to {max_chars} characters for Z.AI summarization")

    system_prompt = get_summary_system_prompt(article_text=text, article_type=article_type)
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]
    total_chars = len(system_prompt) + len(text)
    logger.debug(f"Z.AI prompt length: {total_chars} chars (system: {len(system_prompt)}, user: {len(text)})")

    # Model config: max_tokens, temperature
    cfg_path = os.path.join(os.path.dirname(__file__), "model_config.json")
    me = {}
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                mc = json.load(f)
            me = (mc.get("models") or {}).get(model, mc.get("default_config") or {})
        except Exception:
            pass
    max_tokens = me.get("max_tokens") or me.get("num_predict") or 1024
    temperature = float(me.get("temperature", 0.3))

    url = f"{ZHIPU_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    timeout_sec = GLM_TIMEOUT
    start_time = time.time()
    logger.info(
        f"🤖 Z.AI summary query starting: model={model}, temp={temperature}, max_tokens={max_tokens}, "
        f"stream={stream}, timeout={timeout_sec}s, url={url}"
    )

    try:
        conn_start = time.time()
        r = requests.post(url, json=payload, headers=headers, stream=stream, timeout=timeout_sec)
        connection_time = time.time() - conn_start
        if stream:
            logger.debug(f"⏱️  Z.AI connection established in {connection_time:.2f}s, streaming...")
        r.raise_for_status()
    except requests.exceptions.Timeout as e:
        elapsed = time.time() - start_time
        logger.error(
            f"❌ Z.AI summary request timed out after {elapsed:.2f}s (timeout setting: {timeout_sec}s): {e}",
            exc_info=True,
        )
        return {}
    except requests.exceptions.ConnectionError as e:
        elapsed = time.time() - start_time
        logger.error(
            f"❌ Cannot connect to Z.AI API at {url} after {elapsed:.2f}s: {e}",
            exc_info=True,
        )
        return {}
    except requests.exceptions.HTTPError as e:
        elapsed = time.time() - start_time
        status_code = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
        error_detail = ""
        if hasattr(e, "response") and e.response is not None:
            try:
                error_body = e.response.text[:500]
                error_detail = f" Response: {error_body}"
            except Exception:
                pass
        logger.error(
            f"❌ Z.AI API HTTP error after {elapsed:.2f}s: {e} (status={status_code}){error_detail}",
            exc_info=True,
        )
        return {}
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"❌ Unexpected error querying Z.AI after {elapsed:.2f}s: {e}",
            exc_info=True,
        )
        return {}

    raw = ""
    tokens_received = 0
    if stream:
        try:
            for line in r.iter_lines(decode_unicode=True):
                if not line or not line.strip():
                    continue
                s = line.strip()
                if s.startswith("data: "):
                    data = s[6:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        obj = json.loads(data)
                        for c in (obj.get("choices") or [])[:1]:
                            part = (c.get("delta") or {}).get("content") or ""
                            if part:
                                raw += part
                                tokens_received += len(part.split())  # Rough token count
                                if progress_callback:
                                    progress_callback(len(raw), min(95, len(raw) // 10))
                            if c.get("finish_reason") == "stop":
                                break
                    except json.JSONDecodeError:
                        continue
            if progress_callback:
                progress_callback(len(raw), 100)
            elapsed = time.time() - start_time
            logger.info(f"✅ Z.AI streaming summary completed in {elapsed:.2f}s ({tokens_received} tokens)")
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"❌ Z.AI streaming error after {elapsed:.2f}s: {e}",
                exc_info=True,
            )
            return {}
    else:
        try:
            data = r.json()
            raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            elapsed = time.time() - start_time
            logger.info(f"✅ Z.AI summary request completed in {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"❌ Z.AI response parsing error after {elapsed:.2f}s: {e}",
                exc_info=True,
            )
            return {}

    if not raw or not raw.strip():
        logger.warning("Empty response from Z.AI")
        return {}
    return parse_summary_response(raw.strip())


def generate_summary(
    text: str, model: Optional[str] = None, article_type: str = ""
) -> Dict[str, Any]:
    """Module-level summary entry with provider/model fallback support."""
    model_chain = _get_summary_model_chain(model)
    if not model_chain:
        logger.error("No summary models available for generation")
        return {}

    for idx, candidate in enumerate(model_chain, start=1):
        logger.info(
            "Summary attempt %s/%s using model=%s",
            idx,
            len(model_chain),
            candidate,
        )
        result = _generate_summary_once(
            text=text,
            model=candidate,
            article_type=article_type,
            stream=False,
            progress_callback=None,
        )
        if _has_summary_output(result):
            logger.info("Summary generated successfully with model=%s", candidate)
            return result
        logger.warning("Summary attempt failed/empty for model=%s", candidate)

    logger.error("All summary attempts failed across model chain: %s", model_chain)
    return {}


def generate_summary_streaming(
    text: str,
    model: Optional[str] = None,
    article_type: str = "",
    progress_callback=None
) -> Dict[str, Any]:
    """Module-level streaming summary entry with provider/model fallback support."""
    model_chain = _get_summary_model_chain(model)
    if not model_chain:
        logger.error("No summary models available for streaming generation")
        return {}

    for idx, candidate in enumerate(model_chain, start=1):
        logger.info(
            "Streaming summary attempt %s/%s using model=%s",
            idx,
            len(model_chain),
            candidate,
        )
        result = _generate_summary_once(
            text=text,
            model=candidate,
            article_type=article_type,
            stream=True,
            progress_callback=progress_callback,
        )
        if _has_summary_output(result):
            logger.info("Streaming summary generated successfully with model=%s", candidate)
            return result
        logger.warning("Streaming summary attempt failed/empty for model=%s", candidate)

    logger.error("All streaming summary attempts failed across model chain: %s", model_chain)
    return {}


def _has_summary_output(result: Any) -> bool:
    """True when a summary result is non-empty and usable."""
    if isinstance(result, str):
        return bool(result.strip())
    if isinstance(result, dict):
        summary = result.get("summary", "")
        return isinstance(summary, str) and bool(summary.strip())
    return False


def _get_summary_model_chain(requested_model: Optional[str]) -> List[str]:
    """Build ordered model chain: primary model followed by configured/provider fallbacks."""
    primary = requested_model
    fallback_models: List[str] = []
    try:
        from settings import get_summarizing_model, get_summarizing_fallback_models

        if not primary:
            primary = get_summarizing_model()
        fallback_models = get_summarizing_fallback_models()
    except Exception as e:
        logger.warning("Could not load summarization settings: %s", e)
        if not primary:
            primary = "glm-4.7"
        fallback_models = []

    defaults: List[str] = []
    p = (primary or "").strip()
    if p.startswith("glm-"):
        # Keep a fast GLM fallback in-chain even when DB fallback list is unset.
        defaults = ["glm-4.7", "glm-4.5-air"]
    else:
        defaults = ["glm-4.5-air"]

    chain = [primary] + fallback_models + defaults
    ordered: List[str] = []
    seen: set[str] = set()
    for m in chain:
        if not m:
            continue
        s = str(m).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        ordered.append(s)
    return ordered


def _generate_summary_once(
    text: str,
    model: str,
    *,
    article_type: str = "",
    stream: bool,
    progress_callback=None,
) -> Dict[str, Any]:
    """Generate a summary once for the specified model/provider."""
    start_ms = time.time()
    result: Dict[str, Any] = {}
    error_msg: Optional[str] = None

    try:
        # Web-based AI service
        try:
            from webai_wrapper import is_webai_model

            if is_webai_model(model):
                result = _generate_summary_via_webai(
                    text,
                    model,
                    article_type=article_type,
                    progress_callback=progress_callback,
                    stream=False,
                )
                return result
        except ImportError:
            pass

        # GLM via Z.AI
        if model.startswith("glm-"):
            result = _generate_summary_via_zhipu(
                text,
                model,
                article_type=article_type,
                progress_callback=progress_callback,
                stream=stream,
            )
            return result

        # Ollama model
        client = get_ollama_client()
        if not client:
            logger.warning("Ollama client unavailable for model=%s", model)
            return {}
        if stream:
            result = client.generate_summary_streaming(
                text,
                model=model,
                article_type=article_type,
                progress_callback=progress_callback,
            )
            return result
        result = client.generate_summary(text, model=model, article_type=article_type)
        return result
    except Exception as e:
        error_msg = str(e)
        raise
    finally:
        try:
            from ai_audit import (
                _compute_input_hash,
                _detect_caller,
                _detect_provider,
                get_audit_context,
                log_inference,
            )

            context = get_audit_context()
            log_inference(
                function="generate_summary",
                model=model,
                provider=_detect_provider(model),
                input_chars=len(text),
                input_hash=_compute_input_hash(text),
                output_summary=(result.get("summary", "") or "")
                if isinstance(result, dict)
                else "",
                duration_ms=int((time.time() - start_ms) * 1000),
                success=bool(result) and error_msg is None,
                error=error_msg,
                tickers_extracted=result.get("tickers") if isinstance(result, dict) else None,
                sentiment=result.get("sentiment") if isinstance(result, dict) else None,
                logic_check=result.get("logic_check") if isinstance(result, dict) else None,
                market_relevance=result.get("market_relevance") if isinstance(result, dict) else None,
                caller=_detect_caller(),
                article_type=article_type or None,
                article_url=context.get("article_url"),
                article_title=context.get("article_title"),
            )
        except Exception:
            pass


def list_available_models(include_hidden: bool = False) -> List[str]:
    """
    List all available AI models for selection.

    By default, excludes models marked as "hidden": true in model_config.json.
    Models not in the JSON config are included (backward compatibility).
    Also includes WebAI web-based model options.

    Args:
        include_hidden: If True, include models marked as hidden

    Returns:
        List of model names (filtered, includes WebAI variants)
    """
    models = []
    client = get_ollama_client()
    if client:
        models = client.get_filtered_models(include_hidden=include_hidden)
    
    # Add web-based AI model options
    try:
        from webai_wrapper import get_webai_models
        for webai_model in get_webai_models():
            if webai_model not in models:
                models.append(webai_model)
    except ImportError:
        pass

    # Add GLM models only when Zhipu API key is set (optional)
    try:
        from glm_config import get_zhipu_api_key, get_glm_models

        if get_zhipu_api_key():
            for m in get_glm_models():
                if m not in models:
                    models.append(m)
    except ImportError:
        pass

    return models
