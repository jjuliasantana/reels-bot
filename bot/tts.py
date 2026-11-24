"""Narração (OpenAI TTS) com fallback de áudio-placeholder, e tempos de palavras para legendas."""
import json
import subprocess
import wave
from pathlib import Path
import numpy as np
import requests
from .config import SECRETS, env

WORDS_PER_SEC = 2.3  # ritmo de fala estimado quando não há áudio real (inclui pausas)


def _duration(path: Path) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


def _openai_tts(cfg: dict, text: str, out: Path):
    r = requests.post("https://api.openai.com/v1/audio/speech", headers={"Authorization": f"Bearer {SECRETS.openai}"},
                      json={"model": cfg["ai"]["openai_tts_model"], "voice": cfg["ai"]["openai_tts_voice"],
                            "input": text, "response_format": "wav"}, timeout=120)
    r.raise_for_status()
    out.write_bytes(r.content)


def _edge_tts(cfg: dict, text: str, out: Path) -> list[dict]:
    """edge-tts (gratuito): gera o áudio e devolve os tempos de cada palavra (WordBoundary)."""
    import asyncio
    import edge_tts

    async def go():
        words, mp3 = [], out.with_suffix(".mp3")
        comm = edge_tts.Communicate(text, cfg["ai"]["edge_voice"], rate="+5%")
        with open(mp3, "wb") as f:
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append({"word": ch["text"], "start": ch["offset"] / 1e7, "end": (ch["offset"] + ch["duration"]) / 1e7})
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "44100", "-ac", "1", str(out)], check=True)
        return words
    return asyncio.run(go())


def _kokoro_tts(cfg: dict, text: str, out: Path) -> list[dict]:
    """Kokoro (open-source, CPU, sem chave): voz natural + timestamps por palavra."""
    import soundfile as sf
    from kokoro import KPipeline
    global _KOKORO
    try:
        _KOKORO
    except NameError:
        _KOKORO = KPipeline(lang_code="a")  # 'a' = American English
    voice = cfg["ai"].get("kokoro_voice", "am_michael")
    audio, words, offset = [], [], 0.0
    for res in _KOKORO(text, voice=voice, speed=float(cfg["ai"].get("kokoro_speed", 1.05))):
        if res.audio is None:
            continue
        a = res.audio.numpy() if hasattr(res.audio, "numpy") else np.asarray(res.audio)
        for t in (res.tokens or []):
            if getattr(t, "start_ts", None) is not None and t.text.strip():
                words.append({"word": t.text, "start": offset + float(t.start_ts), "end": offset + float(t.end_ts)})
        audio.append(a); offset += len(a) / 24000
    sig = np.concatenate(audio) if audio else np.zeros(24000)
    sf.write(str(out), sig, 24000)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-ar", "44100", "-ac", "1", str(out.with_suffix(".tmp.wav"))], check=True)
    out.with_suffix(".tmp.wav").replace(out)
    return words


def _gemini_tts(cfg: dict, text: str, out: Path):
    """Gemini TTS (cota gratuita): muito expressivo, com instrução de estilo. Sem timestamps de palavra."""
    import base64
    from . import llm
    r = requests.get(f"{llm.GEMINI}/models", params={"key": SECRETS.gemini, "pageSize": 1000}, timeout=30)
    r.raise_for_status()
    names = [m["name"].removeprefix("models/") for m in r.json().get("models", []) if "tts" in m["name"]]
    if not names:
        raise RuntimeError("nenhum modelo TTS do Gemini disponível")
    model = cfg["ai"].get("gemini_tts_model") if cfg["ai"].get("gemini_tts_model") in names else sorted(names)[0]
    style = cfg["ai"].get("gemini_tts_style", "Energetic, confident gaming YouTuber, fast but clear, a little playful")
    import time
    for attempt in range(4):
        r = requests.post(f"{llm.GEMINI}/models/{model}:generateContent", params={"key": SECRETS.gemini},
                          json={"contents": [{"parts": [{"text": f"{style}: {text}"}]}],
                                "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"voiceConfig": {
                                    "prebuiltVoiceConfig": {"voiceName": cfg["ai"].get("gemini_tts_voice", "Puck")}}}}}, timeout=180)
        if r.status_code in (429, 503) and attempt < 3:
            wait = 20 * (attempt + 1)
            print(f"[tts gemini] limite de requisições; esperando {wait}s")
            time.sleep(wait); continue
        break
    r.raise_for_status()
    data = next(p["inlineData"] for p in r.json()["candidates"][0]["content"]["parts"] if "inlineData" in p)
    pcm = base64.b64decode(data["data"])  # PCM 16-bit 24 kHz mono
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)


