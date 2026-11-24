"""Ilustrações ORIGINAIS estilizadas, geradas proceduralmente (PIL/numpy) — nada é baixado de terceiros.
Opcional: fundo gerado por IA (OpenAI gpt-image) quando video.image_generation == 'openai'."""
import base64
import math
import random
from pathlib import Path
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from .config import SECRETS

W, H = 1080, 1920
BG = (10, 12, 20)


def find_font(cfg: dict, size: int) -> ImageFont.FreeTypeFont:
    for p in cfg["video"]["font_candidates"]:
        if Path(p).exists():
            try:
                f = ImageFont.truetype(p, size)
                try:
                    f.set_variation_by_name("Bold")
                except Exception:
                    pass
                return f
            except Exception:
                continue
    return ImageFont.load_default(size)


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _gradient(top: tuple, bottom: tuple) -> Image.Image:
    a = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(top) * (1 - a) + np.array(bottom) * a).astype(np.uint8)
    return Image.fromarray(np.repeat(arr, W, axis=1), "RGB")


def _glow(img: Image.Image, draw_fn, radius=40, alpha=0.8):
    layer = Image.new("RGB", img.size, (0, 0, 0))
    draw_fn(ImageDraw.Draw(layer))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    return Image.blend(img, Image.fromarray(np.clip(np.array(img, int) + np.array(layer, int) * alpha, 0, 255).astype(np.uint8)), 1.0)


