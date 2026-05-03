from typing import Literal, Protocol, TypedDict


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMProvider(Protocol):
    """All providers expose the same chat interface used by Agents.

    Implementation contract:
    - Native API errors are translated to LLMError or LLMTimeoutError.
    - chat() is async and returns the assistant's text response.
    - messages format is OpenAI-compatible.
    - Providers MUST handle provider-specific request shapes internally.
    - Gateway and Agent code does not see provider-specific shapes.

    The `model` kwarg is provider-specific. If passed, it overrides the
    provider's default model. Cross-provider model names won't match - passing
    model="gpt-4o-mini" to DeepSeekProvider will fail at the provider's API.
    Callers passing `model` are coupling to a specific provider.
    """

    name: str

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
    ) -> str: ...
