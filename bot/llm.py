"""Chamadas a LLM (Anthropic ou OpenAI) e embeddings (OpenAI), via HTTP simples."""
import json
import re
import requests
from .config import SECRETS


GEMINI = "https://generativelanguage.googleapis.com/v1beta"
_GEMINI_CACHE: dict[str, str] = {}


def gemini_model(cfg: dict, method: str = "generateContent") -> str:
    """Escolhe um modelo Gemini que exista de verdade: usa o do config se existir; senão o Flash estável mais novo.
    Os nomes mudam com frequência (2.5 → 3.x), então consultamos models.list em vez de confiar no config."""
    if method in _GEMINI_CACHE:
        return _GEMINI_CACHE[method]
    r = requests.get(f"{GEMINI}/models", params={"key": SECRETS.gemini, "pageSize": 1000}, timeout=30)
    r.raise_for_status()
    models = [m for m in r.json().get("models", []) if method in m.get("supportedGenerationMethods", [])]
    names = [m["name"].removeprefix("models/") for m in models]
    if method == "generateContent":
        want = cfg["ai"].get("gemini_model")
        if want in names:
            chosen = want
        else:
            def rank(n):  # prefere flash estável (sem preview/exp/live/tts/image), versão mais alta
                bad = any(k in n for k in ("preview", "exp", "live", "tts", "image", "audio", "robotics", "omni", "thinking"))
                import re
                v = re.search(r"(\d+)\.(\d+)", n)
                ver = (int(v.group(1)), int(v.group(2))) if v else (0, 0)
                return (not bad, "flash" in n, "lite" not in n, ver)
            cands = sorted(names, key=rank, reverse=True)
            chosen = cands[0] if cands else "gemini-2.5-flash"
    else:  # embedContent
        want = "gemini-embedding-001"
        emb = [n for n in names if "embedding" in n]
        chosen = want if want in names else (sorted(emb, reverse=True)[0] if emb else want)
    _GEMINI_CACHE[method] = chosen
    print(f"[gemini] modelo para {method}: {chosen}")
    return chosen


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
        r = requests.post(f"{GEMINI}/models/{gemini_model(cfg)}:generateContent",
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


def embeddings(texts: list[str], provider: str = "gemini", cfg: dict | None = None) -> list[list[float]] | None:
    if provider == "gemini" and SECRETS.gemini:
        model = gemini_model(cfg or {"ai": {}}, "embedContent")
        out = []
        for i in range(0, len(texts), 100):
            r = requests.post(f"{GEMINI}/models/{model}:batchEmbedContents", params={"key": SECRETS.gemini},
                              json={"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t}]},
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