def _elevenlabs_tts(cfg: dict, text: str, out: Path) -> list[dict]:
    """ElevenLabs (plano grátis: ~10k créditos/mês, não comercial; Starter US$5 para monetizar). Com timestamps."""
    import base64
    key = env("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("sem ELEVENLABS_API_KEY")
    voice = cfg["ai"].get("elevenlabs_voice_id", "pNInz6obpgDQGcFmaJgB")  # Adam (padrão da ElevenLabs)
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps",
                      headers={"xi-api-key": key, "Content-Type": "application/json"},
                      params={"output_format": "mp3_44100_128"},
                      json={"text": text, "model_id": cfg["ai"].get("elevenlabs_model", "eleven_multilingual_v2"),
                            "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.35}}, timeout=180)
    r.raise_for_status()
    j = r.json()
    mp3 = out.with_suffix(".mp3"); mp3.write_bytes(base64.b64decode(j["audio_base64"]))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", "44100", "-ac", "1", str(out)], check=True)
    al = j.get("alignment") or {}
    chars, starts, ends = al.get("characters", []), al.get("character_start_times_seconds", []), al.get("character_end_times_seconds", [])
    words, cur, ws = [], "", None
    for c, st, en in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append({"word": cur, "start": ws, "end": en}); cur, ws = "", None
        else:
            if ws is None:
                ws = st
            cur += c; last = en
    if cur:
        words.append({"word": cur, "start": ws, "end": last})
    return words


def _word_timestamps(path: Path) -> list[dict] | None:
    """Whisper com timestamps por palavra (opcional, melhora a sincronia das legendas)."""
    try:
        with open(path, "rb") as f:
            r = requests.post("https://api.openai.com/v1/audio/transcriptions",
                              headers={"Authorization": f"Bearer {SECRETS.openai}"},
                              files={"file": f}, data={"model": "whisper-1", "response_format": "verbose_json",
                                                       "timestamp_granularities[]": "word"}, timeout=120)
        r.raise_for_status()
        return [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in r.json().get("words", [])]
    except Exception:
        return None


def _placeholder_audio(text: str, out: Path, sr: int = 44100):
    """Trilha sintética suave (sem voz). Usada SÓ quando não há TTS configurado."""
    dur = max(2.0, len(text.split()) / WORDS_PER_SEC + 0.6)
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    beat = (np.sin(2 * np.pi * 2.0 * t) > 0.9).astype(float) * np.exp(-((t * 2) % 1) * 6)
    pad = 0.08 * np.sin(2 * np.pi * 110 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.25 * t))
    sig = np.clip(0.25 * beat * np.sin(2 * np.pi * 55 * t) + pad, -1, 1)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((sig * 32767).astype(np.int16).tobytes())


def _even_words(text: str, dur: float) -> list[dict]:
    words = text.split()
    chars = sum(len(w) + 1 for w in words)
    t, out = 0.0, []
    for w in words:
        d = dur * (len(w) + 1) / chars
        out.append({"word": w, "start": t, "end": t + d})
        t += d
    return out


def narrate(cfg: dict, script: dict, workdir: Path) -> tuple[list[dict], bool]:
    """Gera 1 áudio por cena. Retorna (cenas com audio/duration/words, usou_tts_real?)."""
    order = [p.strip() for p in str(cfg["ai"]["tts_provider"]).split(",")] + ["edge", "none"]
    scenes = []
    prov_used = None
    for i, sc in enumerate(script["scenes"]):
        path = workdir / f"narration_{i:02d}.wav"
        words = None
        chain = order[order.index(prov_used):] if prov_used in order else order  # começa no que funcionou, mas pode descer
        ok = False
        for prov in chain:
            try:
                if prov == "elevenlabs":
                    words = _elevenlabs_tts(cfg, sc["narration"], path)
                elif prov == "kokoro":
                    words = _kokoro_tts(cfg, sc["narration"], path)
                elif prov == "gemini":
                    if not SECRETS.gemini:
                        raise RuntimeError("sem GEMINI_API_KEY")
                    _gemini_tts(cfg, sc["narration"], path)
                elif prov == "edge":
                    words = _edge_tts(cfg, sc["narration"], path)
                elif prov == "openai":
                    if not SECRETS.openai:
                        raise RuntimeError("sem OPENAI_API_KEY")
                    _openai_tts(cfg, sc["narration"], path); words = _word_timestamps(path)
                else:
                    _placeholder_audio(sc["narration"], path)
                prov_used = prov; ok = True
                break
            except Exception as e:
                print(f"[aviso] TTS {prov} falhou na cena {i}: {str(e)[:120]}")
        if not ok or not path.exists():
            _placeholder_audio(sc["narration"], path); prov_used = "none"
        real = prov_used not in (None, "none")
        dur = _duration(path)
        words = words or _even_words(sc["narration"], dur)
        scenes.append({**sc, "audio": str(path), "duration": dur, "words": words})
    print(f"[tts] provedor usado: {prov_used}")
    cfg["ai"]["_tts_used"] = prov_used
    return scenes, real
