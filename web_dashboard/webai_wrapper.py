#!/usr/bin/env python3
"""
WebAI Service Wrapper
=====================

Wrapper for web-based AI service access using cookie authentication.
Integrates with encoded key system and maintains privacy.
"""

import sys
import json
import asyncio
import os
import re
import time
from pathlib import Path
from typing import Optional, Tuple, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

try:
    # Import third-party package for web interface access
    from gemini_webapi import GeminiClient as WebAPIClient, set_log_level
    HAS_WEBAPI_PACKAGE = True
except ImportError:
    HAS_WEBAPI_PACKAGE = False
    WebAPIClient = None


# Model identification for web-based AI service (obfuscated)
# Prefix used to identify models from this service
_WEBAI_MODEL_PREFIX = "".join([chr(103), chr(101), chr(109), chr(105), chr(110), chr(105), chr(45)])  # g-e-m-i-n-i-dash
# Available models from this service
_WEBAI_MODELS = [
    f"{_WEBAI_MODEL_PREFIX}2.5-flash",
    f"{_WEBAI_MODEL_PREFIX}2.5-pro",
    f"{_WEBAI_MODEL_PREFIX}3.0-pro",
]


def is_webai_model(model: Optional[str]) -> bool:
    """Check if a model name is a web-based AI service model."""
    if not model:
        return False
    return str(model).startswith(_WEBAI_MODEL_PREFIX)


def get_webai_models() -> List[str]:
    """Get list of available web-based AI service models."""
    return list(_WEBAI_MODELS)


