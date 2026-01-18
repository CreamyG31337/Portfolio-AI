#!/usr/bin/env python3
"""
AI Chat Handler
================

Orchestrates AI chat across multiple backends (WebAI, GLM, Ollama).
Handles model detection, context building, and response streaming.
"""

import logging
from typing import Optional, Dict, Any, List, Generator
from flask import Response, stream_with_context
import json

logger = logging.getLogger(__name__)


class ChatHandler:
    """Orchestrates AI chat across multiple backends (WebAI, GLM, Ollama)"""
    
    def __init__(self, user_id: str, model: str, fund: Optional[str] = None):
        """
        Initialize ChatHandler.
        
        Args:
            user_id: User ID for session management
            model: Model name (e.g., 'gemini-2.0-flash-exp', 'llama3.2:3b', 'glm-4-plus')
            fund: Optional fund name for context building
        """
        self.user_id = user_id
        self.model = model
        self.fund = fund
        self.backend = self._detect_backend()
        
    def _detect_backend(self) -> str:
        """
        Detect which AI backend to use based on model name.
        
        Returns:
            Backend name: 'webai', 'glm', or 'ollama'
        """
        if not self.model:
            return 'ollama'  # Default
            
        # Check for WebAI models
        try:
            from webai_wrapper import is_webai_model
            if is_webai_model(self.model):
                return 'webai'
        except ImportError:
            pass
        
        # Check for GLM models
        if self.model.startswith('glm-'):
            return 'glm'
        
        # Default to Ollama
        return 'ollama'
    
    def build_context(
        self,
        context_items: List[Dict[str, Any]],
        options: Dict[str, Any]
    ) -> str:
        """
        Build context string from portfolio data.
        
        Args:
            context_items: List of context item dictionaries
            options: Options dict with include_price_volume, include_fundamentals, etc.
            
        Returns:
            Formatted context string
        """
        from ai_context_builder import (
            format_holdings, format_thesis, format_trades,
            format_performance_metrics, format_cash_balances
        )
        from flask_data_utils import (
            get_current_positions_flask, get_trade_log_flask,
            get_cash_balances_flask, calculate_portfolio_value_over_time_flask,
            get_fund_thesis_data_flask, calculate_performance_metrics_flask
        )
        from chat_context import ContextItemType
        
        context_parts = []
        
        for item_dict in context_items:
            item_type_str = item_dict['item_type']
            item_fund = item_dict.get('fund') or self.fund
            
            try:
                item_type = ContextItemType(item_type_str)
            except ValueError:
                continue
            
            try:
                if item_type == ContextItemType.HOLDINGS:
                    positions_df = get_current_positions_flask(item_fund)
                    trades_df = get_trade_log_flask(limit=1000, fund=item_fund) if item_fund else None
                    include_pv = options.get('include_price_volume', True)
                    include_fund = options.get('include_fundamentals', True)
                    context_parts.append(
                        format_holdings(
                            positions_df,
                            item_fund or "Unknown",
                            trades_df=trades_df,
                            include_price_volume=include_pv,
                            include_fundamentals=include_fund
                        )
                    )
                elif item_type == ContextItemType.THESIS:
                    thesis_data = get_fund_thesis_data_flask(item_fund or "")
                    if thesis_data:
                        context_parts.append(format_thesis(thesis_data))
                elif item_type == ContextItemType.TRADES:
                    limit = item_dict.get('metadata', {}).get('limit', 100)
                    trades_df = get_trade_log_flask(limit=limit, fund=item_fund)
                    context_parts.append(format_trades(trades_df, limit))
                elif item_type == ContextItemType.METRICS:
                    portfolio_df = calculate_portfolio_value_over_time_flask(item_fund, days=365) if item_fund else None
                    metrics = calculate_performance_metrics_flask(item_fund) if item_fund else {}
                    context_parts.append(format_performance_metrics(metrics, portfolio_df))
                elif item_type == ContextItemType.CASH_BALANCES:
                    cash = get_cash_balances_flask(item_fund) if item_fund else {}
                    context_parts.append(format_cash_balances(cash))
            except Exception as e:
                logger.warning(f"Error loading {item_type_str}: {e}")
                continue
        
        return "\n\n---\n\n".join(context_parts) if context_parts else ""
    
    def handle_chat(
        self,
        query: str,
        context_string: str,
        conversation_history: List[Dict[str, str]],
        search_results: Optional[Dict[str, Any]] = None,
        repository_articles: Optional[List[Dict[str, Any]]] = None
    ) -> Response:
        """
        Route chat request to appropriate backend and return response.
        
        Args:
            query: User query
            context_string: Pre-built context string
            conversation_history: List of previous messages
            search_results: Optional search results to include
            repository_articles: Optional repository articles to include
            
        Returns:
            Flask Response (streaming or JSON)
        """
        from ai_prompts import get_system_prompt
        from research_utils import escape_markdown
        
        # Build full prompt with context
        full_prompt = query
        if context_string:
            full_prompt = f"{context_string}\n\n{query}"
        
        # Add search results if provided
        if search_results and search_results.get('formatted'):
            if context_string:
                full_prompt = f"{context_string}\n\n---\n\n{search_results['formatted']}\n\n{query}"
            else:
                full_prompt = f"{search_results['formatted']}\n\n{query}"
        
        # Add repository articles if provided
        if repository_articles:
            articles_text = "## Relevant Research from Repository:\n\n"
            for i, article in enumerate(repository_articles, 1):
                similarity = article.get('similarity', 0)
                title = article.get('title', 'Untitled')
                summary = escape_markdown(article.get('summary', article.get('content', '')[:300]))
                source = article.get('source', 'Unknown')
                published = article.get('published_at', '')
                
                articles_text += f"### Article {i} (Similarity: {similarity:.2%})\n"
                articles_text += f"**{title}**\n"
                articles_text += f"*Source: {source}"
                if published:
                    articles_text += f" | Published: {published}"
                articles_text += "*\n\n"
                if summary:
                    articles_text += f"{summary}\n\n"
                articles_text += "---\n\n"
            
            if context_string or (search_results and search_results.get('formatted')):
                full_prompt = f"{full_prompt}\n\n{articles_text}"
            else:
                full_prompt = f"{articles_text}\n\n{query}"
        
        # Get model-specific system prompt
        system_prompt = get_system_prompt(self.model)
        
        # Route to appropriate backend
        if self.backend == 'webai':
            return self._handle_webai(full_prompt, system_prompt)
        elif self.backend == 'glm':
            return self._handle_glm_stream(full_prompt, system_prompt, conversation_history)
        else:  # ollama
            return self._handle_ollama_stream(full_prompt, system_prompt)
    
    def _handle_webai(self, full_prompt: str, system_prompt: str) -> Response:
        """
        Handle WebAI (non-streaming) response.
        
        Args:
            full_prompt: Full prompt with context
            system_prompt: System prompt
            
        Returns:
            JSON response
        """
        from flask import jsonify
        from webai_wrapper import PersistentConversationSession
        import os
        
        try:
            # Use cookie file from shared location
            cookie_file = "/shared/cookies/webai_cookies.json"
            if not os.path.exists(cookie_file):
                cookie_file = None
                logger.warning("Cookie file not found at /shared/cookies/webai_cookies.json, using default")
            else:
                logger.info(f"Using cookie file: {cookie_file}")
            
            # Create session with system prompt (creates versioned Gem)
            logger.info(f"Creating WebAI session for model: {self.model}")
            webai_session = PersistentConversationSession(
                session_id=self.user_id,
                cookies_file=cookie_file,
                auto_refresh=False,
                model=self.model,
                system_prompt=system_prompt
            )
            
            # Send message
            logger.info("Sending message to WebAI...")
            full_response = webai_session.send_sync(full_prompt)
            logger.info(f"WebAI response received, length: {len(full_response) if full_response else 0}")
            
            return jsonify({
                "response": full_response,
                "model": self.model,
                "streaming": False
            })
        
        except Exception as e:
            logger.error(f"WebAI error: {e}", exc_info=True)
            return jsonify({"error": f"WebAI error: {str(e)}"}), 500
    
    def _handle_glm_stream(
        self,
        full_prompt: str,
        system_prompt: str,
        conversation_history: List[Dict[str, str]]
    ) -> Response:
        """
        Handle GLM streaming response via SSE.
        
        Args:
            full_prompt: Full prompt with context
            system_prompt: System prompt
            conversation_history: Previous messages
            
        Returns:
            Streaming SSE response
        """
        from flask import jsonify
        from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL
        from pathlib import Path
        import requests
        
        try:
            key = get_zhipu_api_key()
            if not key:
                return jsonify({"error": "GLM API key not set. Add ZHIPU_API_KEY or save via AI Settings."}), 503
            
            # Load model config for settings
            cfg_path = Path(__file__).resolve().parent / "model_config.json"
            me = {}
            if cfg_path.exists():
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        mc = json.load(f)
                    me = (mc.get("models") or {}).get(self.model, mc.get("default_config") or {})
                except Exception:
                    pass
            
            max_tokens = me.get("max_tokens") or me.get("num_predict") or 4096
            temperature = float(me.get("temperature", 0.1))
            
            # Build messages array
            messages = [{"role": "system", "content": system_prompt}]
            for h in (conversation_history or []):
                role = (h.get("role") or "user").lower()
                if role == "assistant":
                    role = "assistant"
                elif role != "system":
                    role = "user"
                content = h.get("content") or h.get("text") or ""
                if content:
                    messages.append({"role": role, "content": content})
            messages.append({"role": "user", "content": full_prompt})
            
            url = f"{ZHIPU_BASE_URL.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            
            def generate_glm():
                try:
                    r = requests.post(url, json=payload, headers=headers, stream=True, timeout=90)
                    r.raise_for_status()
                    for line in r.iter_lines(decode_unicode=True):
                        if not line or not line.strip():
                            continue
                        s = line.strip()
                        if s.startswith("data: "):
                            data = s[6:].strip()
                            if data == "[DONE]":
                                yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
                                return
                            try:
                                obj = json.loads(data)
                                for c in (obj.get("choices") or [])[:1]:
                                    delta = c.get("delta") or {}
                                    part = delta.get("content") or ""
                                    if part:
                                        yield f"data: {json.dumps({'chunk': part, 'done': False})}\n\n"
                                    if c.get("finish_reason") == "stop":
                                        yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
                                        return
                            except json.JSONDecodeError:
                                continue
                    yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
                except Exception as e:
                    logger.error(f"GLM streaming error: {e}", exc_info=True)
                    yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"
            
            return Response(
                stream_with_context(generate_glm()),
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        
        except ImportError as e:
            logger.error(f"GLM import error: {e}", exc_info=True)
            return jsonify({"error": "glm_config not available"}), 500
        except Exception as e:
            logger.error(f"GLM error: {e}", exc_info=True)
            return jsonify({"error": str(e)}), 500
    
    def _handle_ollama_stream(self, full_prompt: str, system_prompt: str) -> Response:
        """
        Handle Ollama streaming response via SSE.
        
        Args:
            full_prompt: Full prompt with context
            system_prompt: System prompt
            
        Returns:
            Streaming SSE response
        """
        from flask import jsonify
        from ollama_client import get_ollama_client
        
        client = get_ollama_client()
        if not client:
            return jsonify({"error": "Ollama client not available"}), 503
        
        def generate():
            """Generator for streaming response"""
            try:
                for chunk in client.query_ollama(
                    prompt=full_prompt,
                    model=self.model or "granite3.2:8b",
                    stream=True,
                    temperature=None,
                    max_tokens=None,
                    system_prompt=system_prompt
                ):
                    yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"
                
                # Send done signal
                yield f"data: {json.dumps({'chunk': '', 'done': True})}\n\n"
            
            except Exception as e:
                logger.error(f"Streaming error: {e}", exc_info=True)
                error_msg = json.dumps({'error': str(e), 'done': True})
                yield f"data: {error_msg}\n\n"
        
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no'
            }
        )
