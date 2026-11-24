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


def chat(cfg: dict, system: str, user: str, max_tokens: int = 1500, json_mode: bool = False) -> str:
    prov = available(cfg)
    if prov == "gemini":
        # Gemini 2.5/3.x "pensa" antes de responder e o pensamento conta no limite de tokens: limite alto + pouco pensamento.
        gen = {"maxOutputTokens": 8192, "temperature": 0.9, "thinkingConfig": {"thinkingBudget": 512}}
        if json_mode:
            gen["responseMimeType"] = "application/json"
        r = requests.post(f"{GEMINI}/models/{gemini_model(cfg)}:generateContent",
                          params={"key": SECRETS.gemini},
                          json={"system_instruction": {"parts": [{"text": system}]},
                                "contents": [{"role": "user", "parts": [{"text": user}]}],
                                "generationConfig": gen}, timeout=120)
        if r.status_code == 400 and "thinking" in r.text.lower():  # modelo sem thinkingConfig
            gen.pop("thinkingConfig", None)
            r = requests.post(f"{GEMINI}/models/{gemini_model(cfg)}:generateContent", params={"key": SECRETS.gemini},
                              json={"system_instruction": {"parts": [{"text": system}]},
                                    "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen}, timeout=120)
        r.raise_for_status()
        cand = r.json()["candidates"][0]
        txt = "".join(p.get("text", "") for p in cand["content"].get("parts", []) if not p.get("thought"))
        if not txt.strip():
            raise RuntimeError(f"resposta vazia do Gemini (finishReason={cand.get('finishReason')})")
        return txt
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


def _clean(txt: str) -> str:
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt.strip())
    m = re.search(r"\{.*\}", txt, re.S)
    return m.group(0) if m else txt


def _repair_json(txt: str) -> str:
    """Conserta erros comuns de LLM: aspas curvas, quebras de linha dentro de strings, aspas internas sem escape."""
    txt = txt.replace("\u201c", '\\"').replace("\u201d", '\\"').replace("\u2019", "'").replace("\u2018", "'")
    out, in_str, esc = [], False, False
    i = 0
    while i < len(txt):
        c = txt[i]
        if in_str:
            if esc:
                out.append(c); esc = False
            elif c == "\\":
                out.append(c); esc = True
            elif c == '"':
                # fecha a string só se o próximo caractere relevante for um delimitador JSON; senão é aspa interna
                j = i + 1
                while j < len(txt) and txt[j] in " \t\r\n":
                    j += 1
                if j >= len(txt) or txt[j] in ",}]:":
                    out.append(c); in_str = False
                else:
                    out.append('\\"')
            elif c == "\n":
                out.append("\\n")
            else:
                out.append(c)
        else:
            if c == '"':
                in_str = True
            out.append(c)
        i += 1
    return "".join(out)


def parse_json_lenient(txt: str) -> dict:
    txt = _clean(txt)
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return json.loads(_repair_json(txt))


def chat_json(cfg: dict, system: str, user: str, max_tokens: int = 1500) -> dict:
    txt = chat(cfg, system + "\nRespond ONLY with valid JSON, no markdown fences. Escape double quotes inside strings "
               "(or use single quotes inside text).", user, max_tokens, json_mode=True)
    try:
        return parse_json_lenient(txt)
    except json.JSONDecodeError as e:
        print(f"[json] inválido ({e}); pedindo correção ao modelo")
        fixed = chat(cfg, "You fix broken JSON. Output ONLY the corrected JSON, same content, nothing else.",
                     _clean(txt)[:12000], max_tokens, json_mode=True)
        return parse_json_lenient(fixed)


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
