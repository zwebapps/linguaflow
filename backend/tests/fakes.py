"""Test doubles. Nothing here touches the network.

LangChain ships no tool-calling-capable fake chat model, so we implement one. It's
what lets us assert the agent's SSE event ordering without a live LLM.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable


class FakeToolCallingModel(BaseChatModel):
    """A chat model that can request tool calls, then answer.

    `script` is a list of turns. Each turn is either:
      * ``{"tool_calls": [{"name": ..., "args": {...}}]}`` — request tool(s), or
      * ``{"text": "final answer"}``  — stream a final answer.

    The model walks the script one turn per invocation, mirroring a real
    agent loop (call tool → observe → answer).
    """

    script: list[dict[str, Any]] = []
    _turn: int = 0
    bound_tools: list[Any] = []
    usage: dict[str, int] = {"input_tokens": 41, "output_tokens": 17}

    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        # create_agent calls this; returning self keeps the script in control.
        self.bound_tools = list(tools)
        return self

    def _next_turn(self) -> dict[str, Any]:
        if self._turn >= len(self.script):
            return {"text": ""}
        turn = self.script[self._turn]
        self._turn += 1
        return turn

    def _message_for(self, turn: dict[str, Any]) -> AIMessage:
        if calls := turn.get("tool_calls"):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": c["name"],
                        "args": c.get("args", {}),
                        "id": c.get("id", f"call_{i}"),
                        "type": "tool_call",
                    }
                    for i, c in enumerate(calls)
                ],
                usage_metadata={**self.usage, "total_tokens": sum(self.usage.values())},
            )
        return AIMessage(
            content=turn.get("text", ""),
            usage_metadata={**self.usage, "total_tokens": sum(self.usage.values())},
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        turn = self._next_turn()
        return ChatResult(generations=[ChatGeneration(message=self._message_for(turn))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        turn = self._next_turn()
        return ChatResult(generations=[ChatGeneration(message=self._message_for(turn))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        turn = self._next_turn()
        if turn.get("tool_calls"):
            msg = self._message_for(turn)
            yield ChatGenerationChunk(
                message=AIMessageChunk(content="", tool_calls=msg.tool_calls)
            )
            return
        # Stream word-by-word so token events are observable.
        words = (turn.get("text") or "").split(" ")
        for i, w in enumerate(words):
            yield ChatGenerationChunk(
                message=AIMessageChunk(content=w + (" " if i < len(words) - 1 else ""))
            )
        # Real providers attach usage to the FINAL streamed chunk (OpenAI needs
        # stream_usage=True for this). Mirroring that here is what keeps the
        # cost-accounting path honest under test.
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                usage_metadata={**self.usage, "total_tokens": sum(self.usage.values())},
            )
        )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for chunk in self._stream(messages, stop, None, **kwargs):
            yield chunk
