"""Agrupa vídeos sobre o mesmo assunto (mesmo em idiomas diferentes) e pontua cada tendência."""
import math
import re
import unicodedata
from datetime import datetime, timezone
import numpy as np
from . import llm

# Fallback sem embeddings: dicionário multilíngue de jogos e subtemas.
GAME_ALIASES = {
    "gta": ["gta", "grand theft auto", "гта", "グランド・セフト・オート", "gta6", "gta 6", "gta vi", "gta5", "gta 5"],
    "elden-ring": ["elden ring", "элден ринг", "エルデンリング"],
    "minecraft": ["minecraft", "майнкрафт", "マインクラフト", "마인크래프트"],
    "fortnite": ["fortnite", "фортнайт", "フォートナイト"],
    "roblox": ["roblox", "роблокс"],
    "call-of-duty": ["call of duty", "cod ", "warzone", "黑色行动", "колда"],
    "valorant": ["valorant", "валорант"],
    "league-of-legends": ["league of legends", " lol ", "лол", "リーグ・オブ・レジェンド"],
    "zelda": ["zelda", "ゼルダ"],
    "pokemon": ["pokemon", "pokémon", "ポケモン", "покемон"],
    "hollow-knight": ["hollow knight", "silksong"],
    "counter-strike": ["cs2", "counter-strike", "counter strike", "кс2"],
    "red-dead": ["red dead", "rdr2", "rdr 2"],
    "cyberpunk": ["cyberpunk"],
    "the-witcher": ["witcher", "ведьмак", "wiedźmin"],
    "starfield": ["starfield"],
    "helldivers": ["helldivers"],
    "baldurs-gate": ["baldur"],
    "battlefield": ["battlefield"],
    "steam": ["steam"],
}
SUBTOPIC_ALIASES = {
    "map": ["map", "mapa", "карта", "マップ", "karte", "carte", "地图", "지도", "harita"],
    "trailer": ["trailer", "tráiler", "трейлер", "トレーラー"],
    "leak": ["leak", "vazamento", "filtración", "слив", "リーク", "rumor", "rumour"],
    "update": ["update", "atualização", "actualización", "обновление", "アップデート", "patch", "mise à jour"],
    "release-date": ["release date", "data de lançamento", "fecha de lanzamiento", "дата выхода", "発売日"],
    "boss": ["boss", "chefe", "jefe", "босс", "ボス"],
    "dlc": ["dlc", "expansion", "expansão", "expansión"],
    "mod": ["mod ", "mods", "мод "],
    "glitch": ["glitch", "bug", "баг", "バグ"],
    "price": ["price", "preço", "precio", "цена", "価格", "$"],
}
GLOBAL_GAMES = set(GAME_ALIASES)  # jogos com público global de língua inglesa


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return " " + re.sub(r"[^\w\s$]", " ", s) + " "


def _detect(text: str, table: dict) -> str | None:
    t = _norm(text)
    for key, aliases in table.items():
        if any(_norm(a).strip() in t or a in t for a in aliases):
            return key
    return None


