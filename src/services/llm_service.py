import os
import asyncio
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from src.utils.circuit_breaker import CircuitBreaker
from src.logger import get_logger

log = get_logger(__name__)
load_dotenv()

LLM_TIMEOUT = 30  # seconds


class LLMProvider:
    """Wraps a single LLM API endpoint with circuit breaker."""

    def __init__(self, name, client, model, breaker=None):
        self.name = name
        self.client = client
        self.model = model
        self.breaker = breaker or CircuitBreaker(name=name)

    async def create(self, messages, tools=None, tool_choice="auto", temperature=0.7, stream=False):
        if self.breaker.is_open:
            raise ConnectionError(f"{self.name} circuit is open")

        kwargs = dict(
            messages=messages,
            model=self.model,
            temperature=temperature,
            stream=stream,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self.client.chat.completions.create, **kwargs),
                timeout=LLM_TIMEOUT
            )
            self.breaker.record_success()
            return result
        except Exception as e:
            self.breaker.record_failure()
            log.warning(f"[{self.name}] failed: {e}")
            raise


class FallbackLLM:
    """Tries LLM providers in order. Returns first successful response."""

    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers

    async def create(self, messages, tools=None, tool_choice="auto", temperature=0.7, stream=False):
        last_error = None
        for provider in self.providers:
            if provider.breaker.is_open:
                log.info(f"Skipping {provider.name} (circuit open)")
                continue
            try:
                result = await provider.create(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    stream=stream,
                )
                if provider != self.providers[0]:
                    log.info(f"Fell back to {provider.name}")
                return result
            except Exception as e:
                last_error = e
                continue

        raise last_error or RuntimeError("All LLM providers failed")


# ─── Build the fallback chain ────────────────────────────────────────────────

_groq_client = Groq(api_key=os.getenv("API_KEY"))
_groq_model = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

_providers = [LLMProvider("groq", _groq_client, _groq_model)]

# Add OpenRouter fallback chain if key is configured.
# Multiple models supported via OPENROUTER_MODELS (comma-separated). Each gets
# its own LLMProvider entry so a single bad model trips its own circuit
# breaker without taking out the rest of the chain.
# Backward compat: if only OPENROUTER_MODEL (singular) is set, use that.
_openrouter_key = os.getenv("OPENROUTER_API_KEY")
if _openrouter_key:
    _openrouter_client = OpenAI(
        api_key=_openrouter_key,
        base_url="https://openrouter.ai/api/v1"
    )
    _or_models_env = os.getenv("OPENROUTER_MODELS") or os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    _or_models = [m.strip() for m in _or_models_env.split(",") if m.strip()]
    for _m in _or_models:
        _providers.append(LLMProvider(f"openrouter:{_m}", _openrouter_client, _m))
    log.info(f"OpenRouter fallback chain configured ({len(_or_models)} model(s)): {_or_models}")
else:
    log.warning("No OPENROUTER_API_KEY set — running without fallback")

# Also add a Groq summary client (cheap model for history compaction)
summary_client = Groq(api_key=os.getenv("API_KEY"))
SUMMARY_MODEL = "llama-3.1-8b-instant"

llm = FallbackLLM(_providers)
