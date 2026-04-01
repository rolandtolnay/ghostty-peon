"""Standalone Ollama HTTP client. Pure stdlib (json + urllib)."""

import json
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:4b"
DEFAULT_CTX = 8192


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
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())

    return data.get("message", {}).get("content", "")
