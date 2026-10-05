"""The vision models that can read images and scanned PDFs: what each needs, which prompt it
understands, and how to see whether the local Ollama has it (and fetch it, when the user says so)."""

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

import httpx

GENERIC_PROMPT = (
    "Transcribe all the text in this image exactly as written, in reading order. "
    "Output only the text, nothing else. If there is no text, output nothing."
)


@dataclass(frozen=True)
class Preset:
    name: str  # the Ollama tag
    size_gb: float  # download size shown on ollama.com
    min_ram_gb: int  # recommended memory: the model loaded plus the page being read
    min_ollama: str  # the oldest Ollama that can run it
    note: str
    prompt: str  # what this model must be asked (a general instruction does not work for all)


# DeepSeek-OCR is trained for fixed instructions, not a free-form one: its Ollama page lists
# "Free OCR." (plain text) and grounding prompts that return boxes and markup, which a note
# cannot use.
DEEPSEEK = Preset(
    "deepseek-ocr:3b",
    6.7,
    16,
    "0.13.0",
    "needs more memory (about 10 GB loaded); on an 8 GB Mac it read a small image correctly but took 7 to 8 minutes, so use it on 16 GB or more (not measured there)",
    "Free OCR.",
)
QWEN = Preset(
    "qwen3-vl:2b-instruct",
    1.9,
    8,
    "0.12.7",
    "small and fast; fits an 8 GB Mac",
    GENERIC_PROMPT,
)
PRESETS = (DEEPSEEK, QWEN)  # the best first
DEFAULT_BASE = "http://localhost:11434"
PULL_READ_TIMEOUT_SECONDS = 300  # Ollama sends progress often; a longer silence is a stuck pull


class PullError(RuntimeError):
    pass


def preset(name: str) -> Preset | None:
    """The preset for this Ollama name (`deepseek-ocr` and `deepseek-ocr:3b` are the same model)."""
    return next((p for p in PRESETS if name in (p.name, p.name.split(":")[0])), None)


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]*")


def clean_name(text: str) -> str:
    """An Ollama model name as typed (`ollama/` in front is fine). The name ends up inside the
    config file and in a command we print, so anything else is refused."""
    name = text.strip().removeprefix("ollama/")
    if not _NAME.fullmatch(name):
        raise ValueError(f"{text!r} is not an Ollama model name (letters, digits and . _ / : -)")
    return name


def prompt_for(name: str) -> str:
    found = preset(name)
    return found.prompt if found else GENERIC_PROMPT


def machine_ram_gb() -> float | None:
    """This machine's memory in GiB (macOS and Linux), or None where the system does not say."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return None


RECOMMENDED = (
    QWEN  # the model that fits an 8 GB Mac; DeepSeek-OCR stays a choice, never the default
)


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version.split("-")[0]))


def version_at_least(have: str | None, need: str) -> bool:
    """An unknown version (Ollama not answering) is not a reason to complain."""
    return have is None or _numbers(have) >= _numbers(need)


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(5.0, read=PULL_READ_TIMEOUT_SECONDS))


def _get(base: str, path: str) -> dict | None:
    try:
        with _client() as client:
            resp = client.get(f"{base.rstrip('/')}{path}")
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError):
        return None


def installed_models(base: str = DEFAULT_BASE) -> set[str] | None:
    """The model names this Ollama has, or None when it does not answer."""
    data = _get(base, "/api/tags")
    try:
        return {m["name"] for m in data["models"]} if data else None
    except (KeyError, TypeError):
        return None


def ollama_version(base: str = DEFAULT_BASE) -> str | None:
    data = _get(base, "/api/version")
    return data.get("version") if data else None


def is_installed(name: str, installed: set[str]) -> bool:
    return name in installed or f"{name}:latest" in installed


def pull(base: str, name: str, on_progress: Callable[[str, float | None], None]) -> None:
    """Ask the local Ollama to download `name`, reporting (status, fraction done or None).
    Ollama resumes a half-finished download by itself, so running this again is safe."""
    from esbi_cli.llm.adapter import is_loopback  # adapter imports this module: not at the top

    if not is_loopback(base):
        raise PullError(f"{base} is not on this machine: pull the model there with `ollama pull`")
    try:
        with (
            _client() as client,
            client.stream(
                "POST", f"{base.rstrip('/')}/api/pull", json={"model": name, "stream": True}
            ) as resp,
        ):
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line.strip():
                    continue
                event = json.loads(line)
                if "error" in event:
                    raise PullError(str(event["error"]))
                total = event.get("total")
                done = event.get("completed")
                on_progress(
                    event.get("status", ""), done / total if total and done is not None else None
                )
    except httpx.TransportError as exc:
        raise PullError(f"Ollama is not reachable at {base}: {exc}") from exc
    except (httpx.HTTPStatusError, ValueError) as exc:
        raise PullError(f"Ollama could not pull {name}: {exc}") from exc
