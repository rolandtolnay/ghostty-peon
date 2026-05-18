"""Standalone Ollama HTTP client. Pure stdlib (json + urllib)."""

import json
import time
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "gemma4:e2b"
DEFAULT_CTX = 8192

LOG_DIR = Path.home() / ".local" / "share" / "local-llm"
RETAIN_MONTHS = 3


def _current_log_file() -> Path:
    return LOG_DIR / f"calls-{time.strftime('%Y-%m')}.jsonl"


def _cleanup_old_log_files() -> None:
    now = time.localtime()
    keep = set()
    for i in range(RETAIN_MONTHS):
        month = now.tm_mon - i
        year = now.tm_year
        while month < 1:
            month += 12
            year -= 1
        keep.add(f"calls-{year:04d}-{month:02d}.jsonl")

    for path in LOG_DIR.glob("calls-????-??.jsonl"):
        if path.name not in keep:
            try:
                path.unlink()
            except OSError:
                pass


def _write_log_entry(entry: dict) -> None:
    """Write a local-llm-compatible JSONL entry. Never fail the caller."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(_current_log_file(), "a") as f:
            f.write(json.dumps(entry) + "\n")
        _cleanup_old_log_files()
    except Exception:
        pass


def _log_call(
    *,
    system: str | None,
    prompt: str,
    response: str,
    thinking: str | None,
    tag: str | None,
    temperature: float,
    max_tokens: int,
    num_ctx: int,
    timeout: float | None,
    think: bool,
    raw_api_response: dict,
) -> None:
    total_ns = raw_api_response.get("total_duration", 0)
    prompt_eval_ns = raw_api_response.get("prompt_eval_duration", 0)
    eval_ns = raw_api_response.get("eval_duration", 0)
    load_ns = raw_api_response.get("load_duration", 0)

    prompt_tokens = raw_api_response.get("prompt_eval_count", 0)
    completion_tokens = raw_api_response.get("eval_count", 0)
    gen_tok_per_sec = completion_tokens / (eval_ns / 1e9) if eval_ns > 0 else None

    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "epoch": time.time(),
        "model": MODEL,
        "tag": tag,
        "system": system,
        "prompt": prompt,
        "response": response,
        "thinking": thinking,
        "params": {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "think": think,
            "num_ctx": num_ctx,
            **({"timeout": timeout} if timeout is not None else {}),
        },
        "tokens": {
            "prompt": prompt_tokens,
            "completion": completion_tokens,
            "total": prompt_tokens + completion_tokens,
        },
        "timing_ms": {
            "total": round(total_ns / 1e6, 1),
            "prompt_eval": round(prompt_eval_ns / 1e6, 1),
            "generation": round(eval_ns / 1e6, 1),
            "model_load": round(load_ns / 1e6, 1),
        },
        "gen_tok_per_sec": round(gen_tok_per_sec, 1) if gen_tok_per_sec else None,
    }
    _write_log_entry(entry)


def _log_error(
    *,
    system: str | None,
    prompt: str,
    tag: str | None,
    temperature: float,
    max_tokens: int,
    num_ctx: int,
    timeout: float | None,
    think: bool,
    error: str,
) -> None:
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "epoch": time.time(),
        "model": MODEL,
        "tag": tag,
        "system": system,
        "prompt": prompt,
        "response": None,
        "error": error,
        "params": {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "think": think,
            "num_ctx": num_ctx,
            **({"timeout": timeout} if timeout is not None else {}),
        },
    }
    _write_log_entry(entry)


def llm(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 512,
    num_ctx: int = DEFAULT_CTX,
    think: bool = False,
    tag: str | None = None,
    timeout: float | None = None,
) -> str:
    """Send a prompt to the local Ollama model and return the response text."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": think,
        "keep_alive": -1,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": num_ctx,
        },
    }).encode()

    req = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        _log_error(
            system=system,
            prompt=prompt,
            tag=tag,
            temperature=temperature,
            max_tokens=max_tokens,
            num_ctx=num_ctx,
            timeout=timeout,
            think=think,
            error=f"{type(e).__name__}: {e}",
        )
        raise

    message = data.get("message", {})
    response = message.get("content", "")
    _log_call(
        system=system,
        prompt=prompt,
        response=response,
        thinking=message.get("thinking") if think else None,
        tag=tag,
        temperature=temperature,
        max_tokens=max_tokens,
        num_ctx=num_ctx,
        timeout=timeout,
        think=think,
        raw_api_response=data,
    )
    return response
