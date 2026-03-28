import os
import time
import asyncio
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
from src.logger import get_logger

log = get_logger(__name__)
load_dotenv()

LLM_TIMEOUT = 30  # seconds


class CircuitBreaker:
    """Simple circuit breaker: opens after `threshold` consecutive failures."""

    def __init__(self, threshold=3, recovery_time=60):
        self.threshold = threshold
        self.recovery_time = recovery_time
        self.failures = 0
        self.opened_at = None

    @property
    def is_open(self):
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at > self.recovery_time:
            # Half-open: allow one probe
            return False
        return True

    def record_success(self):
        self.failures = 0
        self.opened_at = None

    def record_failure(self):
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.time()
            log.warning(f"Circuit breaker opened after {self.failures} failures")


class LLMProvider:
    """Wraps a single LLM API endpoint with circuit breaker."""

    def __init__(self, name, client, model, breaker=None):
        self.name = name
        self.client = client
        self.model = model
        self.breaker = breaker or CircuitBreaker()

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

# Add OpenRouter fallback if key is configured
_openrouter_key = os.getenv("OPENROUTER_API_KEY")
if _openrouter_key:
    _openrouter_client = OpenAI(
        api_key=_openrouter_key,
        base_url="https://openrouter.ai/api/v1"
    )
    _openrouter_model = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    _providers.append(LLMProvider("openrouter", _openrouter_client, _openrouter_model))
    log.info(f"OpenRouter fallback configured with model: {_openrouter_model}")
else:
    log.warning("No OPENROUTER_API_KEY set — running without fallback")

# Also add a Groq summary client (cheap model for history compaction)
summary_client = Groq(api_key=os.getenv("API_KEY"))
SUMMARY_MODEL = "llama-3.1-8b-instant"

llm = FallbackLLM(_providers)
