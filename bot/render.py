"""Monta o MP4 vertical 9:16: 1 arquivo por cena (zoom/pan + legendas ASS), concat e áudio."""
import math
import os
import random
import subprocess
from pathlib import Path
from PIL import Image
from . import visuals, assets
from .config import ROOT


def find_broll(game: str | None) -> list[Path]:
    """Material em assets/broll/<jogo>/: sua gameplay ou material oficial do publisher (vídeo ou imagem)."""
    return assets.local_assets(game)

ENC = ["-c:v", "libx264", "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "30"]


def _ass_time(t: float) -> str:
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _write_ass(scene: dict, path: Path, font_name: str = "Inter"):
    """Legendas estilo short: 1–2 palavras por vez, grandes, centralizadas, com pop de cor."""
    words = scene["words"]
    accent = scene.get("params", {}).get("accent", "#2ee6a6").lstrip("#")
    abgr = f"&H00{accent[4:6]}{accent[2:4]}{accent[0:2]}"  # ASS usa BBGGRR
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        long_word = len(w["word"].strip()) >= 7
        if len(cur) >= 2 or long_word or w["word"].rstrip().endswith((".", ",", "?", "!")):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font_name},104,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,9,3,5,60,60,0,1",
        f"Style: Pop,{font_name},112,{abgr},&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,9,3,5,60,60,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for i, ch in enumerate(chunks):
        text = " ".join(w["word"].strip() for w in ch).replace("{", "(").replace("}", ")").upper()
        style = "Pop" if (i % 3 == 2 or text.rstrip(".,!?") in ("WRONG", "NOPE", "NO")) else "Cap"
        # pequeno "pop" de escala na entrada (\fscx/\fscy animados) — centralizado na metade inferior
        fx = "{\\an5\\pos(540,1180)\\fscx80\\fscy80\\t(0,80,\\fscx100\\fscy100)}"
        end = max(ch[-1]["end"], ch[0]["start"] + 0.25)
        lines.append(f"Dialogue: 0,{_ass_time(ch[0]['start'])},{_ass_time(end)},{style},,0,0,0,,{fx}{text}")
    path.write_text("\n".join(lines), encoding="utf-8")


def _run(cmd: list[str]):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _label_for(cfg: dict, path: Path) -> str:
    return cfg["video"]["official_label"] if path.name.startswith("official_") else cfg["video"]["broll_label"]


