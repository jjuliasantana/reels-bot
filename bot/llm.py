"""Chamadas a LLM (Anthropic ou OpenAI) e embeddings (OpenAI), via HTTP simples."""
import json
import re
import requests
from .config import SECRETS


GEMINI = "https://generativelanguage.googleapis.com/v1beta"


def available(cfg: dict) -> str | None:
    p = cfg["ai"]["llm_provider"]
    if p == "gemini" and SECRETS.gemini:
        return "gemini"
    if p == "anthropic" and SECRETS.anthropic:
        return "anthropic"
    if p == "openai" and SECRETS.openai:
        return "openai"
    for name, key in (("gemini", SECRETS.gemini), ("anthropic", SECRETS.anthropic), ("openai", SECRETS.openai)):
        if key:
            return name
    return None


def chat(cfg: dict, system: str, user: str, max_tokens: int = 1500) -> str:
    prov = available(cfg)
    if prov == "gemini":
        r = requests.post(f"{GEMINI}/models/{cfg['ai']['gemini_model']}:generateContent",
                          params={"key": SECRETS.gemini},
                          json={"system_instruction": {"parts": [{"text": system}]},
                                "contents": [{"role": "user", "parts": [{"text": user}]}],
                                "generationConfig": {"maxOutputTokens": max_tokens * 2, "temperature": 0.8}}, timeout=120)
        r.raise_for_status()
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
    if prov == "anthropic":
        r = requests.post("https://api.anthropic.com/v1/messages", headers={
            "x-api-key": SECRETS.anthropic, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": cfg["ai"]["anthropic_model"], "max_tokens": max_tokens, "system": system,
                  "messages": [{"role": "user", "content": user}]}, timeout=120)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])
    if prov == "openai":
        r = requests.post("https://api.openai.com/v1/chat/completions", headers={
            "Authorization": f"Bearer {SECRETS.openai}"},
            json={"model": cfg["ai"]["openai_model"], "max_tokens": max_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("Nenhum LLM configurado")


def chat_json(cfg: dict, system: str, user: str, max_tokens: int = 1500) -> dict:
    txt = chat(cfg, system + "\nResponda SOMENTE com JSON válido, sem markdown.", user, max_tokens)
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0) if m else txt)


def embeddings(texts: list[str], provider: str = "gemini") -> list[list[float]] | None:
    if provider == "gemini" and SECRETS.gemini:
        out = []
        for i in range(0, len(texts), 100):
            r = requests.post(f"{GEMINI}/models/gemini-embedding-001:batchEmbedContents", params={"key": SECRETS.gemini},
                              json={"requests": [{"model": "models/gemini-embedding-001", "content": {"parts": [{"text": t}]},
                                                  "taskType": "CLUSTERING"} for t in texts[i:i + 100]]}, timeout=120)
            r.raise_for_status()
            out += [e["values"] for e in r.json()["embeddings"]]
        return out
    if not SECRETS.openai:
        return None
    r = requests.post("https://api.openai.com/v1/embeddings", headers={"Authorization": f"Bearer {SECRETS.openai}"},
                      json={"model": "text-embedding-3-small", "input": texts}, timeout=60)
    r.raise_for_status()
    return [d["embedding"] for d in r.json()["data"]]
