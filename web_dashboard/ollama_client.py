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
from dotenv import load_dotenv

from summary_common import get_summary_system_prompt, parse_summary_response

# Load environment variables from .env file (if it exists)
# This allows local development with .env file, but Docker/CI can override with actual env vars
load_dotenv()

logger = logging.getLogger(__name__)

# Default configuration from environment variables
# Priority: Docker env vars > .env file > Python defaults
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_ENABLED = os.getenv("OLLAMA_ENABLED", "true").lower() == "true"


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
        self.model_config = self._load_model_config()

    def _load_model_config(self) -> Dict[str, Any]:
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
        model: str = "llama3",
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
            logger.info(f"🤖 Ollama query starting: model={model}, temp={effective_temp}, ctx={effective_ctx}, max_tokens={effective_max_tokens}, stream={stream}, timeout={streaming_timeout}s")
            logger.debug(f"Prompt length: {len(full_prompt)} chars")
            
            response = self.session.post(
                f"{self.base_url}/api/generate",
                json=payload,
                stream=stream,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            connection_time = time.time() - request_start_time
            logger.debug(f"⏱️  Ollama connection established in {connection_time:.2f}s, streaming...")
            
            if stream:
                # Stream response chunks with timeout protection
                timeout_triggered = threading.Event()
                response_iterator = response.iter_lines()
                
                def timeout_handler():
                    """Handler called when streaming timeout is reached"""
                    timeout_triggered.set()
                    logger.error(f"❌ Ollama streaming timeout after {streaming_timeout}s - killing connection")
                
                # Set up timeout timer
                timeout_timer = threading.Timer(streaming_timeout, timeout_handler)
                timeout_timer.daemon = True
                timeout_timer.start()
                
                try:
                    for line in response_iterator:
                        # Check if timeout was triggered
                        if timeout_triggered.is_set():
                            elapsed = time.time() - request_start_time
                            logger.error(f"❌ Ollama streaming timed out after {elapsed:.2f}s")
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
                                    logger.info(f"✅ Ollama streaming completed in {elapsed:.2f}s")
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
                logger.info(f"✅ Ollama request completed in {elapsed:.2f}s")
                yield data.get("response", "")
                
        except requests.exceptions.Timeout:
            elapsed = time.time() - request_start_time
            logger.error(f"❌ Ollama request timed out after {elapsed:.2f}s (timeout setting: {self.timeout}s)")
            yield "Request timed out. Please try again with a shorter prompt or context."
        except requests.exceptions.ConnectionError as e:
            elapsed = time.time() - request_start_time
            logger.error(f"❌ Cannot connect to Ollama API at {self.base_url} after {elapsed:.2f}s: {e}")
            yield "Cannot connect to AI assistant. Please check if Ollama is running."
        except requests.exceptions.HTTPError as e:
            elapsed = time.time() - request_start_time
            # Provide more helpful error messages for common issues
            if e.response and e.response.status_code == 404:
                # 404 usually means model doesn't exist
                logger.error(f"❌ Ollama API HTTP 404 after {elapsed:.2f}s: Model '{model}' not found. Available models: {', '.join(self.list_available_models()[:5])}")
                yield f"Model '{model}' not found. Please ensure the model is installed: ollama pull {model}"
            else:
                logger.error(f"❌ Ollama API HTTP error after {elapsed:.2f}s: {e}")
                yield f"AI assistant error: {str(e)}"
        except Exception as e:
            elapsed = time.time() - request_start_time
            logger.error(f"❌ Unexpected error querying Ollama after {elapsed:.2f}s: {e}", exc_info=True)
            yield f"An error occurred: {str(e)}"
    
    def generate_completion(
        self, 
        prompt: str, 
        model: str = "llama3", 
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
                model = "granite3.3:8b"
        
        # Combine texts into single prompt
        combined_text = "\n\n---\n\n".join(texts[:5])  # Limit to top 5
        
        # Truncate if too long (keep first ~4000 chars)
        max_chars = 4000
        if len(combined_text) > max_chars:
            combined_text = combined_text[:max_chars] + "..."
            logger.debug(f"Truncated combined text to {max_chars} characters")
        
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
            
            return {
                "sentiment": sentiment,
                "reasoning": parsed.get("reasoning", "Sentiment analysis completed")
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse JSON from Ollama response: {e}")
            logger.debug(f"Response was: {full_response[:500]}")
            return {"sentiment": "NEUTRAL", "reasoning": "Failed to parse AI response"}
        except Exception as e:
            logger.error(f"❌ Error analyzing crowd sentiment: {e}", exc_info=True)
            return {"sentiment": "NEUTRAL", "reasoning": f"Error: {str(e)}"}
    
    def generate_summary(self, text: str, model: Optional[str] = None) -> Dict[str, Any]:
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
                model = "granite3.3:8b"

        # GLM: use Z.AI, not Ollama (Ollama would 404 for glm-*)
        if model and str(model).startswith("glm-"):
            return _generate_summary_via_zhipu(text, model, stream=False)

        # Truncate text to ~6000 characters
        max_chars = 6000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            logger.debug(f"Truncated text to {max_chars} characters for summarization")

        system_prompt = get_summary_system_prompt()

        # Get model settings
        model_settings = self.get_model_settings(model)
        effective_temp = model_settings.get('temperature', 0.3)
        effective_ctx = model_settings.get('num_ctx', 4096)
        effective_max_tokens = model_settings.get('num_predict', 1024)  # Increased for more comprehensive summaries
        
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
            logger.error(f"❌ Cannot connect to Ollama API at {self.base_url}: {e}")
            return {}
        except Exception as e:
            logger.error(f"❌ Error generating summary: {e}", exc_info=True)
            return {}
    
    def generate_summary_streaming(self, text: str, model: Optional[str] = None, progress_callback=None) -> Dict[str, Any]:
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
                model = "granite3.3:8b"

        # GLM: use Z.AI, not Ollama
        if model and str(model).startswith("glm-"):
            return _generate_summary_via_zhipu(text, model, progress_callback=progress_callback, stream=True)

        if not self.enabled:
            logger.warning("Ollama summary generation rejected: AI assistant disabled")
            return {}

        # Truncate text to ~6000 characters
        max_chars = 6000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."
            logger.debug(f"Truncated text to {max_chars} characters for summarization")
        
        system_prompt = get_summary_system_prompt()

        # Get model settings
        model_settings = self.get_model_settings(model)
        effective_temp = model_settings.get("temperature", 0.3)
        effective_ctx = model_settings.get("num_ctx", 4096)
        effective_max_tokens = model_settings.get("num_predict", 1024)
        
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
            logger.error(f"❌ Cannot connect to Ollama API at {self.base_url}: {e}")
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
            logger.error(f"❌ Ollama embedding request timed out after {self.timeout}s")
            return []
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ Cannot connect to Ollama API at {self.base_url}: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ Error generating embedding: {e}", exc_info=True)
            return []
    
    def query_ollama_chat(
        self,
        messages: List[Dict[str, str]],
        model: str = "llama3",
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


def _generate_summary_via_zhipu(
    text: str, model: str, *, progress_callback=None, stream: bool = False
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
        return {}

    max_chars = 6000
    if len(text) > max_chars:
        text = text[:max_chars] + "..."

    system_prompt = get_summary_system_prompt()
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": text}]

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

    try:
        logger.info(f"Generating summary with model {model} via Z.AI")
        r = requests.post(url, json=payload, headers=headers, stream=stream, timeout=120)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"Z.AI summary request failed: {e}", exc_info=True)
        return {}

    raw = ""
    if stream:
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
                            if progress_callback:
                                progress_callback(len(raw), min(95, len(raw) // 10))
                        if c.get("finish_reason") == "stop":
                            break
                except json.JSONDecodeError:
                    continue
        if progress_callback:
            progress_callback(len(raw), 100)
    else:
        data = r.json()
        raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    if not raw or not raw.strip():
        return {}
    return parse_summary_response(raw.strip())


def generate_summary_streaming(
    text: str, model: Optional[str] = None, progress_callback=None
) -> Dict[str, Any]:
    """Module-level entry: routes to Z.AI for glm-* or OllamaClient.generate_summary_streaming."""
    if model is None:
        try:
            from settings import get_summarizing_model
            model = get_summarizing_model()
        except Exception:
            model = "granite3.3:8b"
    if model and str(model).startswith("glm-"):
        return _generate_summary_via_zhipu(text, model, progress_callback=progress_callback, stream=True)
    client = get_ollama_client()
    if not client:
        return {}
    return client.generate_summary_streaming(text, model=model, progress_callback=progress_callback)


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
    
    # Add web-based WebAI model options
    webai_models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.0-pro"]
    for webai_model in webai_models:
        if webai_model not in models:
            models.append(webai_model)

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
