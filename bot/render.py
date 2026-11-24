"""Monta o MP4 vertical 9:16: 1 arquivo por cena (zoom/pan + legendas ASS), concat e áudio."""
import math
import os
import subprocess
from pathlib import Path
from . import visuals

ENC = ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "30"]


def _ass_time(t: float) -> str:
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _write_ass(scene: dict, path: Path, font_name: str = "Inter"):
    """Legendas em blocos de 3–4 palavras, sincronizadas com os tempos das palavras."""
    words = scene["words"]
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 3 and (len(cur) >= 4 or w["word"].rstrip().endswith((".", ",", "?", "!"))):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font_name},78,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,6,2,2,80,80,560,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for ch in chunks:
        text = " ".join(w["word"].strip() for w in ch).replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{_ass_time(ch[0]['start'])},{_ass_time(ch[-1]['end'])},Cap,,0,0,0,,{text.upper()}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _run(cmd: list[str]):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def render_scene(cfg: dict, scene: dict, idx: int, workdir: Path) -> tuple[Path, bool]:
    png, used_ai = visuals.render_scene_image(cfg, scene, idx, workdir)
    ass = workdir / f"scene_{idx:02d}.ass"
    _write_ass(scene, ass)
    fps = cfg["video"]["fps"]
    frames = max(int(round(scene["duration"] * fps)), fps)
    dur = frames / fps
    # alterna zoom-in e pan lateral (movimento simples e barato)
    if idx % 2 == 0:
        z = f"zoompan=z='min(1+0.0012*on,1.18)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={fps}"
    else:
        z = f"zoompan=z='1.12':x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={fps}"
    ass_path = str(ass).replace("\\", "/").replace(":", "\\:")
    vf = (f"scale=2160:3840:flags=lanczos,{z},subtitles='{ass_path}',"
          f"fade=t=in:d=0.25,fade=t=out:st={max(dur - 0.25, 0):.2f}:d=0.25,format=yuv420p")
    tmp, out = workdir / f"scene_{idx:02d}.tmp.mp4", workdir / f"scene_{idx:02d}.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), "-vf", vf, "-t", f"{dur:.3f}", *ENC, "-an", str(tmp)])
    os.replace(tmp, out)
    return out, used_ai


def assemble(cfg: dict, scenes: list[dict], workdir: Path, final_path: Path) -> dict:
    files, ai_images = [], 0
    for i, sc in enumerate(scenes):
        f, used_ai = render_scene(cfg, sc, i, workdir)
        files.append(f); ai_images += int(used_ai)
    lst = workdir / "concat.txt"
    lst.write_text("".join(f"file '{f.name}'\n" for f in files))
    silent = workdir / "video_silent.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(silent)])
    alst = workdir / "audio_concat.txt"
    alst.write_text("".join(f"file '{Path(sc['audio']).name}'\n" for sc in scenes))
    audio = workdir / "narration_all.wav"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(alst), "-c", "copy", str(audio)])
    tmp = final_path.with_suffix(".tmp.mp4")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio), "-map", "0:v", "-map", "1:a",
          "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-shortest", "-movflags", "+faststart", str(tmp)])
    os.replace(tmp, final_path)
    total = sum(sc["duration"] for sc in scenes)
    return {"path": str(final_path), "seconds": round(total, 2), "scenes": len(scenes), "ai_images": ai_images}