def _fallback_clusters(videos: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for v in videos:
        game = _detect(v["title"], GAME_ALIASES)
        sub = _detect(v["title"], SUBTOPIC_ALIASES)
        if not game and not sub:
            continue  # assunto não identificado sem LLM
        key = f"{game or 'unknown'}:{sub or 'general'}"
        groups.setdefault(key, []).append(v)
    return groups


def _embedding_clusters(videos: list[dict], provider: str, cfg: dict, threshold: float = 0.72) -> dict[str, list[dict]] | None:
    vecs = llm.embeddings([v["title"] for v in videos], provider, cfg)
    if vecs is None:
        return None
    X = np.array(vecs)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    labels = [-1] * len(videos)
    centroids: list[np.ndarray] = []
    for i, x in enumerate(X):  # clustering incremental simples (greedy) — barato e suficiente aqui
        best, bi = -1.0, -1
        for j, c in enumerate(centroids):
            s = float(x @ c / np.linalg.norm(c))
            if s > best:
                best, bi = s, j
        if best >= threshold:
            labels[i] = bi
            centroids[bi] = centroids[bi] + x
        else:
            labels[i] = len(centroids)
            centroids.append(x.copy())
    groups: dict[str, list[dict]] = {}
    for v, l in zip(videos, labels):
        groups.setdefault(f"emb-{l}", []).append(v)
    return groups


def _label_with_llm(cfg: dict, groups: dict[str, list[dict]]) -> dict[str, dict]:
    """Rótulo em inglês para cada cluster (jogo + subtema), via LLM quando disponível."""
    labels = {}
    if not llm.available(cfg):
        for k in groups:
            game, _, sub = k.partition(":")
            labels[k] = {"label": f"{game.upper() if len(game) <= 3 else game.replace('-', ' ').title()} — {sub}", "game": game, "subtopic": sub}
        return labels
    payload = {k: [v["title"] for v in vs[:6]] for k, vs in groups.items()}
    try:
        out = _llm_labels(cfg, payload)
    except Exception as e:  # LLM fora do ar / modelo inexistente → não derruba a execução
        print(f"[aviso] rotulagem por LLM falhou ({e}); usando rótulos por dicionário")
        out = {}
    for k in groups:
        lab = out.get(k)
        if not lab:
            if k.startswith("emb-"):  # cluster por embeddings sem rótulo do LLM → detecta pelo título mais visto
                t0 = groups[k][0]["title"]
                k = f"{_detect(t0, GAME_ALIASES) or 'unknown'}:{_detect(t0, SUBTOPIC_ALIASES) or 'general'}"
            game, _, sub = k.partition(":")
            lab = {"label": f"{game.upper() if len(game) <= 3 else game.replace('-', ' ').title()} — {sub}", "game": game, "subtopic": sub}
        labels[k] = lab
    return labels


def _llm_labels(cfg, payload):
    return llm.chat_json(cfg,
        "You label clusters of YouTube gaming video titles (any language). For each cluster id, return "
        '{"<id>": {"label": "<short English topic, e.g. GTA 6 map size>", "game": "<game slug>", "game_name": "<official game title, e.g. Grand Theft Auto VI>", "subtopic": "<slug>", '
        '"english_fit": <0..1 how relevant to a US gaming audience>}}',
        str(payload), max_tokens=2000)


def _hours_between(a: str, b: str) -> float:
    da, db_ = datetime.fromisoformat(a.replace("Z", "+00:00")), datetime.fromisoformat(b.replace("Z", "+00:00"))
    return max((db_ - da).total_seconds() / 3600.0, 1e-6)


def score_clusters(cfg: dict, videos: list[dict], insights_prior: dict | None = None) -> list[dict]:
    """videos: cada um com 'snapshots' [{taken_at, views}]. Retorna tendências ordenadas por score."""
    sel, w = cfg["selection"], cfg["selection"]["weights"]
    groups = None
    if cfg["ai"]["embeddings"] in ("gemini", "openai"):
        try:
            groups = _embedding_clusters(videos, cfg["ai"]["embeddings"], cfg)
        except Exception:
            groups = None
    if groups is None:
        groups = _fallback_clusters(videos)
    labels = _label_with_llm(cfg, groups)
    now = datetime.now(timezone.utc).isoformat()
    trends = []
    for key, vs in groups.items():
        growth_vph, proxy_vph, confirmed_videos = 0.0, 0.0, 0
        for v in vs:
            snaps = sorted(v["snapshots"], key=lambda s: s["taken_at"])
            if len(snaps) >= 2 and snaps[-1]["taken_at"] != snaps[0]["taken_at"]:
                growth_vph += (snaps[-1]["views"] - snaps[0]["views"]) / _hours_between(snaps[0]["taken_at"], snaps[-1]["taken_at"])
                confirmed_videos += 1
            proxy_vph += snaps[-1]["views"] / _hours_between(v["published_at"], now)
        preliminary = confirmed_videos < max(1, len(vs) // 2)
        vph = proxy_vph if preliminary else growth_vph
        channels = {v["channel_id"] for v in vs}
        langs = {(v.get("lang") or "und")[:2] for v in vs}
        lab = labels[key]
        english_fit = lab.get("english_fit")
        if english_fit is None:
            english_fit = 1.0 if "en" in langs else (0.6 if lab.get("game") in GLOBAL_GAMES else 0.3)
        slug = f"{lab.get('game','unknown')}-{lab.get('subtopic','general')}"
        bonus = (insights_prior or {}).get(lab.get("game"), 0.0)
        score = (w["growth"] * math.log1p(max(vph, 0)) + w["channels"] * math.log1p(len(channels))
                 + w["languages"] * math.log1p(len(langs)) + w["english_fit"] * english_fit
                 + w["insights_bonus"] * bonus)
        total_views = sum(sorted(v["snapshots"], key=lambda s: s["taken_at"])[-1]["views"] for v in vs)
        trends.append({
            "key": key, "slug": slug, "label": lab["label"], "game": lab.get("game"), "subtopic": lab.get("subtopic"),
            "game_name": lab.get("game_name") or (lab.get("game") or "").replace("-", " "),
            "score": round(score, 3), "views_per_hour": round(vph), "preliminary": preliminary,
            "independent_channels": len(channels), "languages": sorted(langs), "total_views": total_views,
            "english_fit": english_fit, "insights_bonus": bonus,
            "evidence": [{
                "url": f"https://www.youtube.com/watch?v={v['video_id']}", "title": v["title"], "channel": v["channel_title"],
                "lang": v.get("lang"), "published_at": v["published_at"], "simulated": bool(v.get("simulated")),
                "snapshots": sorted(v["snapshots"], key=lambda s: s["taken_at"]),
            } for v in sorted(vs, key=lambda v: -v["snapshots"][-1]["views"])],
        })
    trends.sort(key=lambda t: -t["score"])
    return trends


def pick(cfg: dict, trends: list[dict], recent_topics: list[dict]) -> tuple[dict | None, str]:
    """Escolhe a pauta ou devolve (None, motivo) para pular."""
    sel = cfg["selection"]
    recent = {t["topic_slug"] for t in recent_topics}
    for t in trends:
        why = []
        if t["slug"] in recent or any(t["game"] and r.startswith(str(t["game"])) and t["subtopic"] in r for r in recent):
            why.append("pauta parecida já publicada recentemente")
        if t["independent_channels"] < sel["min_independent_channels"]:
            why.append(f"só {t['independent_channels']} canais independentes")
        if t["total_views"] < sel["min_cluster_views"]:
            why.append("poucas visualizações no cluster")
        if t["preliminary"] and not sel["allow_preliminary_post"]:
            why.append("sinal preliminar (uma coleta só)")
        if not t["preliminary"] and t["views_per_hour"] < sel["min_growth_views_per_hour"]:
            why.append("crescimento abaixo do mínimo")
        t["rejection_reasons"] = why
        if not why:
            return t, "ok"
    return None, "nenhuma tendência passou nos critérios"