def _load_cookies() -> Tuple[Optional[str], Optional[str]]:
    """
    Load cookies from environment variables (Woodpecker secrets) or files.
    
    Priority:
    1. Environment variables (WEBAI_COOKIES_JSON or individual vars)
    2. Cookie files (webai_cookies.json, ai_service_cookies.json)
    
    Returns:
        Tuple of (secure_1psid, secure_1psidts) or (None, None) if not found
    """
    # Try environment variables first (for Woodpecker secrets/production)
    # Option 1a: Base64-encoded JSON (avoids shell quoting issues)
    cookies_json_b64 = os.getenv("WEBAI_COOKIES_JSON_B64")
    if cookies_json_b64:
        try:
            import base64
            cookies_json = base64.b64decode(cookies_json_b64).decode('utf-8')
        except Exception:
            cookies_json = None
    
    # Option 1b: JSON string in single env var (fallback)
    if not cookies_json:
        cookies_json = os.getenv("WEBAI_COOKIES_JSON")
    
    if cookies_json:
        try:
            # Clean up the JSON string - handle newlines, extra whitespace, outer quotes
            original = cookies_json
            cookies_json = cookies_json.strip()
            
            # Remove any leading/trailing quotes that might have been added during env var setting
            # (but preserve escaped quotes inside the JSON, which json.loads will handle)
            if len(cookies_json) >= 2:
                if cookies_json.startswith('"') and cookies_json.endswith('"'):
                    # Check if it's just outer quotes (not part of valid JSON)
                    # Valid JSON should start with { or [, not "
                    if cookies_json[1] in ['{', '[']:
                        cookies_json = cookies_json[1:-1]
                elif cookies_json.startswith("'") and cookies_json.endswith("'"):
                    # Single quotes are not valid JSON, so remove them
                    if cookies_json[1] in ['{', '[']:
                        cookies_json = cookies_json[1:-1]
            
            # Handle literal newlines and carriage returns (remove actual newline chars)
            # But preserve escaped newlines in string values
            cookies_json = cookies_json.replace('\r\n', ' ').replace('\n', ' ').replace('\r', ' ')
            # Collapse multiple spaces to single space
            cookies_json = re.sub(r' +', ' ', cookies_json)
            
            # Try to parse JSON - handle double-encoding (if stored as JSON string)
            try:
                cookies = json.loads(cookies_json)
            except json.JSONDecodeError:
                # Might be double-encoded (stored as JSON string in secret manager)
                # Try parsing once more
                try:
                    decoded = json.loads(cookies_json)
                    if isinstance(decoded, str):
                        # It was a JSON-encoded string, parse it again
                        cookies = json.loads(decoded)
                    else:
                        cookies = decoded
                except (json.JSONDecodeError, TypeError):
                    # Re-raise original error with more context
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.debug(f"Original value length: {len(original)}")
                    logger.debug(f"Cleaned value (first 500 chars): {cookies_json[:500]}")
                    raise
            
            secure_1psid = cookies.get("__Secure-1PSID")
            secure_1psidts = cookies.get("__Secure-1PSIDTS")
            if secure_1psid:
                return (secure_1psid, secure_1psidts)
            else:
                # JSON exists but missing required cookie
                import logging
                logger = logging.getLogger(__name__)
                logger.warning("WEBAI_COOKIES_JSON found but missing __Secure-1PSID cookie")
                logger.debug(f"Available keys: {list(cookies.keys())}")
        except json.JSONDecodeError as e:
            # JSON parsing failed - try to fix malformed JSON (missing quotes)
            # Format: {__Secure-1PSID: value, __Secure-1PSIDTS: value}
            try:
                fixed = cookies_json.strip()
                if fixed.startswith('{') and fixed.endswith('}'):
                    fixed = fixed[1:-1].strip()
                
                # Parse manually: key: value pairs
                cookies_dict = {}
                pattern = r'(__Secure-1PSID(?:TS)?):\s*([^,}]+?)(?=\s*[,}]|$)'
                matches = re.findall(pattern, fixed)
                
                if matches:
                    for key, value in matches:
                        cookies_dict[key.strip()] = value.strip()
                    
                    if cookies_dict and "__Secure-1PSID" in cookies_dict:
                        secure_1psid = cookies_dict.get("__Secure-1PSID")
                        secure_1psidts = cookies_dict.get("__Secure-1PSIDTS")
                        if secure_1psid:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning("⚠️ WEBAI_COOKIES_JSON contains malformed JSON (missing quotes). Fixed automatically.")
                            logger.warning("⚠️ Please update Woodpecker secret 'webai_cookies_json' to valid JSON format:")
                            logger.warning("   {\"__Secure-1PSID\":\"...\",\"__Secure-1PSIDTS\":\"...\"}")
                            return (secure_1psid, secure_1psidts)
            except Exception:
                pass  # Fall through to original error handling
            
            # JSON parsing failed - log but continue to try other methods
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to parse WEBAI_COOKIES_JSON as JSON: {e}")
            # Log more details for debugging
            raw_value = original[:500] if 'original' in locals() else (cookies_json[:500] if 'cookies_json' in locals() else 'N/A')
            cleaned_value = cookies_json[:500] if 'cookies_json' in locals() else 'N/A'
            logger.debug(f"Raw WEBAI_COOKIES_JSON value (first 500 chars): {raw_value}")
            logger.debug(f"Cleaned value (first 500 chars): {cleaned_value}")
            logger.debug(f"Raw value length: {len(original) if 'original' in locals() else 'N/A'}")
            # Check for common issues
            if 'original' in locals():
                if '\n' in original:
                    logger.debug("⚠️ Raw value contains newlines - this may be the issue")
                if original.count('"') % 2 != 0:
                    logger.debug("⚠️ Raw value has mismatched quotes")
                if original.startswith('"') and original.endswith('"') and len(original) > 2:
                    logger.debug("⚠️ Raw value is wrapped in quotes - may need to be unwrapped")
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error processing WEBAI_COOKIES_JSON: {e}")
            logger.debug(f"Raw WEBAI_COOKIES_JSON value (first 200 chars): {original[:200] if 'original' in locals() else cookies_json[:200]}")
    
    # Option 2: Individual environment variables
    secure_1psid = os.getenv("WEBAI_SECURE_1PSID")
    secure_1psidts = os.getenv("WEBAI_SECURE_1PSIDTS")
    if secure_1psid:
        return (secure_1psid, secure_1psidts)
    
    # Fallback: Try cookie files (for local development and shared volume)
    # Priority: shared volume (from sidecar) > project root > web_dashboard
    cookie_locations = [
        Path("/shared/cookies/webai_cookies.json"),  # Shared volume from sidecar container
        project_root / "webai_cookies.json",
        project_root / "ai_service_cookies.json",
        project_root / "web_dashboard" / "webai_cookies.json",
        project_root / "web_dashboard" / "ai_service_cookies.json",
    ]
    
    for cookie_file in cookie_locations:
        if cookie_file.exists():
            try:
                with open(cookie_file, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
                
                secure_1psid = cookies.get("__Secure-1PSID")
                secure_1psidts = cookies.get("__Secure-1PSIDTS")
                
                if secure_1psid:
                    return (secure_1psid, secure_1psidts)
            except Exception as e:
                continue
    
    return (None, None)


def check_cookie_config() -> dict:
    """
    Debug helper: Check cookie configuration status.
    
    Returns:
        Dictionary with configuration status and details
    """
    status = {
        "env_var_exists": bool(os.getenv("WEBAI_COOKIES_JSON")),
        "env_var_length": len(os.getenv("WEBAI_COOKIES_JSON", "")),
        "individual_vars": {
            "WEBAI_SECURE_1PSID": bool(os.getenv("WEBAI_SECURE_1PSID")),
            "WEBAI_SECURE_1PSIDTS": bool(os.getenv("WEBAI_SECURE_1PSIDTS"))
        },
        "cookie_files": {}
    }
    
    # Check cookie files
    cookie_names = ["webai_cookies.json", "ai_service_cookies.json"]
    for name in cookie_names:
        root_cookie = project_root / name
        web_cookie = project_root / "web_dashboard" / name
        status["cookie_files"][name] = {
            "root_exists": root_cookie.exists(),
            "web_exists": web_cookie.exists()
        }
    
    # Try to parse WEBAI_COOKIES_JSON if it exists
    cookies_json = os.getenv("WEBAI_COOKIES_JSON")
    if cookies_json:
        try:
            cookies = json.loads(cookies_json)
            status["json_parse_success"] = True
            status["has_secure_1psid"] = "__Secure-1PSID" in cookies
            status["has_secure_1psidts"] = "__Secure-1PSIDTS" in cookies
            status["cookie_keys"] = list(cookies.keys())
        except Exception as e:
            status["json_parse_success"] = False
            status["json_parse_error"] = str(e)
    
    return status


def test_webai_connection(cookies_file: Optional[str] = None) -> dict:
    """
    Test WebAI connection and cookie validity.
    
    Args:
        cookies_file: Optional path to cookie file
        
    Returns:
        Dictionary with test results:
        - success (bool): Whether test passed
        - message (str): Status message
        - details (dict): Additional diagnostic information
    """
    import logging
    logger = logging.getLogger(__name__)
    
    result = {
        "success": False,
        "message": "",
        "details": {}
    }
    
    try:
        # Step 1: Check if cookies are available
        if cookies_file:
            with open(cookies_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            secure_1psid = cookies.get("__Secure-1PSID")
            secure_1psidts = cookies.get("__Secure-1PSIDTS")
        else:
            secure_1psid, secure_1psidts = _load_cookies()
        
        if not secure_1psid:
            result["message"] = "No cookies found"
            result["details"]["error_type"] = "missing_cookies"
            return result
        
        result["details"]["has_1psid"] = True
        result["details"]["has_1psidts"] = bool(secure_1psidts)
        
        # Step 2: Try to initialize client
        logger.info("Testing WebAI connection with simple query...")
        
        async def _test():
            client = WebAIClient(cookies_file=cookies_file, auto_refresh=False)
            try:
                await client._init_client()
                result["details"]["client_init"] = "success"
                
                # Step 3: Send a simple test query
                response = await client.query("Hello")
                
                if response and len(response) > 0:
                    result["success"] = True
                    result["message"] = "Connection test successful"
                    result["details"]["response_received"] = True
                    result["details"]["response_length"] = len(response)
                else:
                    result["message"] = "Client initialized but no response received"
                    result["details"]["response_received"] = False
                
            except Exception as e:
                result["message"] = f"Connection test failed: {str(e)}"
                result["details"]["error"] = str(e)
                result["details"]["error_type"] = type(e).__name__
            finally:
                await client.close()
        
        asyncio.run(_test())
        
    except Exception as e:
        result["message"] = f"Test error: {str(e)}"
        result["details"]["error"] = str(e)
        result["details"]["error_type"] = type(e).__name__
        logger.error(f"WebAI connection test failed: {e}", exc_info=True)
    
    return result



class WebAIClient:
    """
    Wrapper for web-based AI service access using cookie authentication.
    
    Maintains obfuscation layer while using third-party package for communication.
    """
    
    def __init__(self, cookies_file: Optional[str] = None, auto_refresh: bool = False):
        """
        Initialize the WebAI client.
        
        Args:
            cookies_file: Optional path to cookie file (auto-detected if not provided)
            auto_refresh: Whether to automatically refresh cookies (default: False)
                         Note: Enabling this may cause browser sessions to be invalidated
        """
        if not HAS_WEBAPI_PACKAGE:
            raise ImportError(
                "Required package not installed. Install with: pip install gemini-webapi  # Package name required for installation"
            )
        
        self.cookies_file = cookies_file
        self.auto_refresh = auto_refresh
        self._client: Optional[WebAPIClient] = None
        self._chat_session = None  # For conversation continuity
        self._initialized = False
    
    async def _init_client(self) -> None:
        """Initialize the web AI client with cookies (single attempt, fresh load)."""
        if self._initialized:
            return
        
        import logging
        logger = logging.getLogger(__name__)
        
        # Load cookies fresh from disk (in case they were recently refreshed)
        if self.cookies_file:
            # Load from specified file
            with open(self.cookies_file, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            secure_1psid = cookies.get("__Secure-1PSID")
            secure_1psidts = cookies.get("__Secure-1PSIDTS")
        else:
            # Auto-detect cookie file (loads from disk for freshness)
            secure_1psid, secure_1psidts = _load_cookies()
        
        if not secure_1psid:
            # Check if environment variable exists but wasn't parsed correctly
            env_check = ""
            cookies_json_env = os.getenv("WEBAI_COOKIES_JSON")
            if cookies_json_env:
                env_check = "\n\n💡 Note: WEBAI_COOKIES_JSON environment variable is set, but cookies couldn't be loaded.\n"
                env_check += "   This might indicate:\n"
                env_check += "   - JSON format is invalid (check for newlines, extra quotes, or escaping issues)\n"
                env_check += "   - Missing __Secure-1PSID in the JSON\n"
                env_check += "   - Woodpecker secret 'webai_cookies_json' should be a single-line JSON string:\n"
                env_check += "     {\"__Secure-1PSID\":\"...\",\"__Secure-1PSIDTS\":\"...\"}\n"
                env_check += "   - Avoid newlines in the secret value - use a single line\n"
                env_check += "   - If using quotes, ensure they're properly escaped\n"
            
            raise ValueError(
                "No cookies found. Please extract cookies first:\n"
                "  python web_dashboard/extract_ai_cookies.py --browser manual\n\n"
                "Or configure via environment variable:\n"
                "  - WEBAI_COOKIES_JSON (JSON string from Woodpecker secret 'webai_cookies_json')\n"
                "    Format: {\"__Secure-1PSID\":\"...\",\"__Secure-1PSIDTS\":\"...\"} (single line, no newlines)\n"
                "  - Or WEBAI_SECURE_1PSID + WEBAI_SECURE_1PSIDTS (individual cookies)" + env_check
            )
        
        # Initialize client with cookies
        # Note: secure_1psidts is optional but recommended for better stability
        if secure_1psidts:
            self._client = WebAPIClient(
                secure_1psid=secure_1psid,
                secure_1psidts=secure_1psidts
            )
        else:
            # Try with just __Secure-1PSID (may work but less stable)
            logger.warning("Only __Secure-1PSID found. __Secure-1PSIDTS recommended for better stability.")
            self._client = WebAPIClient(
                secure_1psid=secure_1psid
            )
        
        # Initialize the client (this handles cookie refresh, etc.)
        # Note: auto_refresh=False by default to avoid invalidating browser sessions
        # Single attempt only - no retries to avoid triggering anti-bot detection
        await self._client.init(
            timeout=30,
            auto_close=False,
            close_delay=300,
            auto_refresh=self.auto_refresh  # Configurable - disabled by default
        )
        
        self._initialized = True
    
    async def query(self, prompt: str, continue_conversation: bool = False) -> str:
        """
        Send a query to the AI service.
        
        Args:
            prompt: The query/prompt to send
            continue_conversation: If True, maintains conversation history across queries
            
        Returns:
            Response text
        """
        await self._init_client()
        
        if continue_conversation:
            # Use chat session for conversation continuity
            if self._chat_session is None:
                self._chat_session = self._client.start_chat()
            response = await self._chat_session.send_message(prompt)
        else:
            # Single query without conversation history
            response = await self._client.generate_content(prompt)
        
        return response.text
    
    def start_chat(self):
        """
        Start a new chat session for conversation continuity.
        Returns a chat session object that maintains conversation history.
        
        Usage:
            client = WebAIClient()
            chat = await client.start_chat()
            response1 = await chat.send_message("Hello")
            response2 = await chat.send_message("What did I just say?")  # Remembers previous message
        """
        async def _start():
            await self._init_client()
            if self._chat_session is None:
                self._chat_session = self._client.start_chat()
            return self._chat_session
        
        return asyncio.run(_start())
    
    def reset_chat(self):
        """Reset the conversation history by starting a new chat session."""
        self._chat_session = None
    
    async def close(self) -> None:
        """Close the client and cleanup."""
        self._chat_session = None
        if self._client:
            await self._client.close()
            self._initialized = False


# Synchronous wrapper for easier use
def query_webai(prompt: str, cookies_file: Optional[str] = None, auto_refresh: bool = False, 
                 continue_conversation: bool = False) -> str:
    """
    Synchronous wrapper for querying the AI service.
    
    Args:
        prompt: The query/prompt to send
        cookies_file: Optional path to cookie file
        auto_refresh: Whether to automatically refresh cookies (default: False)
                     Note: Enabling this may cause browser sessions to be invalidated
        continue_conversation: If True, maintains conversation history (default: False)
        
    Returns:
        Response text
    """
    async def _query():
        client = WebAIClient(cookies_file=cookies_file, auto_refresh=auto_refresh)
        try:
            return await client.query(prompt, continue_conversation=continue_conversation)
        finally:
            await client.close()
    
    return asyncio.run(_query())


# Conversation helper class for maintaining chat sessions
class ConversationSession:
    """
    Helper class for maintaining conversation continuity across multiple queries.
    
    Usage:
        session = ConversationSession()
        response1 = session.send("Hello")
        response2 = session.send("What did I just say?")  # Remembers context
        session.reset()  # Start fresh conversation
        session.close()  # Clean up
    """
    
    def __init__(self, cookies_file: Optional[str] = None, auto_refresh: bool = False):
        self._client = WebAIClient(cookies_file=cookies_file, auto_refresh=auto_refresh)
        self._chat_session = None
        self._initialized = False
        self._loop = None
    
    def _get_loop(self):
        """Get or create event loop for this session."""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop
    
    async def _ensure_chat(self):
        """Ensure chat session is initialized."""
        if not self._initialized:
            await self._client._init_client()
            self._chat_session = self._client._client.start_chat()
            self._initialized = True
    
    async def send(self, prompt: str) -> str:
        """
        Send a message in the conversation.
        
        Args:
            prompt: The message to send
            
        Returns:
            Response text
        """
        await self._ensure_chat()
        response = await self._chat_session.send_message(prompt)
        return response.text
    
    def send_sync(self, prompt: str) -> str:
        """Synchronous version of send()."""
        loop = self._get_loop()
        if loop.is_running():
            # If loop is already running, we need to use a different approach
            import nest_asyncio
            nest_asyncio.apply()
            return asyncio.run(self.send(prompt))
        else:
            return loop.run_until_complete(self.send(prompt))
    
    async def reset(self):
        """Reset the conversation and start fresh."""
        self._chat_session = None
        self._initialized = False
    
    def reset_sync(self):
        """Synchronous version of reset()."""
        loop = self._get_loop()
        if not loop.is_running():
            loop.run_until_complete(self.reset())
    
    async def close(self):
        """Close the session."""
        self._chat_session = None
        self._initialized = False
        await self._client.close()
        # Don't close the loop - it may be shared or still running
        self._loop = None
    
    def close_sync(self):
        """Synchronous version of close()."""
        loop = self._get_loop()
        if not loop.is_running():
            loop.run_until_complete(self.close())


# Persistent conversation session for production use
class PersistentConversationSession:
    """
    Production-ready conversation session that persists across restarts.
    
    Saves conversation metadata to disk and automatically restores it.
    Each user gets one persistent conversation identified by user_id.
    
    Usage:
        # First time - creates new session
        session = PersistentConversationSession("user_123")
        response1 = session.send_sync("Hello")
        
        # Later - resumes existing session
        session = PersistentConversationSession("user_123")
        response2 = session.send_sync("What did I say before?")  # Remembers!
    """
    
    def __init__(
        self, 
        session_id: str = "default",
        cookies_file: Optional[str] = None,
        auto_refresh: bool = False,
        storage_dir: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None
    ):
        """
        Initialize persistent conversation session.
        
        Args:
            session_id: Unique identifier for this conversation (used as filename, typically user_id)
            cookies_file: Optional path to cookie file
            auto_refresh: Whether to automatically refresh cookies
            storage_dir: Directory to store session files (default: project_root/data/conversations)
            model: WebAI model to use (e.g., "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3.0-pro")
            system_prompt: Optional system prompt (will create a custom Gem if provided)
        """
        self.session_id = session_id
        self.model = model
        self.system_prompt = system_prompt
        self._client = WebAIClient(cookies_file=cookies_file, auto_refresh=auto_refresh)
        self._chat_session = None
        self._custom_gem = None
        self._initialized = False
        self._loop = None
        
        # Set up storage directory
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = project_root / "data" / "conversations"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_file = self.storage_dir / f"{session_id}.json"
        self._saved_metadata = None
    
    def _get_loop(self):
        """Get or create event loop for this session."""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop
    
    def _load_metadata(self) -> Optional[dict]:
        """Load saved conversation metadata from disk."""
        if self.session_file.exists():
            try:
                with open(self.session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('metadata')
            except Exception as e:
                # Silently fail - will start fresh
                pass
        return None
    
    def _save_metadata(self, metadata: dict):
        """Save conversation metadata to disk."""
        try:
            data = {
                'session_id': self.session_id,
                'metadata': metadata,
                'last_updated': time.time()
            }
            with open(self.session_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self._saved_metadata = metadata
        except Exception as e:
            # Silently fail - conversation continues but won't persist
            pass
    
    async def _ensure_chat(self):
        """Ensure chat session is initialized, loading from saved state if available."""
        if not self._initialized:
            await self._client._init_client()
            
            # Try to load saved metadata
            saved_metadata = self._load_metadata()
            
            # Create custom Gem if system prompt provided
            if self.system_prompt and not self._custom_gem:
                try:
                    # Create a custom gem with the system prompt
                    gem_name = f"Portfolio Assistant {self.session_id[:8]}"
                    self._custom_gem = await self._client._client.create_gem(
                        name=gem_name,
                        prompt=self.system_prompt,
                        description="System prompt for portfolio AI assistant"
                    )
                except Exception as e:
                    # If gem creation fails, continue without it
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f"Failed to create custom gem: {e}")
            
            if saved_metadata:
                # Resume existing conversation
                chat_params = {"metadata": saved_metadata}
                if self.model:
                    chat_params["model"] = self.model
                if self._custom_gem:
                    chat_params["gem"] = self._custom_gem
                self._chat_session = self._client._client.start_chat(**chat_params)
            else:
                # Start new conversation
                chat_params = {}
                if self.model:
                    chat_params["model"] = self.model
                if self._custom_gem:
                    chat_params["gem"] = self._custom_gem
                self._chat_session = self._client._client.start_chat(**chat_params)
            
            self._initialized = True
    
    async def send(self, prompt: str) -> str:
        """
        Send a message in the conversation and auto-save state.
        
        Args:
            prompt: The message to send
            
        Returns:
            Response text
        """
        await self._ensure_chat()
        response = await self._chat_session.send_message(prompt)
        
        # Auto-save conversation metadata after each message
        try:
            if hasattr(self._chat_session, 'metadata'):
                self._save_metadata(self._chat_session.metadata)
        except Exception:
            pass  # Continue even if save fails
        
        return response.text
    
    def send_sync(self, prompt: str) -> str:
        """Synchronous version of send()."""
        loop = self._get_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return asyncio.run(self.send(prompt))
        else:
            return loop.run_until_complete(self.send(prompt))
    
    async def reset(self):
        """Reset the conversation and delete saved state."""
        # Delete custom gem if it exists
        if self._custom_gem:
            try:
                await self._client._init_client()
                await self._client._client.delete_gem(self._custom_gem)
            except Exception:
                pass  # Silently fail
            self._custom_gem = None
        
        self._chat_session = None
        self._initialized = False
        if self.session_file.exists():
            try:
                self.session_file.unlink()
            except Exception:
                pass
    
    def reset_sync(self):
        """Synchronous version of reset()."""
        loop = self._get_loop()
        if not loop.is_running():
            loop.run_until_complete(self.reset())
    
    def get_history(self) -> List[dict]:
        """
        Get conversation history (if available from metadata).
        
        Returns:
            List of message dicts with 'role' and 'content'
        """
        saved_metadata = self._load_metadata()
        if saved_metadata and 'history' in saved_metadata:
            return saved_metadata['history']
        return []
    
    async def close(self):
        """Close the session and save final state."""
        # Save one last time before closing
        if self._chat_session and hasattr(self._chat_session, 'metadata'):
            try:
                self._save_metadata(self._chat_session.metadata)
            except:
                pass
        
        # Clean up custom gem
        if self._custom_gem:
            try:
                await self._client._init_client()
                await self._client._client.delete_gem(self._custom_gem)
            except Exception:
                pass  # Silently fail
            self._custom_gem = None
        
        self._chat_session = None
        self._initialized = False
        await self._client.close()
        self._loop = None
    
    def close_sync(self):
        """Synchronous version of close()."""
        loop = self._get_loop()
        if not loop.is_running():
            loop.run_until_complete(self.close())


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Query WebAI using cookies")
    parser.add_argument(
        "--cookies",
        help="Path to cookie file (auto-detected if not provided)"
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Query to send"
    )
    parser.add_argument(
        "--auto-refresh",
        action="store_true",
        help="Enable automatic cookie refresh (may cause browser logout)"
    )
    
    args = parser.parse_args()
    
    if not HAS_WEBAPI_PACKAGE:
        print("ERROR: Required package not installed")
        print("Install with: pip install gemini-webapi  # Package name required for installation")
        sys.exit(1)
    
    try:
        response = query_webai(
            args.query, 
            cookies_file=args.cookies, 
            auto_refresh=args.auto_refresh
        )
        print("\n" + "=" * 60)
        print("RESPONSE:")
        print("=" * 60)
        print(response)
        print("=" * 60)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
