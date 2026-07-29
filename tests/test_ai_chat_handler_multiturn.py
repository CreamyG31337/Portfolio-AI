"""Unit tests for AI chat multi-turn message assembly and context continuity."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from ai_chat_handler import ChatHandler


class TestNormalizePriorHistory:
    def test_empty_history(self) -> None:
        assert ChatHandler.normalize_prior_history([], "hi") == []
        assert ChatHandler.normalize_prior_history(None, "hi") == []

    def test_keeps_prior_turns(self) -> None:
        history = [
            {"role": "user", "content": "about AMD"},
            {"role": "assistant", "content": "AMD looks fine"},
        ]
        assert ChatHandler.normalize_prior_history(history, "about MCHP") == history

    def test_drops_trailing_user_matching_current_query(self) -> None:
        history = [
            {"role": "user", "content": "about AMD"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "about MCHP"},
        ]
        prior = ChatHandler.normalize_prior_history(history, "about MCHP")
        assert prior == [
            {"role": "user", "content": "about AMD"},
            {"role": "assistant", "content": "ok"},
        ]

    def test_accepts_text_key_alias(self) -> None:
        history = [{"role": "user", "text": "hello"}]
        assert ChatHandler.normalize_prior_history(history) == [
            {"role": "user", "content": "hello"}
        ]


class TestBuildLlmMessages:
    def test_system_prior_and_current_full_prompt(self) -> None:
        history = [
            {"role": "user", "content": "about AMD"},
            {"role": "assistant", "content": "AMD analysis"},
        ]
        full_prompt = "PORTFOLIO_HOLDINGS: AMD, MCHP\n\nabout MCHP"
        messages = ChatHandler.build_llm_messages(
            "sys",
            full_prompt,
            history,
            current_query="about MCHP",
        )
        assert messages[0] == {"role": "system", "content": "sys"}
        assert messages[1]["content"] == "about AMD"
        assert messages[2]["content"] == "AMD analysis"
        assert messages[-1] == {"role": "user", "content": full_prompt}
        assert "MCHP" in messages[-1]["content"]
        # Current query not duplicated as a bare prior user turn
        user_contents = [m["content"] for m in messages if m["role"] == "user"]
        assert user_contents.count("about MCHP") == 0

    def test_dedupes_legacy_history_that_includes_current_turn(self) -> None:
        history = [
            {"role": "user", "content": "about AMD"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "about MCHP"},
        ]
        full_prompt = "HOLDINGS\n\nabout MCHP"
        messages = ChatHandler.build_llm_messages(
            "sys", full_prompt, history, current_query="about MCHP"
        )
        assert [m["role"] for m in messages] == [
            "system",
            "user",
            "assistant",
            "user",
        ]
        assert messages[1]["content"] == "about AMD"
        assert messages[-1]["content"] == full_prompt


class TestWebAiContextInjection:
    def _make_webai_handler(self) -> ChatHandler:
        handler = ChatHandler(user_id="user-1", model="llama3.2:3b")
        handler.backend = "webai"
        return handler

    def test_first_turn_includes_portfolio_context(self) -> None:
        handler = self._make_webai_handler()
        captured: Dict[str, Any] = {}

        def _capture(full_prompt: str, system_prompt: str) -> Any:
            captured["full_prompt"] = full_prompt
            return MagicMock(status_code=200)

        with patch.object(handler, "_handle_webai", side_effect=_capture), patch(
            "ai_prompts.get_system_prompt", return_value="sys"
        ), patch(
            "prompt_safety.prepare_untrusted_for_prompt",
            side_effect=lambda text, **kwargs: text,
        ):
            handler.handle_chat(
                query="about AMD",
                context_string="PORTFOLIO_MARKER: AMD MCHP",
                conversation_history=[],
            )

        assert "PORTFOLIO_MARKER" in captured["full_prompt"]
        assert "about AMD" in captured["full_prompt"]

    def test_follow_up_omits_portfolio_context(self) -> None:
        """Client sends empty context_string on follow-ups; server must not invent it."""
        handler = self._make_webai_handler()
        captured: Dict[str, Any] = {}

        def _capture(full_prompt: str, system_prompt: str) -> Any:
            captured["full_prompt"] = full_prompt
            return MagicMock(status_code=200)

        prior = [
            {"role": "user", "content": "PORTFOLIO_MARKER: AMD MCHP\n\nabout AMD"},
            {"role": "assistant", "content": "AMD looks fine"},
        ]
        with patch.object(handler, "_handle_webai", side_effect=_capture), patch(
            "ai_prompts.get_system_prompt", return_value="sys"
        ), patch(
            "prompt_safety.prepare_untrusted_for_prompt",
            side_effect=lambda text, **kwargs: text,
        ):
            handler.handle_chat(
                query="about MCHP",
                context_string="",
                conversation_history=prior,
            )

        assert "PORTFOLIO_MARKER" not in captured["full_prompt"]
        assert captured["full_prompt"] == "about MCHP"

    def test_follow_up_with_stale_context_string_still_injects_when_provided(
        self,
    ) -> None:
        """If the client re-injects (history window dropped the anchor), honor it."""
        handler = self._make_webai_handler()
        captured: Dict[str, Any] = {}

        def _capture(full_prompt: str, system_prompt: str) -> Any:
            captured["full_prompt"] = full_prompt
            return MagicMock(status_code=200)

        prior = [
            {"role": "user", "content": "old q"},
            {"role": "assistant", "content": "old a"},
        ]
        with patch.object(handler, "_handle_webai", side_effect=_capture), patch(
            "ai_prompts.get_system_prompt", return_value="sys"
        ), patch(
            "prompt_safety.prepare_untrusted_for_prompt",
            side_effect=lambda text, **kwargs: text,
        ):
            handler.handle_chat(
                query="about MCHP",
                context_string="PORTFOLIO_MARKER: AMD MCHP",
                conversation_history=prior,
            )

        assert "PORTFOLIO_MARKER" in captured["full_prompt"]
        assert "about MCHP" in captured["full_prompt"]


class TestOllamaMultiturn:
    def test_query_ollama_chat_receives_prior_history(self, app: Any) -> None:
        handler = ChatHandler(user_id="user-1", model="llama3.2:3b")
        assert handler.backend == "ollama"

        mock_client = MagicMock()
        mock_client.query_ollama_chat.return_value = iter(["ok"])

        history = [
            {"role": "user", "content": "about AMD"},
            {"role": "assistant", "content": "AMD analysis"},
        ]
        full_prompt = "PORTFOLIO: MCHP\n\nabout MCHP"

        with app.test_request_context("/api/v2/ai/chat", method="POST"):
            with patch("ollama_client.get_ollama_client", return_value=mock_client):
                response = handler._handle_ollama_stream(
                    full_prompt,
                    "sys",
                    history,
                    current_query="about MCHP",
                )
                # Drive the streaming generator so query_ollama_chat is invoked
                body = "".join(response.response)

        mock_client.query_ollama_chat.assert_called_once()
        call_kwargs = mock_client.query_ollama_chat.call_args.kwargs
        messages: List[Dict[str, str]] = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "about AMD"
        assert messages[2]["content"] == "AMD analysis"
        assert messages[-1]["content"] == full_prompt
        assert "ok" in body


class TestGlmMultiturnContext:
    def test_follow_up_relies_on_history_anchor_not_current_prompt(
        self,
    ) -> None:
        """After first turn, holdings live on the prior user turn; current prompt is bare query."""
        history = [
            {
                "role": "user",
                "content": "Holdings include AMD and MCHP\n\nTell me about AMD",
            },
            {"role": "assistant", "content": "AMD is in the portfolio"},
        ]
        query = "What about MCHP?"
        full_prompt = query  # no re-attached holdings
        messages = ChatHandler.build_llm_messages(
            "sys", full_prompt, history, current_query=query
        )
        assert messages[-1]["content"] == query
        assert "Holdings include" in messages[1]["content"]
        assert "MCHP" in messages[1]["content"]
        user_contents = [m["content"] for m in messages if m["role"] == "user"]
        assert user_contents.count(query) == 1
