"""Transforma a tendência em pauta original + roteiro (inglês americano, tom de criador gamer)."""
import json
from . import llm

GAME_DISPLAY = {"gta": "GTA 6", "elden-ring": "Elden Ring", "call-of-duty": "Call of Duty", "league-of-legends": "League of Legends",
                "counter-strike": "Counter-Strike", "red-dead": "Red Dead", "baldurs-gate": "Baldur's Gate", "the-witcher": "The Witcher"}
VISUAL_TEMPLATES = ["title_card", "map", "cityscape", "stat_bars", "grid_abstract", "orbit"]

SYSTEM = """You are a sharp, funny American gaming creator making a 30–45 second vertical short in the "did you know" /
gaming-curiosities style (think: "3 things about X you never noticed").
Format (exactly this structure):
- Scene 1 HOOK (≤ 12 words): a bold, slightly cheeky claim or question that makes people stop scrolling
  ("This map is lying to you.", "Nobody talks about this glitch." ). No "hey guys", no "did you know".
- Scenes 2–4: THREE surprising, specific, true facts/curiosities tied to the trend. Each one concrete (a number, a detail,
  a hidden mechanic, a dev decision, an easter egg, a record). Short punchy sentences.
- Before the last fact, tease it ("and the last one is the weird one"). Scene 5: a twist or a punchline + CTA ("Follow for more").
- Tone: confident, funny, a little sarcastic, like a friend who knows too much about games. Use "you". Vary rhythm:
  one-word sentences are welcome ("Wrong.", "Nope.").
Rules:
- Use third-party videos ONLY as a trend signal. Never describe, quote or reuse their footage, thumbnails or audio.
- Only state facts you are confident are widely confirmed (publisher/developer/official sources). Anything unconfirmed
  must be flagged in the narration ("rumor has it", "reportedly", "not confirmed yet"). Never invent numbers.
- Natural spoken US English, creator energy, no emojis in narration. Total narration 80–110 words (≈35–45 s).
- For each scene write an image_prompt: a vivid, original illustration idea in a stylized painterly/concept-art
  look, vertical composition, moody lighting, NO text, NO logos, NO real characters or trademarked designs, and
  described generically (e.g. "neon-lit coastal city at night from above", not "Vice City").
- Each scene also gets a 3–6 word on-screen headline (ALL CAPS) and a fallback template from:
  title_card, map, cityscape, stat_bars, grid_abstract, orbit.
Return JSON:
{"angle": "...", "title": "...", "rumor_flags": ["..."], "claims": [{"claim": "...", "status": "confirmed|rumor", "source_hint": "..."}],
 "scenes": [{"narration": "...", "headline": "...", "image_prompt": "...", "template": "map", "params": {"accent": "#hex"}}],
 "caption": "<Instagram/TikTok caption, 2-3 lines + CTA>", "hashtags": ["#..."]}"""


def _fallback_script(trend: dict) -> dict:
    """Roteiro-modelo quando não há LLM (claramente identificado como fallback)."""
    game = GAME_DISPLAY.get(trend.get("game") or "", (trend.get("game") or "this game").replace("-", " ").title())
    sub = trend.get("subtopic") or "general"
    if sub == "map":
        return {
            "angle": "Three things about open-world maps most players never notice",
            "title": f"3 things about {game}'s map you never noticed",
            "rumor_flags": ["Exact map size is not officially confirmed"],
            "claims": [{"claim": "Map size numbers circulating online", "status": "rumor", "source_hint": "No official figure released"}],
            "scenes": [
                {"narration": f"Three things about {game}'s map that almost nobody notices.", "headline": "3 THINGS YOU MISSED", "template": "title_card",
                 "image_prompt": "dramatic aerial view of a sprawling fictional coastal city at dusk, painterly concept art, vertical", "params": {"accent": "#ff5f3c"}},
                {"narration": "One. Open-world maps feel bigger when roads curve. Straight highways let your brain measure distance; curves hide it.", "headline": "CURVES HIDE DISTANCE", "template": "map",
                 "image_prompt": "stylized top-down map of a fictional island with winding highways glowing at night, no text", "params": {"accent": "#2ee6a6"}},
                {"narration": "Two. Designers plant something interesting every thirty to forty seconds of travel. Miss that rhythm and the world feels empty.", "headline": "THE 30-SECOND RULE", "template": "orbit",
                 "image_prompt": "lonely desert road at golden hour with a mysterious glowing structure in the distance, concept art", "params": {"accent": "#58a6ff"}},
                {"narration": "Three. Water and mountains are cheap. Dense city blocks are expensive. That's why big maps are mostly wilderness.", "headline": "WILDERNESS IS CHEAP", "template": "cityscape",
                 "image_prompt": "dense neon city skyline bordered by dark mountains and ocean, moody painterly style, vertical", "params": {"accent": "#ffd166"}},
                {"narration": "And any exact size number you've seen online? Still a rumor until the studio confirms it. Follow for more.", "headline": "RUMOR UNTIL CONFIRMED", "template": "stat_bars",
                 "image_prompt": "abstract glowing question mark over a dark map grid, cinematic lighting", "params": {"accent": "#ff5f3c"}},
            ],
            "caption": f"3 things about {game}'s map you probably never noticed. Size numbers are rumors until confirmed.\nFollow for daily gaming curiosities.",
            "hashtags": ["#gaming", "#openworld", "#gamedesign", "#didyouknow"],
        }
    return {
        "angle": f"Three curiosities behind the {game} {sub} hype",
        "title": f"3 things about {game} you never noticed",
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
