"""Métricas do próprio perfil (Instagram Insights) → prior para as próximas pautas."""
import json
import requests
from .config import SECRETS
from . import db

GRAPH = "https://graph.facebook.com/v21.0"


def fetch_and_store(con) -> int:
    """Coleta métricas dos Reels publicados pelo bot. Retorna quantos atualizou."""
    if not (SECRETS.ig_token and SECRETS.ig_user_id):
        return 0
    rows = con.execute("SELECT ig_media_id FROM posts WHERE status='published' AND ig_media_id IS NOT NULL").fetchall()
    n = 0
    for r in rows:
        mid = r["ig_media_id"]
        try:
            m = requests.get(f"{GRAPH}/{mid}/insights", params={
                "metric": "plays,reach,likes,saved,shares,comments", "access_token": SECRETS.ig_token}, timeout=30).json()
            vals = {d["name"]: (d.get("values") or [{}])[0].get("value", 0) for d in m.get("data", [])}
            con.execute("INSERT OR REPLACE INTO insights VALUES(?,?,?,?,?,?,?,?)",
                        (mid, db.now_iso(), vals.get("plays", 0), vals.get("reach", 0), vals.get("likes", 0),
                         vals.get("saved", 0), vals.get("shares", 0), vals.get("comments", 0)))
            n += 1
        except Exception:
            continue
    con.commit()
    return n


def prior_by_game(con) -> dict[str, float]:
    """Bônus (-1..+1) por jogo: desempenho relativo (plays+5*saves+3*shares) vs. mediana do perfil."""
    rows = con.execute("""
        SELECT p.evidence_json, i.plays, i.saves, i.shares FROM posts p JOIN insights i ON i.ig_media_id=p.ig_media_id
        WHERE i.taken_at = (SELECT MAX(taken_at) FROM insights WHERE ig_media_id=p.ig_media_id)""").fetchall()
    if len(rows) < 3:
        return {}
    scores = []
    for r in rows:
        ev = json.loads(r["evidence_json"] or "{}")
        scores.append((ev.get("game"), (r["plays"] or 0) + 5 * (r["saves"] or 0) + 3 * (r["shares"] or 0)))
    med = sorted(s for _, s in scores)[len(scores) // 2] or 1
    out: dict[str, list] = {}
    for g, s in scores:
        out.setdefault(g, []).append(max(-1.0, min(1.0, (s - med) / med)))
    return {g: sum(v) / len(v) for g, v in out.items() if g}
