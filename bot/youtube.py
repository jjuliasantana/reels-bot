"""Coleta de vídeos públicos recentes de games via YouTube Data API v3 (ou dados simulados)."""
import hashlib
import random
from datetime import datetime, timedelta, timezone
import requests
from .config import SECRETS

API = "https://www.googleapis.com/youtube/v3"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def search_recent(query: str, lookback_hours: int, max_results: int) -> list[dict]:
    """search.list (100 unidades de quota) + videos.list (1 unidade). Qualquer idioma/região."""
    key = SECRETS.youtube
    published_after = _iso(datetime.now(timezone.utc) - timedelta(hours=lookback_hours))
    r = requests.get(f"{API}/search", params={
        "part": "snippet", "q": query, "type": "video", "order": "viewCount",
        "publishedAfter": published_after, "maxResults": min(max_results, 50),
        "videoCategoryId": "20",  # Gaming
        "safeSearch": "moderate", "key": key,
    }, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    ids = [i["id"]["videoId"] for i in items]
    if not ids:
        return []
    r2 = requests.get(f"{API}/videos", params={
        "part": "snippet,statistics", "id": ",".join(ids), "key": key}, timeout=30)
    r2.raise_for_status()
    out = []
    for it in r2.json().get("items", []):
        sn, st = it["snippet"], it.get("statistics", {})
        out.append({
            "video_id": it["id"], "title": sn["title"], "channel_id": sn["channelId"],
            "channel_title": sn["channelTitle"], "published_at": sn["publishedAt"],
            "lang": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "und",
            "query": query, "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
            "comments": int(st.get("commentCount", 0)), "simulated": False,
        })
    return out


# ----------------------------------------------------------------------------------------------
# DADOS SIMULADOS (usados somente quando YOUTUBE_API_KEY não existe). Identificados por simulated=True
# e por IDs com prefixo "SIM". Os links gerados NÃO apontam para vídeos reais.
# ----------------------------------------------------------------------------------------------
_SIM_CLUSTERS = [
    # (assunto, [ (idioma, título, canal, views_base, growth_por_hora) ... ])
    ("gta6-map", [
        ("en", "GTA 6 map is WAY bigger than we thought (full analysis)", "SimCh LeonidasPlays", 410000, 18000),
        ("pt", "O MAPA DE GTA 6 É GIGANTE - comparação com GTA 5", "SimCh CanalDoGamer", 220000, 9500),
        ("es", "El mapa de GTA 6 comparado con Vice City original", "SimCh JuegosHoy", 150000, 7000),
        ("ru", "Карта GTA 6 — разбор всех районов", "SimCh ИгроМир", 120000, 5000),
        ("ja", "GTA6のマップが広すぎる件", "SimCh ゲーム速報", 90000, 4200),
        ("de", "GTA 6 Map: Alle Städte und Gebiete erklärt", "SimCh SpieleNews", 70000, 2800),
    ]),
    ("elden-ring-dlc-boss", [
        ("en", "This Elden Ring boss is impossible (new DLC)", "SimCh SoulsBorne", 300000, 6000),
        ("en", "Beating the hardest DLC boss hitless", "SimCh NoHitKing", 180000, 3000),
        ("fr", "Le nouveau boss du DLC d'Elden Ring", "SimCh JeuxVideoFR", 60000, 1500),
    ]),
    ("minecraft-update", [
        ("en", "NEW Minecraft update changes everything", "SimCh CraftDaily", 500000, 4000),
        ("pt", "Nova atualização do Minecraft explicada", "SimCh MineBR", 140000, 1200),
    ]),
    ("random-viral", [
        ("en", "I played the worst game on Steam", "SimCh ViralVic", 900000, 2500),
    ]),
]


def simulated_snapshot(hours_after_start: float, lookback_hours: int) -> list[dict]:
    rng = random.Random(42)
    now = datetime.now(timezone.utc)
    out = []
    for slug, vids in _SIM_CLUSTERS:
        for i, (lang, title, channel, base, growth) in enumerate(vids):
            vid = "SIM" + hashlib.md5(f"{slug}{i}".encode()).hexdigest()[:8]
            age_h = rng.uniform(6, lookback_hours - 4)
            views = int(base + growth * hours_after_start * rng.uniform(0.85, 1.15))
            out.append({
                "video_id": vid, "title": title, "channel_id": "SIMCH_" + channel.replace(" ", ""),
                "channel_title": channel, "published_at": _iso(now - timedelta(hours=age_h)),
                "lang": lang, "query": slug, "views": views, "likes": views // 40, "comments": views // 400,
                "simulated": True,
            })
    return out


def collect(cfg: dict, sim_hours: float | None = None) -> tuple[list[dict], bool]:
    """Retorna (vídeos, simulado?)."""
    mon = cfg["monitoring"]
    if not SECRETS.youtube:
        return simulated_snapshot(sim_hours or 0.0, mon["lookback_hours"]), True
    seen: dict[str, dict] = {}
    for q in mon["seed_topics"] + mon["generic_queries"]:
        for v in search_recent(q, mon["lookback_hours"], mon["max_results_per_query"]):
            if v["views"] >= mon["min_views_to_track"] and v["video_id"] not in seen:
                seen[v["video_id"]] = v
    return list(seen.values()), False