def _mix_broll(broll: list[Path], n_scenes: int) -> list[Path]:
    """Alterna vídeo e imagens para não ficar só foto parada."""
    vids = [p for p in broll if p.suffix.lower() in assets.VIDEO_EXT]
    imgs = [p for p in broll if p.suffix.lower() in assets.IMAGE_EXT]
    if not vids or not imgs:
        return broll
    out = []
    for i in range(max(n_scenes, len(broll))):
        out.append(vids[i % len(vids)] if i % 2 == 0 else imgs[(i // 2) % len(imgs)])
    return out


def _overlay_png(cfg: dict, scene: dict, idx: int, workdir: Path) -> Path:
    """Só headline + selo, fundo transparente, para sobrepor ao B-roll."""
    from PIL import ImageDraw
    img = Image.new("RGBA", (visuals.W, visuals.H), (0, 0, 0, 0))
    shade = Image.new("RGBA", (visuals.W, visuals.H), (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle([0, 0, visuals.W, 620], fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img, shade)
    rgb = img.convert("RGB")
    visuals._headline(rgb, cfg, scene["headline"], visuals._hex(scene.get("params", {}).get("accent", "#2ee6a6")))
    visuals._label(rgb, cfg, scene.get("label") or cfg["video"]["broll_label"])
    # recupera alpha: onde o rgb mudou vs. preto puro
    import numpy as np
    a = np.array(rgb); alpha = np.array(img)[:, :, 3]
    alpha = np.maximum(alpha, (a.max(axis=2) > 0) * 255).astype(np.uint8)
    out = Image.fromarray(np.dstack([a, alpha]), "RGBA")
    p = workdir / f"overlay_{idx:02d}.png"; out.save(p)
    return p


def render_scene(cfg: dict, scene: dict, idx: int, workdir: Path, broll: list[Path] | None = None) -> tuple[Path, bool]:
    ass = workdir / f"scene_{idx:02d}.ass"
    _write_ass(scene, ass)
    fps = cfg["video"]["fps"]
    frames = max(int(round(scene["duration"] * fps)), fps)
    dur = frames / fps
    ass_path = str(ass).replace("\\", "/").replace(":", "\\:")
    clip = None
    if broll:
        clip = broll[idx % len(broll)]
        scene["label"] = _label_for(cfg, clip)
    elif cfg["video"].get("use_pexels", True):
        q = scene.get("stock_query") or " ".join((scene.get("image_prompt") or scene["headline"]).split()[:5])
        clip = assets.pexels_clip(q, workdir, idx)
        if clip:
            scene["label"] = cfg["video"]["stock_label"]
    if clip and clip.suffix.lower() in assets.IMAGE_EXT:
        # imagem oficial (screenshot): Ken Burns sobre a imagem, mesma rota das ilustrações
        img = visuals._cover(Image.open(clip).convert("RGB"))
        png = workdir / f"scene_{idx:02d}.png"
        visuals._headline(img, cfg, scene["headline"], visuals._hex(scene.get("params", {}).get("accent", "#2ee6a6")))
        visuals._label(img, cfg, scene["label"])
        img.save(png)
        scene["broll"] = True
        clip = None
        used_ai = False
    elif clip:
        scene["broll"] = True
        ov = _overlay_png(cfg, scene, idx, workdir)
        start = random.Random(f"{clip}{idx}").uniform(0, 20)  # trecho diferente a cada cena
        vf = (f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps={fps},"
              f"eq=contrast=1.05:saturation=1.1[bg];[bg][1:v]overlay=0:0[o];[o]subtitles='{ass_path}',"
              f"fade=t=in:d=0.25,fade=t=out:st={max(dur - 0.25, 0):.2f}:d=0.25,format=yuv420p[v]")
        tmp, out = workdir / f"scene_{idx:02d}.tmp.mp4", workdir / f"scene_{idx:02d}.mp4"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-stream_loop", "-1", "-i", str(clip), "-i", str(ov),
              "-filter_complex", vf, "-map", "[v]", "-t", f"{dur:.3f}", *ENC, "-an", str(tmp)])
        os.replace(tmp, out)
        return out, False
    if not scene.get("broll"):
        png, used_ai = visuals.render_scene_image(cfg, scene, idx, workdir)
    # alterna zoom-in e pan lateral (movimento simples e barato)
    punch = "1.22-0.12*min(on/6,1)"  # entra com zoom forte e relaxa em 6 frames (corte com impacto)
    if idx % 2 == 0:
        z = f"zoompan=z='{punch}+0.0010*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={fps}"
    else:
        z = f"zoompan=z='{punch}+0.02':x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)':d={frames}:s=1080x1920:fps={fps}"
    vf = (f"scale=2160:3840:flags=lanczos,{z},subtitles='{ass_path}',"
          f"fade=t=in:d=0.25,fade=t=out:st={max(dur - 0.25, 0):.2f}:d=0.25,format=yuv420p")
    tmp, out = workdir / f"scene_{idx:02d}.tmp.mp4", workdir / f"scene_{idx:02d}.mp4"
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(png), "-vf", vf, "-t", f"{dur:.3f}", *ENC, "-an", str(tmp)])
    os.replace(tmp, out)
    return out, used_ai


def assemble(cfg: dict, scenes: list[dict], workdir: Path, final_path: Path, game: str | None = None,
             game_name: str | None = None) -> dict:
    files, ai_images = [], 0
    assets.sync_sources(cfg)
    broll = find_broll(game) if cfg["video"].get("use_own_broll", True) else []
    credit = None
    if not broll and cfg["video"].get("use_steam_official", True):
        broll, credit = assets.steam_official(game_name or (game or "").replace("-", " "), workdir)
        if broll:
            cfg["video"]["official_label"] = credit
    if broll:
        random.Random(final_path.name).shuffle(broll)
        broll = _mix_broll(broll, len(scenes))
        print(f"[broll] usando {len(broll)} arquivos de fundo para {game}")
    for i, sc in enumerate(scenes):
        f, used_ai = render_scene(cfg, sc, i, workdir, broll)
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
    return {"path": str(final_path), "seconds": round(total, 2), "scenes": len(scenes), "ai_images": ai_images, "broll_clips": len(broll)}
