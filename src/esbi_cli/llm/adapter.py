"""Provider-agnostic structured-output LLM access.

One method, `complete_json`, returns raw JSON text constrained to a schema. Providers:
  ollama/<model>     native Ollama API (lets us set the context window)
  openai/<model>     any OpenAI-compatible endpoint (OpenAI, LM Studio, OpenRouter): set base_url
  anthropic/<model>  Anthropic Messages API (forced tool call)
  lmstudio/<model>   a local LM Studio server (OpenAI protocol, no key; base_url if not on port 1234)
  claude-cli/<model> the official `claude -p`, paid by a Claude Pro/Max subscription (model `default` = the account's)
"""

import base64
import json
import os
import subprocess
import tempfile
from dataclasses import replace
from typing import Protocol
from urllib.parse import urlparse

import httpx

from esbi_cli.config import LLMConfig


class LLMError(RuntimeError):
    pass


class LLMTimeout(LLMError):
    """The model answered too slowly (a small model looping on one input): a problem with that
    input, not proof that the model is down, so callers fail the input and go on."""


class LLM(Protocol):
    tokens_used: int  # cumulative input+output tokens reported by the provider

    def complete_json(self, *, system: str, user: str, schema: dict) -> str: ...


class ClaudeCliLLM:
    """The official `claude -p`, so a Claude Pro/Max subscription pays for the call.

    The worker never touches the login: it only runs the tool, which holds it. Everything beyond
    the prompt is switched off (tools, settings, plugins, MCP servers): measured, a call otherwise
    carries ~450,000 tokens of the user's own setup, which a nightly run would burn in minutes.
    The subscription's usage window still applies: when it is spent the tool says so, and the run
    stops like any other LLM outage and resumes next time."""

    sends_text_out = True

    def __init__(self, name: str, cfg: LLMConfig):
        self.name, self.cfg = name, cfg
        self.tokens_used = 0

    def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        cmd = [
            "claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
            "--system-prompt", system, "--tools", "", "--setting-sources", "",
            "--no-session-persistence", "--disable-slash-commands",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        ]  # fmt: skip
        if self.name != "default":
            cmd += ["--model", self.name]
        try:
            with tempfile.TemporaryDirectory() as workdir:  # no project files for it to wander into
                done = subprocess.run(
                    cmd, input=user, capture_output=True, text=True, timeout=self.cfg.timeout_seconds,
                    cwd=workdir,
                )  # fmt: skip
        except FileNotFoundError:
            raise LLMError(
                "The `claude` command is not installed (see https://claude.com/code)"
            ) from None
        except subprocess.TimeoutExpired:
            raise LLMTimeout(
                f"claude gave no answer within {self.cfg.timeout_seconds:g}s"
            ) from None
        try:
            data = json.loads(done.stdout)
        except ValueError:
            raise LLMError(
                f"claude returned no JSON (exit {done.returncode}): {done.stderr[:200]}"
            ) from None
        usage = data.get("usage", {})
        self.tokens_used += sum(
            usage.get(k, 0)
            for k in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
                "output_tokens",
            )
        )
        if data.get("is_error"):
            reason = str(data.get("result", "")).strip()
            if "authenticate" in reason.lower() or "oauth" in reason.lower():
                reason += " Run `claude auth login`."
            raise LLMError(f"claude: {reason}")
        if data.get("structured_output") is not None:
            return json.dumps(data["structured_output"])
        return str(data.get("result", ""))


class FallbackLLM:
    """The primary model, and a second one for when the primary cannot be reached (a spent
    subscription window, a lost login, a server down). A timeout is not that: it says something
    about this input, so it still fails the input instead of silently changing model."""

    def __init__(self, primary: LLM, fallback: LLM):
        self.primary, self.fallback = primary, fallback

    @property
    def tokens_used(self) -> int:
        return self.primary.tokens_used + self.fallback.tokens_used

    @property
    def sends_text_out(self) -> bool:
        # either may be shown the text: the fallback takes over when the primary cannot be reached
        return bool(
            getattr(self.primary, "sends_text_out", False)
            or getattr(self.fallback, "sends_text_out", False)
        )

    def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        try:
            return self.primary.complete_json(system=system, user=user, schema=schema)
        except LLMTimeout:
            raise
        except LLMError:
            return self.fallback.complete_json(system=system, user=user, schema=schema)


