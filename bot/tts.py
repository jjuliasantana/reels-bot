"""Narração (OpenAI TTS) com fallback de áudio-placeholder, e tempos de palavras para legendas."""
import json
import subprocess
import wave
from pathlib import Path
import numpy as np
import requests
from .config import SECRETS

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
    prov = cfg["ai"]["tts_provider"]
    if prov == "edge":
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            prov = "none"
    if prov == "openai" and not SECRETS.openai:
        prov = "none"
    real = prov != "none"
    scenes = []
    for i, sc in enumerate(script["scenes"]):
        path = workdir / f"narration_{i:02d}.wav"
        words = None
        if prov == "edge":
            words = _edge_tts(cfg, sc["narration"], path)
        elif prov == "openai":
            _openai_tts(cfg, sc["narration"], path)
            words = _word_timestamps(path)
        else:
            _placeholder_audio(sc["narration"], path)
        dur = _duration(path)
        words = words or _even_words(sc["narration"], dur)
        scenes.append({**sc, "audio": str(path), "duration": dur, "words": words})
    return scenes, real
