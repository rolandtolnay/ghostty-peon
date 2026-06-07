"""Standalone Ollama HTTP client. Pure stdlib (json + urllib).

When configured, high-value Ghostty Peon LLM calls can optionally delegate to
local-llm's scheduler. Without that configuration, or when delegation fails,
this bundled direct Ollama client remains the standalone default.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "gemma4:e2b"
DEFAULT_CTX = 8192
HIGH_PRIORITY_TAGS = {"tabtitle", "stop-question", "workflow-transition"}

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


def _response_from_api(data: dict, *, think: bool) -> tuple[str, str | None]:
    message = data.get("message", {})
    return message.get("content", ""), message.get("thinking") if think else None


def _direct_ollama_chat(
    *,
    prompt: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    num_ctx: int,
    think: bool,
    timeout: float | None,
) -> dict:
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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _configured_local_llm_client() -> Path | None:
    value = os.environ.get("GHOSTTY_PEON_LOCAL_LLM_CLIENT")
    if not value:
        return None
    path = Path(value).expanduser()
    try:
        if path.resolve() == Path(__file__).resolve():
            return None
    except OSError:
        return None
    return path if path.exists() else None


def _configured_local_llm_wrapper() -> Path | None:
    value = os.environ.get("GHOSTTY_PEON_LOCAL_LLM_WRAPPER")
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.exists() else None


def _delegate_via_client(
    client_path: Path,
    *,
    prompt: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    num_ctx: int,
    think: bool,
    tag: str | None,
    timeout: float | None,
) -> str:
    spec = importlib.util.spec_from_file_location("ghostty_peon_local_llm_client", client_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import local-llm client at {client_path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(client_path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(client_path.parent))
        except ValueError:
            pass
    return module.llm(
        prompt,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        num_ctx=num_ctx,
        think=think,
        tag=tag,
        timeout=timeout,
        priority="high",
        use_scheduler=True,
    )


def _delegate_via_wrapper(
    wrapper_path: Path,
    *,
    prompt: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    num_ctx: int,
    think: bool,
    tag: str | None,
    timeout: float | None,
) -> str:
    args = [
        str(wrapper_path),
        "--priority", "high",
        "--temperature", str(temperature),
        "--max-tokens", str(max_tokens),
        "--num-ctx", str(num_ctx),
    ]
    if timeout is not None:
        args.extend(["--timeout", str(timeout)])
    if tag:
        args.extend(["--tag", tag])
    if think:
        args.append("--think")
    if system:
        args.extend(["--system", system])
    args.append(prompt)

    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout.rstrip("\n")


def _try_local_llm_delegation(
    *,
    prompt: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
    num_ctx: int,
    think: bool,
    tag: str | None,
    timeout: float | None,
) -> str | None:
    if tag not in HIGH_PRIORITY_TAGS:
        return None

    client_path = _configured_local_llm_client()
    wrapper_path = _configured_local_llm_wrapper()
    if client_path is None and wrapper_path is None:
        return None

    try:
        if client_path is not None:
            return _delegate_via_client(
                client_path,
                prompt=prompt,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                num_ctx=num_ctx,
                think=think,
                tag=tag,
                timeout=timeout,
            )
        assert wrapper_path is not None
        return _delegate_via_wrapper(
            wrapper_path,
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            num_ctx=num_ctx,
            think=think,
            tag=tag,
            timeout=timeout,
        )
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
            error=f"local-llm delegation failed; falling back: {type(e).__name__}: {e}",
        )
        return None


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
    """Send a prompt to the local model and return the response text."""
    delegated = _try_local_llm_delegation(
        prompt=prompt,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        num_ctx=num_ctx,
        think=think,
        tag=tag,
        timeout=timeout,
    )
    if delegated is not None:
        return delegated

    try:
        data = _direct_ollama_chat(
            prompt=prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            num_ctx=num_ctx,
            think=think,
            timeout=timeout,
        )
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

    response, thinking = _response_from_api(data, think=think)
    _log_call(
        system=system,
        prompt=prompt,
        response=response,
        thinking=thinking,
        tag=tag,
        temperature=temperature,
        max_tokens=max_tokens,
        num_ctx=num_ctx,
        timeout=timeout,
        think=think,
        raw_api_response=data,
    )
    return response