def make_llm(cfg: LLMConfig) -> LLM:
    if cfg.fallback:
        return FallbackLLM(
            make_llm(replace(cfg, fallback=None)),
            make_llm(replace(cfg, model=cfg.fallback, fallback=None)),
        )
    provider, _, name = cfg.model.partition("/")
    if not name:
        raise ValueError(f"Model must look like '<provider>/<name>', got {cfg.model!r}")
    backends = {
        "ollama": OllamaLLM,
        "openai": OpenAILLM,
        "anthropic": AnthropicLLM,
        "claude-cli": ClaudeCliLLM,
        "lmstudio": LMStudioLLM,
    }
    if provider not in backends:
        raise ValueError(f"Unknown LLM provider {provider!r}; use one of {sorted(backends)}")
    return backends[provider](name, cfg)


OCR_PROMPT = (
    "Transcribe all the text in this image exactly as written, in reading order. "
    "Output only the text, nothing else. If there is no text, output nothing."
)
OCR_MAX_TOKENS = (
    4096  # a page of dense text is ~1,500 tokens; stops a model looping on a blank image
)


def make_ocr(cfg: LLMConfig) -> "OllamaLLM":
    """The model that reads images. Images (and the text read from them) never leave this machine:
    only a vision model served by Ollama on this computer is accepted."""
    llm = make_llm(cfg)
    if not isinstance(llm, OllamaLLM) or llm.sends_text_out:
        raise ValueError(
            "[llm.ocr] must be a vision model served by Ollama on this machine "
            '(model = "ollama/qwen3-vl:2b-instruct"): images are never sent anywhere else'
        )
    return llm