def _value_noise(rng, shape, scale=8):
    small = rng.random((shape[0] // scale + 2, shape[1] // scale + 2))
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((shape[1], shape[0]), Image.BICUBIC)
    return np.array(img) / 255.0


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def _headline(img, cfg, text, accent, y=300):
    d = ImageDraw.Draw(img)
    font = find_font(cfg, 96)
    lines = _wrap(d, text.upper(), font, W - 160)
    for i, line in enumerate(lines):
        tw = d.textlength(line, font=font)
        x, yy = (W - tw) / 2, y + i * 112
        d.text((x, yy), line, font=font, fill=(0, 0, 0), stroke_width=10, stroke_fill=(0, 0, 0))
        d.text((x, yy), line, font=font, fill=(255, 255, 255) if i == 0 else accent, stroke_width=0)
    # faixa de acento
    d.rectangle([80, y - 36, 80 + 160, y - 22], fill=accent)


def _label(img, cfg, text):
    d = ImageDraw.Draw(img)
    f = find_font(cfg, 30)
    tw = d.textlength(text, font=f)
    d.rounded_rectangle([(W - tw) / 2 - 24, 200, (W + tw) / 2 + 24, 256], radius=14, fill=(16, 16, 20))
    d.text(((W - tw) / 2, 208), text, font=f, fill=(230, 230, 230))


# ---------------- templates ----------------
def t_title_card(rng, accent):
    img = _gradient((18, 14, 40), BG)
    d = ImageDraw.Draw(img)
    for i in range(-6, 14):
        x = i * 220
        d.polygon([(x, H), (x + 120, H), (x + 1200, 0), (x + 1080, 0)], fill=(accent if i % 3 == 0 else (24, 26, 44)))
    img = img.filter(ImageFilter.GaussianBlur(1))
    img = _glow(img, lambda g: g.ellipse([W / 2 - 300, 900, W / 2 + 300, 1500], fill=accent), 120, 0.5)
    return img


def t_map(rng, accent):
    """Mapa fictício de mundo aberto: costa suave, estradas, pontos de interesse."""
    img = _gradient((8, 24, 40), (6, 14, 28))
    land = _value_noise(rng, (H, W), 220) * 0.7 + _value_noise(rng, (H, W), 90) * 0.3
    land = np.array(Image.fromarray((land * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(18))) / 255.0
    mask = land > 0.5
    arr = np.array(img)
    arr[mask] = (36, 48, 50)
    shallow = (land > 0.44) & ~mask
    arr[shallow] = (18, 48, 70)
    coast = np.array(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.FIND_EDGES).filter(ImageFilter.MaxFilter(5)))
    arr[coast > 0] = (150, 200, 215)
    img = Image.fromarray(arr)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 135):
        d.line([(x, 0), (x, H)], fill=(40, 56, 70), width=1)
    for y in range(0, H, 135):
        d.line([(0, y), (W, y)], fill=(40, 56, 70), width=1)
    nodes = [(int(rng.integers(100, W - 100)), int(rng.integers(520, H - 320))) for _ in range(22)]
    for a in nodes:  # rede de estradas fictícia
        for b in sorted(nodes, key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)[1:3]:
            d.line([a, b], fill=(225, 200, 130), width=6)
    for (x, y) in nodes[:8]:  # distritos / pontos de interesse
        d.ellipse([x - 18, y - 18, x + 18, y + 18], fill=accent, outline=(0, 0, 0), width=4)
    return _glow(img, lambda g: [g.ellipse([x - 24, y - 24, x + 24, y + 24], fill=accent) for (x, y) in nodes[:8]], 30, 0.6)


def t_cityscape(rng, accent):
    img = _gradient((40, 16, 60), (8, 8, 18))
    img = _glow(img, lambda g: g.ellipse([W / 2 - 260, 620, W / 2 + 260, 1140], fill=accent), 80, 0.7)
    d = ImageDraw.Draw(img)
    d.ellipse([W / 2 - 220, 660, W / 2 + 220, 1100], fill=accent)
    for layer, (col, base) in enumerate([((28, 22, 50), 1250), ((18, 16, 36), 1420), (BG, 1600)]):
        x = -40
        while x < W + 40:
            w = int(rng.integers(70, 200)); h = int(rng.integers(200, 700)) - layer * 60
            d.rectangle([x, base - h, x + w, H], fill=col)
            for wx in range(x + 12, x + w - 12, 28):
                for wy in range(base - h + 20, base - 20, 36):
                    if rng.random() < 0.35:
                        d.rectangle([wx, wy, wx + 12, wy + 16], fill=(255, 220, 140))
            x += w + int(rng.integers(6, 30))
    return img


def t_stat_bars(rng, accent):
    img = _gradient((12, 18, 30), BG)
    d = ImageDraw.Draw(img)
    vals = sorted(rng.random(7))
    for i, v in enumerate(vals):
        x = 140 + i * 120; h = int(300 + v * 800)
        d.rounded_rectangle([x, 1500 - h, x + 80, 1500], radius=20, fill=accent if i == len(vals) - 1 else (50, 60, 90))
    d.line([(120, 1500), (W - 120, 1500)], fill=(120, 130, 160), width=4)
    img = _glow(img, lambda g: g.rounded_rectangle([140 + 6 * 120, 1500 - int(300 + vals[-1] * 800), 140 + 6 * 120 + 80, 1500], radius=20, fill=accent), 50, 0.6)
    return img


def t_grid_abstract(rng, accent):
    img = _gradient((20, 10, 40), BG)
    d = ImageDraw.Draw(img)
    hz = 1050
    for i in range(-10, 11):
        d.line([(W / 2 + i * 60, hz), (W / 2 + i * 400, H)], fill=accent, width=3)
    for k in range(1, 14):
        y = hz + (k ** 2) * 5
        if y < H:
            d.line([(0, y), (W, y)], fill=accent, width=2)
    img = _glow(img, lambda g: g.rectangle([0, hz - 10, W, hz + 10], fill=accent), 60, 0.8)
    return img


def t_orbit(rng, accent):
    img = _gradient((10, 20, 36), BG)
    d = ImageDraw.Draw(img)
    cx, cy = W / 2, 1120
    for r in (180, 320, 460):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(60, 80, 110), width=3)
    pts = []
    for r in (180, 320, 460):
        for k in range(5):
            a = rng.random() * 2 * math.pi
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    for p in pts:
        d.line([(cx, cy), p], fill=(60, 90, 120), width=2)
        d.ellipse([p[0] - 14, p[1] - 14, p[0] + 14, p[1] + 14], fill=accent)
    d.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], fill=(255, 255, 255))
    return _glow(img, lambda g: g.ellipse([cx - 60, cy - 60, cx + 60, cy + 60], fill=accent), 70, 0.8)


TEMPLATES = {"title_card": t_title_card, "map": t_map, "cityscape": t_cityscape, "stat_bars": t_stat_bars,
             "grid_abstract": t_grid_abstract, "orbit": t_orbit}


