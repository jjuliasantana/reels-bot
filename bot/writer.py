"""Transforma a tendência em pauta original + roteiro (inglês americano, tom de criador gamer)."""
import json
from . import llm

GAME_DISPLAY = {"gta": "GTA 6", "elden-ring": "Elden Ring", "call-of-duty": "Call of Duty", "league-of-legends": "League of Legends",
                "counter-strike": "Counter-Strike", "red-dead": "Red Dead", "baldurs-gate": "Baldur's Gate", "the-witcher": "The Witcher"}
VISUAL_TEMPLATES = ["title_card", "map", "cityscape", "stat_bars", "grid_abstract", "orbit"]

SYSTEM = """You are a sharp, funny American gaming creator writing a 30–45 second vertical Reel.
Rules:
- Use third-party videos ONLY as a trend signal. Never describe, quote or reuse their footage, thumbnails or audio.
- Pick an ORIGINAL angle on the topic (an insight, a 'why', a comparison, a design lesson), not a recap of the videos.
- Only state facts that are widely confirmed by official sources (publisher, developer, official store pages). Anything
  unconfirmed must be flagged in the narration as a rumor ("rumor has it", "reportedly", "not confirmed").
- Hook in the first 2 seconds. Short punchy sentences. Natural spoken US English. No emojis in narration.
- Total narration 70–110 words (≈30–45 s at normal pace).
- Visuals are ORIGINAL stylized illustrations rendered by our own engine — choose templates from this list only:
  title_card, map, cityscape, stat_bars, grid_abstract, orbit. Give each scene a 3–7 word on-screen headline.
Return JSON:
{"angle": "...", "title": "...", "rumor_flags": ["..."], "claims": [{"claim": "...", "status": "confirmed|rumor", "source_hint": "..."}],
 "scenes": [{"narration": "...", "headline": "...", "template": "map", "params": {"accent": "#hex"}}],
 "caption": "<Instagram caption in US English, 2-3 lines + CTA>", "hashtags": ["#..."]}"""


def _fallback_script(trend: dict) -> dict:
    """Roteiro-modelo quando não há LLM (claramente identificado como fallback)."""
    game = GAME_DISPLAY.get(trend.get("game") or "", (trend.get("game") or "this game").replace("-", " ").title())
    sub = trend.get("subtopic") or "general"
    if sub == "map":
        return {
            "angle": "Why some open-world maps feel bigger than they are",
            "title": f"Why {game}'s map feels bigger than it is",
            "rumor_flags": ["Exact map size is not officially confirmed"],
            "claims": [{"claim": "Map size numbers circulating online", "status": "rumor", "source_hint": "No official figure released"}],
            "scenes": [
                {"narration": "Everyone's arguing about how big this map is. That's the wrong question, and here's why.", "headline": "WRONG QUESTION", "template": "title_card", "params": {"accent": "#ff5f3c"}},
                {"narration": "A map doesn't feel big because of square miles. It feels big because of density, travel time, and how often something stops you.", "headline": "DENSITY BEATS SIZE", "template": "map", "params": {"accent": "#2ee6a6"}},
                {"narration": "Fewer straight roads, more elevation, more detours pulling you off the path. Your brain counts decisions, not miles, so the world stretches.", "headline": "CURVES STRETCH DISTANCE", "template": "cityscape", "params": {"accent": "#58a6ff"}},
                {"narration": "And any exact size number you've seen online? That's a rumor until the studio confirms it. Follow for the next breakdown.", "headline": "RUMOR UNTIL CONFIRMED", "template": "stat_bars", "params": {"accent": "#ffd166"}},
            ],
            "caption": f"Why {game}'s map feels bigger than it actually is. Size numbers are rumors until confirmed.\nFollow for daily game breakdowns.",
            "hashtags": ["#gaming", "#openworld", "#gamedesign"],
        }
    return {
        "angle": f"What the {game} {sub} hype says about how we play",
        "title": f"The real reason {game} is everywhere right now",
        "rumor_flags": ["Details not confirmed by the developer are treated as rumors"],
        "claims": [],
        "scenes": [
            {"narration": f"{game} is suddenly everywhere. Here's the part nobody explains.", "headline": "EVERYWHERE RIGHT NOW", "template": "title_card", "params": {"accent": "#ff5f3c"}},
            {"narration": "Big moments in games spread across languages before they spread across channels. That's the tell.", "headline": "SPREADS ACROSS LANGUAGES", "template": "orbit", "params": {"accent": "#2ee6a6"}},
            {"narration": "When a topic grows on independent channels at the same time, it's real momentum, not one creator's push.", "headline": "REAL MOMENTUM", "template": "stat_bars", "params": {"accent": "#58a6ff"}},
            {"narration": "Anything not confirmed by the studio is still a rumor. Follow for the next one.", "headline": "RUMOR UNTIL CONFIRMED", "template": "grid_abstract", "params": {"accent": "#ffd166"}},
        ],
        "caption": f"The real reason {game} is everywhere right now.\nFollow for daily game breakdowns.",
        "hashtags": ["#gaming", "#gamenews"],
    }


def write_script(cfg: dict, trend: dict) -> tuple[dict, bool]:
    """Retorna (roteiro, gerado_por_llm?)."""
    if not llm.available(cfg):
        s = _fallback_script(trend)
        s["generated_by"] = "fallback-template (sem LLM configurado)"
        return s, False
    user = json.dumps({
        "trend_label": trend["label"], "game": trend["game"], "subtopic": trend["subtopic"],
        "signal": {"views_per_hour": trend["views_per_hour"], "independent_channels": trend["independent_channels"],
                   "languages": trend["languages"]},
        "titles_seen_for_context_only": [e["title"] for e in trend["evidence"][:8]],
    }, ensure_ascii=False)
    try:
        s = llm.chat_json(cfg, SYSTEM, user, max_tokens=1800)
        assert s.get("scenes") and s.get("caption") and s.get("angle")
    except Exception as e:
        print(f"[aviso] roteiro por LLM falhou ({e}); usando roteiro-modelo")
        s = _fallback_script(trend); s["generated_by"] = f"fallback-template (LLM falhou: {str(e)[:80]})"
        return s, False
    for sc in s["scenes"]:
        if sc.get("template") not in VISUAL_TEMPLATES:
            sc["template"] = "grid_abstract"
        sc.setdefault("params", {}).setdefault("accent", "#2ee6a6")
    s["generated_by"] = f"llm:{llm.available(cfg)}"
    return s, True


def word_count(script: dict) -> int:
    return sum(len(sc["narration"].split()) for sc in script["scenes"])
