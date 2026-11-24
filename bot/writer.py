"""Transforma a tendência em pauta original + roteiro (inglês americano, tom de criador gamer)."""
import json
from . import llm

GAME_DISPLAY = {"gta": "GTA 6", "elden-ring": "Elden Ring", "call-of-duty": "Call of Duty", "league-of-legends": "League of Legends",
                "counter-strike": "Counter-Strike", "red-dead": "Red Dead", "baldurs-gate": "Baldur's Gate", "the-witcher": "The Witcher"}
VISUAL_TEMPLATES = ["title_card", "map", "cityscape", "stat_bars", "grid_abstract", "orbit"]

SYSTEM = """You write 35–45 second vertical shorts for {channel} ({handle}), a gaming-curiosities channel. Think of the best
"things you didn't know about <game>" creators: specific, surprising, a little cocky, zero filler.

THE ONE RULE: every sentence must be ABOUT THIS GAME. Concrete details only: a mechanic, a number, a dev decision, an
easter egg, a cut feature, a record, a weird bug, a design trick, a cost, a date, a comparison with a previous entry.
If a sentence could be pasted into a video about a different game, delete it.

Structure:
1. HOOK (≤ 12 words): a bold claim or question about THIS game ("GTA 6's cops are smarter than you think." /
   "Elden Ring hides a boss 90% of players never find.").
2–4. THREE facts/curiosities, each 2–3 short sentences, each with at least one specific detail. Tease the last one
   ("the last one is the weird one").
5. Punchline or twist + CTA: "Follow {channel} for more".

Hard bans: "dive into", "game-changer", "immersive", "next level", "in this video", "did you know", "let's talk about",
"gaming community", any sentence about trends, popularity, views, channels, languages or hype in general.
Never invent numbers or features. Only facts you are confident are confirmed by the developer/publisher or widely
documented; otherwise say "reportedly" / "rumor has it" / "not confirmed yet". Use third-party video titles only as a
hint of WHAT people are talking about, never as a source of facts.

Spoken US English, creator energy, short sentences, one-word sentences welcome ("Wrong.", "Nope."). 80–110 words total.
For each scene add: headline (3–6 words, ALL CAPS, specific), stock_query (2–4 generic English words for stock footage
mood, no game names), image_prompt (original stylized illustration idea, no logos/characters/text), template from
title_card, map, cityscape, stat_bars, grid_abstract, orbit, and params.accent (hex color).
Return JSON:
{"angle": "...", "title": "...", "rumor_flags": ["..."], "claims": [{"claim": "...", "status": "confirmed|rumor", "source_hint": "..."}],
 "scenes": [{"narration": "...", "headline": "...", "image_prompt": "...", "stock_query": "...", "template": "map", "params": {"accent": "#hex"}}],
 "caption": "<2-3 line caption + CTA, last line mentions {handle}>", "hashtags": ["#..."]}"""

BANNED = ("dive into", "game-changer", "game changer", "immersive", "next level", "in this video", "did you know",
          "let's talk about", "gaming community", "across languages", "independent channels", "momentum")


def _quality_issues(script: dict, trend: dict) -> list[str]:
    """Checagem automática: fala do jogo? tem detalhe concreto? sem frases genéricas?"""
    text = " ".join(sc["narration"] for sc in script.get("scenes", [])).lower()
    issues = []
    name = (trend.get("game_name") or trend.get("game") or "").lower()
    keys = [k for k in {name, name.replace("grand theft auto", "gta"), (trend.get("game") or "").replace("-", " ")} if k]
    if keys and not any(k.split()[0] in text for k in keys):
        issues.append("não menciona o jogo")
    import re
    if len(re.findall(r"\d", text)) < 2:
        issues.append("quase nenhum número/detalhe concreto")
    hits = [b for b in BANNED if b in text]
    if hits:
        issues.append("frases genéricas: " + ", ".join(hits))
    n = len(text.split())
    if not 60 <= n <= 130:
        issues.append(f"{n} palavras (fora de 80–110)")
    return issues


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
                {"narration": "And any exact size number you've seen online? Still a rumor until the studio confirms it. Follow Beyond the HUD for more.", "headline": "RUMOR UNTIL CONFIRMED", "template": "stat_bars",
                 "image_prompt": "abstract glowing question mark over a dark map grid, cinematic lighting", "params": {"accent": "#ff5f3c"}},
            ],
            "caption": f"3 things about {game}'s map you probably never noticed. Size numbers are rumors until confirmed.\nFollow @beyondthehudtv for daily gaming curiosities.",
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
            {"narration": "Anything not confirmed by the studio is still a rumor. Follow Beyond the HUD for the next one.", "headline": "RUMOR UNTIL CONFIRMED", "template": "grid_abstract", "params": {"accent": "#ffd166"}},
        ],
        "caption": f"The real reason {game} is everywhere right now.\nFollow @beyondthehudtv for daily game breakdowns.",
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
    system = SYSTEM.replace("{channel}", cfg["channel"]["name"]).replace("{handle}", cfg["channel"].get("handle", ""))
    try:
        s, last_err = None, None
        for attempt in range(3):  # até 3 tentativas; a partir da 2ª manda os problemas encontrados
            extra = "" if not last_err else f"\n\nYour previous draft was rejected because: {last_err}. Fix ALL of it."
            try:
                cand = llm.chat_json(cfg, system, user + extra, max_tokens=2500)
            except Exception as e:  # JSON quebrado, 429 etc.: conta como tentativa
                last_err = f"invalid JSON ({str(e)[:60]})"; print(f"[roteiro] tentativa {attempt + 1} falhou: {e}"); continue
            if not (cand.get("scenes") and cand.get("caption") and cand.get("angle")):
                last_err = "JSON incompleto"; continue
            issues = _quality_issues(cand, trend)
            if not issues:
                s = cand; break
            last_err = "; ".join(issues); s = cand
            print(f"[roteiro] tentativa {attempt + 1} com problemas: {last_err}")
        if s is None:
            raise RuntimeError(last_err or "sem roteiro")
        s["quality_issues"] = _quality_issues(s, trend)
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