def _openai_background(prompt: str) -> Image.Image | None:
    try:
        r = requests.post("https://api.openai.com/v1/images/generations",
                          headers={"Authorization": f"Bearer {SECRETS.openai}"},
                          json={"model": "gpt-image-1", "prompt": prompt, "size": "1024x1536", "quality": "low"}, timeout=180)
        r.raise_for_status()
        b = base64.b64decode(r.json()["data"][0]["b64_json"])
        import io
        return Image.open(io.BytesIO(b)).convert("RGB").resize((W, H))
    except Exception:
        return None


def _gemini_background(cfg: dict, prompt: str) -> Image.Image | None:
    """Imagem pelo modelo de imagem do Gemini (cota gratuita). Nome do modelo detectado via models.list."""
    try:
        import io
        from . import llm
        r = requests.get(f"{llm.GEMINI}/models", params={"key": SECRETS.gemini, "pageSize": 1000}, timeout=30)
        r.raise_for_status()
        names = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
                 if "generateContent" in m.get("supportedGenerationMethods", []) and "image" in m["name"]
                 and "preview" not in m["name"]]
        names = names or [m["name"].removeprefix("models/") for m in r.json().get("models", []) if "image" in m["name"]]
        if not names:
            return None
        model = cfg["video"].get("gemini_image_model") if cfg["video"].get("gemini_image_model") in names else sorted(names, reverse=True)[0]
        r = requests.post(f"{llm.GEMINI}/models/{model}:generateContent", params={"key": SECRETS.gemini},
                          json={"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}},
                          timeout=180)
        r.raise_for_status()
        for part in r.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                img = Image.open(io.BytesIO(base64.b64decode(part["inlineData"]["data"]))).convert("RGB")
                return _cover(img)
    except Exception as e:
        print(f"[aviso] imagem Gemini falhou: {e}")
    return None


def _cover(img: Image.Image) -> Image.Image:
    """Redimensiona cobrindo 1080x1920 sem distorcer (corte central)."""
    s = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def render_scene_image(cfg: dict, scene: dict, idx: int, workdir: Path) -> tuple[Path, bool]:
    """Retorna (png, usou_imagem_IA?)."""
    rng = np.random.default_rng(1000 + idx)
    accent = _hex(scene.get("params", {}).get("accent", "#2ee6a6"))
    used_ai = False
    img = None
    prompt = scene.get("image_prompt") or f"theme: {scene['headline']}"
    style = (" Original stylized painterly concept-art illustration for a gaming short, vertical 9:16, moody cinematic "
             "lighting, rich colors. No text, no letters, no logos, no watermarks, no real game characters, vehicles or "
             "trademarked designs.")
    max_ai = int(cfg["video"].get("max_ai_images_per_video", 3))
    if cfg["video"]["image_generation"] == "gemini" and SECRETS.gemini and idx < max_ai:
        img = _gemini_background(cfg, prompt + style)
        used_ai = img is not None
    if img is None and cfg["video"]["image_generation"] == "openai" and SECRETS.openai:
        img = _openai_background(
            f"Original stylized flat illustration for a gaming explainer, vertical, moody dark palette with accent "
            f"color {scene.get('params', {}).get('accent')}, theme: {scene['headline']}. No text, no logos, no real "
            f"game characters or branded content.")
        used_ai = img is not None
    if img is None:
        img = TEMPLATES.get(scene["template"], t_grid_abstract)(rng, accent)
    # vinheta para legibilidade
    vign = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vign).rectangle([0, 0, W, H], fill=0)
    arr = np.array(img).astype(float)
    yy = np.linspace(0, 1, H)[:, None]
    fade = np.clip(1.15 - 0.55 * np.exp(-((yy - 0.17) ** 2) / 0.01) - 0.6 * np.exp(-((yy - 0.86) ** 2) / 0.006), 0.35, 1.0)
    img = Image.fromarray((arr * fade[:, :, None]).astype(np.uint8))
    _headline(img, cfg, scene["headline"], accent)
    _label(img, cfg, cfg["video"]["illustration_label"] if not scene.get("broll") else cfg["video"]["broll_label"])
    out = workdir / f"scene_{idx:02d}.png"
    img.save(out)
    return out, used_ai