def _post(url: str, *, headers: dict, payload: dict, timeout_seconds: float) -> dict:
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=timeout_seconds)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(
            f"{url} -> HTTP {exc.response.status_code}: {exc.response.text[:300]}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise LLMTimeout(f"{url} gave no answer within {timeout_seconds:g}s") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"{url} unreachable: {exc}") from exc
    return resp.json()


def _api_key(cfg: LLMConfig, default_env: str) -> str:
    env = cfg.api_key_env or default_env
    key = os.environ.get(env)
    if not key:
        raise LLMError(f"Environment variable {env} is not set")
    return key


def is_loopback(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "::1") or host.startswith("127.")


class OllamaLLM:
    @property
    def sends_text_out(self) -> bool:
        """False only for a model served from this machine: Ollama can be pointed at another host,
        and its `-cloud` models run on Ollama's servers."""
        return not is_loopback(self.base) or self.name.lower().endswith((":cloud", "-cloud"))

    def __init__(self, name: str, cfg: LLMConfig):
        self.name, self.cfg = name, cfg
        self.tokens_used = 0
        self.base = (cfg.base_url or "http://localhost:11434").rstrip("/")

    def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        data = _post(
            f"{self.base}/api/chat",
            headers={},
            timeout_seconds=self.cfg.timeout_seconds,
            payload={
                "model": self.name,
                "stream": False,
                "format": schema,
                "options": {
                    "num_ctx": self.cfg.num_ctx,
                    "temperature": self.cfg.temperature,
                    **({"num_predict": self.cfg.max_tokens} if self.cfg.max_tokens else {}),
                },
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        self.tokens_used += data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
        return data["message"]["content"]

    def read_image(self, png: bytes) -> str:
        """The text printed in an image (a vision model: qwen3-vl, ...), in reading order."""
        data = _post(
            f"{self.base}/api/chat",
            headers={},
            timeout_seconds=self.cfg.timeout_seconds,
            payload={
                "model": self.name,
                "stream": False,
                "options": {
                    "num_ctx": self.cfg.num_ctx,
                    "temperature": 0,
                    "num_predict": self.cfg.max_tokens or OCR_MAX_TOKENS,
                },
                "messages": [
                    {
                        "role": "user",
                        "content": OCR_PROMPT,
                        "images": [base64.b64encode(png).decode()],
                    }
                ],
            },
        )
        self.tokens_used += data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
        return data["message"]["content"].strip()


class OpenAILLM:
    sends_text_out = True

    def __init__(self, name: str, cfg: LLMConfig):
        self.name, self.cfg = name, cfg
        self.tokens_used = 0
        self.base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {_api_key(self.cfg, 'OPENAI_API_KEY')}"}

    def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        data = _post(
            f"{self.base}/chat/completions",
            headers=self._headers(),
            timeout_seconds=self.cfg.timeout_seconds,
            payload={
                "model": self.name,
                "temperature": self.cfg.temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "edit_plan", "schema": schema},
                },
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        usage = data.get("usage", {})
        self.tokens_used += usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"]


class LMStudioLLM(OpenAILLM):
    """LM Studio's local server speaks the OpenAI protocol (default http://localhost:1234/v1) and
    needs no key; the model name is the identifier LM Studio shows (`lms ls`)."""

    def __init__(self, name: str, cfg: LLMConfig):
        super().__init__(name, cfg)
        self.base = (cfg.base_url or "http://localhost:1234/v1").rstrip("/")

    @property
    def sends_text_out(self) -> bool:  # False unless base_url points at another machine
        return not is_loopback(self.base)

    def _headers(self) -> dict:
        return {}


class AnthropicLLM:
    sends_text_out = True

    def __init__(self, name: str, cfg: LLMConfig):
        self.name, self.cfg = name, cfg
        self.tokens_used = 0
        self.base = (cfg.base_url or "https://api.anthropic.com").rstrip("/")

    def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        headers = {
            "x-api-key": _api_key(self.cfg, "ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
        }
        data = _post(
            f"{self.base}/v1/messages",
            headers=headers,
            timeout_seconds=self.cfg.timeout_seconds,
            payload={
                "model": self.name,
                "max_tokens": 4096,
                "temperature": self.cfg.temperature,
                "system": system,
                "messages": [{"role": "user", "content": user}],
                "tools": [
                    {
                        "name": "submit_edit_plan",
                        "description": "Submit the edit plan for this source.",
                        "input_schema": schema,
                    }
                ],
                "tool_choice": {"type": "tool", "name": "submit_edit_plan"},
            },
        )
        usage = data.get("usage", {})
        self.tokens_used += usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        for block in data.get("content", []):
            if block.get("type") == "tool_use":
                return json.dumps(block["input"])
        raise LLMError("Anthropic response had no tool_use block")


class OllamaEmbedder:
    """Vectors from Ollama's `/api/embed`. `nomic-embed-text` was trained with a task prefix on
    both sides; without it the same notes retrieved measurably worse (see rag-fit.md)."""

    def __init__(self, name: str, cfg: LLMConfig):
        self.name, self.cfg = name, cfg
        self.base = (cfg.base_url or "http://localhost:11434").rstrip("/")
        self.identity = f"{self.base}/{name}"  # a vector is only comparable with its own model's
        self.prefixed = name.startswith("nomic-embed")

    @property
    def sends_text_out(self) -> bool:
        return not is_loopback(self.base) or self.name.lower().endswith((":cloud", "-cloud"))

    def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        if self.prefixed:
            prefix = "search_query: " if query else "search_document: "
            texts = [prefix + t for t in texts]
        data = _post(
            f"{self.base}/api/embed",
            headers={},
            timeout_seconds=self.cfg.timeout_seconds,
            payload={"model": self.name, "input": texts, "truncate": True},
        )
        vectors = data.get("embeddings", [])
        if len(vectors) != len(texts):
            raise LLMError(f"{self.base} returned {len(vectors)} vectors for {len(texts)} texts")
        return vectors


def make_embedder(cfg: LLMConfig) -> OllamaEmbedder:
    provider, _, name = cfg.model.partition("/")
    if provider != "ollama" or not name:
        raise ValueError(
            f"[llm.embed] model must look like 'ollama/<name>' (only Ollama embeds for now), "
            f"got {cfg.model!r}"
        )
    return OllamaEmbedder(name, cfg)
