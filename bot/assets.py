"""Material de fundo: (1) arquivos oficiais do publisher em assets/broll/<jogo>/ (vídeo OU imagem),
(2) links oficiais em assets/sources.txt baixados pelo bot (só domínios permitidos), (3) B-roll gratuito do Pexels."""
import hashlib
import re
from pathlib import Path
import requests
from .config import ROOT, env

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
BROLL = ROOT / "assets" / "broll"
SOURCES = ROOT / "assets" / "sources.txt"


def _allowed(url: str, cfg: dict) -> bool:
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    return any(host == d or host.endswith("." + d) for d in cfg["video"].get("official_domains", []))


def sync_sources(cfg: dict) -> int:
    """Baixa os links de assets/sources.txt (formato: <jogo> <url>) para assets/broll/<jogo>/. Só domínios oficiais."""
    if not SOURCES.exists():
        return 0
    n = 0
    for line in SOURCES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        game, url = parts[0], parts[1]
        if not _allowed(url, cfg):
            print(f"[fontes] ignorado (domínio não oficial): {url}")
            continue
        ext = Path(url.split("?")[0]).suffix.lower() or ".mp4"
        if ext not in VIDEO_EXT + IMAGE_EXT:
            ext = ".mp4"
        dest = BROLL / game / ("official_" + hashlib.md5(url.encode()).hexdigest()[:10] + ext)
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with requests.get(url, stream=True, timeout=300, headers={"User-Agent": "Mozilla/5.0"}) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for ch in r.iter_content(1 << 20):
                        f.write(ch)
                tmp.replace(dest); n += 1
                print(f"[fontes] baixado: {dest.name}")
        except Exception as e:
            print(f"[fontes] falha em {url}: {e}")
    return n


def local_assets(game: str | None) -> list[Path]:
    if not game:
        return []
    d = BROLL / game
    return sorted(p for p in d.glob("*") if p.suffix.lower() in VIDEO_EXT + IMAGE_EXT) if d.exists() else []


def pexels_clip(query: str, workdir: Path, idx: int) -> Path | None:
    """Vídeo real de banco gratuito (Pexels, licença livre). Requer PEXELS_API_KEY."""
    key = env("PEXELS_API_KEY")
    if not key:
        return None
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                         params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 8}, timeout=30)
        r.raise_for_status()
        vids = r.json().get("videos", [])
        if not vids:
            return None
        v = vids[idx % len(vids)]
        files = sorted(v["video_files"], key=lambda f: abs((f.get("height") or 0) - 1920))
        url = files[0]["link"]
        dest = workdir / f"pexels_{idx:02d}.mp4"
        with requests.get(url, stream=True, timeout=300) as rr:
            rr.raise_for_status()
            with open(dest, "wb") as f:
                for ch in rr.iter_content(1 << 20):
                    f.write(ch)
        print(f"[pexels] {query!r} → {v.get('url')}")
        return dest
    except Exception as e:
        print(f"[pexels] falhou: {e}")
        return None


# ---------------- Material oficial via Steam (trailer + screenshots da página da loja, enviados pela publisher) --------
STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/"
STEAM_APP = "https://store.steampowered.com/api/appdetails"


def steam_official(game_name: str, workdir: Path, max_videos: int = 1, max_images: int = 6) -> tuple[list[Path], str]:
    """Baixa trailer e screenshots oficiais do jogo na Steam. Retorna (arquivos, crédito)."""
    if not game_name or game_name.lower() in ("unknown", "none"):
        return [], ""
    try:
        r = requests.get(STEAM_SEARCH, params={"term": game_name, "cc": "us", "l": "en"}, timeout=30)
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            return [], ""
        appid = items[0]["id"]
        r = requests.get(STEAM_APP, params={"appids": appid, "cc": "us", "l": "en"}, timeout=30)
        r.raise_for_status()
        data = r.json()[str(appid)]["data"]
        dev = ", ".join(data.get("developers") or data.get("publishers") or ["the publisher"])
        out = []
        for i, m in enumerate((data.get("movies") or [])[:max_videos]):
            url = (m.get("mp4") or {}).get("480") or (m.get("mp4") or {}).get("max")
            if url:
                out.append(_download(url, workdir / f"official_steam_{appid}_v{i}.mp4"))
        for i, sc in enumerate((data.get("screenshots") or [])[:max_images]):
            url = sc.get("path_full")
            if url:
                out.append(_download(url, workdir / f"official_steam_{appid}_s{i}.jpg"))
        out = [p for p in out if p]
        if out:
            print(f"[steam] {data.get('name')} (app {appid}): {len(out)} arquivos oficiais")
        return out, f"Official media © {dev}"
    except Exception as e:
        print(f"[steam] falhou para {game_name!r}: {e}")
        return [], ""


def _download(url: str, dest: Path) -> Path | None:
    try:
        if dest.exists():
            return dest
        with requests.get(url, stream=True, timeout=300, headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as f:
                for ch in r.iter_content(1 << 20):
                    f.write(ch)
            tmp.replace(dest)
        return dest
    except Exception as e:
        print(f"[download] falhou {url}: {e}")
        return None
