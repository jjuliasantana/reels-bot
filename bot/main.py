"""CLI do bot.
  python -m bot.main collect                  # coleta/atualiza snapshots do YouTube (rode a cada ~4h)
  python -m bot.main run --dry-run            # pauta + roteiro + MP4, sem publicar
  python -m bot.main run                      # igual, e publica se publishing.enabled e PUBLISH_ENABLED=true
  python -m bot.main run --dry-run --sim      # teste completo com dados simulados (2 coletas fictícias)
  python -m bot.main insights                 # coleta métricas do perfil
"""
import argparse
import json
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from . import alerts, cluster, db, insights, publish, render, tts, writer, youtube
from .config import OUTPUT_DIR, SECRETS, load_config


def cmd_collect(cfg, con, sim_hours=None, taken_at=None):
    videos, simulated = youtube.collect(cfg, sim_hours)
    db.upsert_videos(con, videos, taken_at or db.now_iso())
    print(f"coleta: {len(videos)} vídeos ({'SIMULADOS' if simulated else 'YouTube API'})")
    return simulated


def estimate_cost(cfg, script, n_scenes, use_images) -> dict:
    c = cfg["costs"]
    chars = sum(len(s["narration"]) for s in script["scenes"])
    items = {"roteiro (LLM)": c["llm_script_usd"], "embeddings": c["embeddings_usd"],
             "narração (TTS)": c["tts_per_1k_chars_usd"] * chars / 1000, "legendas (whisper)": c["whisper_per_minute_usd"] * 0.75,
             "imagens IA": c["image_usd_each"] * n_scenes if use_images else 0.0, "YouTube API": 0.0}
    items["total"] = round(sum(items.values()), 4)
    return items


def write_report(cfg, post, trend, trends, script, video_info, cost, steps, simulated, reason=None) -> Path:
    p = OUTPUT_DIR / f"relatorio_{post['post_key']}.md"
    L = [f"# Relatório do bot — {post['post_key']}", f"Gerado em {db.now_iso()} (UTC)", ""]
    if simulated:
        L += ["> ⚠️ **DADOS SIMULADOS**: não havia YOUTUBE_API_KEY. Os vídeos abaixo são fictícios (IDs `SIM…`) e os links não apontam para vídeos reais.", ""]
    L += ["## Etapas realmente executadas"] + [f"- {'✅' if ok else '⏭️'} {name}{(' — ' + note) if note else ''}" for name, ok, note in steps] + [""]
    if reason:
        L += [f"## Resultado: postagem pulada", f"Motivo: {reason}", ""]
    if trend:
        L += ["## Pauta escolhida", f"- **Tendência:** {trend['label']}  (jogo: {trend['game']}, subtema: {trend['subtopic']})",
              f"- **Ângulo original:** {script['angle'] if script else '-'}", f"- **Título:** {script['title'] if script else '-'}",
              f"- **Sinal:** {'PRELIMINAR (uma coleta)' if trend['preliminary'] else 'confirmado (≥2 coletas)'}",
              f"- **Score:** {trend['score']} | crescimento ≈ {trend['views_per_hour']} views/h | {trend['independent_channels']} canais independentes | idiomas: {', '.join(trend['languages'])} | views no cluster: {trend['total_views']:,}",
              ""]
        if script and script.get("rumor_flags"):
            L += ["**Rumores identificados no roteiro:** " + "; ".join(script["rumor_flags"]), ""]
        L += ["## Evidências (links e números que justificam a escolha)"]
        for e in trend["evidence"]:
            snaps = " → ".join(f"{s['views']:,} ({s['taken_at'][11:16]}Z)" for s in e["snapshots"])
            L += [f"- [{e['title']}]({e['url']}) — {e['channel']} [{e['lang']}]{' (simulado)' if e['simulated'] else ''}: {snaps}"]
        L += [""]
    L += ["## Outras tendências avaliadas"]
    for t in trends[:8]:
        L += [f"- {t['label']}: score {t['score']}, {t['views_per_hour']} v/h, {t['independent_channels']} canais, {'preliminar' if t['preliminary'] else 'confirmado'}"
              + (f" — rejeitada: {', '.join(t['rejection_reasons'])}" if t.get('rejection_reasons') else "")]
    L += [""]
    if video_info:
        L += ["## Vídeo", f"- Arquivo: `{video_info['path']}`", f"- Duração: {video_info['seconds']} s, {video_info['scenes']} cenas, 1080x1920 MP4",
              f"- Imagens: {'sua gameplay (B-roll próprio, ' + str(video_info.get('broll_clips', 0)) + ' clipes)' if video_info.get('broll_clips') else ('IA Gemini (' + str(video_info['ai_images']) + ' cenas)' if video_info['ai_images'] else 'ilustrações procedurais originais')}", ""]
    if cost:
        L += ["## Custo estimado por vídeo (USD)"] + [f"- {k}: {v:.4f}" for k, v in cost.items()] + [""]
    if script:
        L += ["## Roteiro (en-US)", f"_gerado por: {script.get('generated_by')}_", ""]
        for i, sc in enumerate(script["scenes"]):
            L += [f"{i + 1}. **[{sc['template']}] {sc['headline']}** — {sc['narration']}"]
        L += ["", "## Legenda do post", "```", script["caption"], " ".join(dict.fromkeys(script.get("hashtags", []) + cfg["publishing"]["hashtags"])), "```", ""]
    L += [f"## Publicação", f"- Status: **{post['status']}**" + (f" — {post.get('error')}" if post.get('error') else ""),
          f"- Publicação automática: {'LIGADA' if cfg['publishing']['enabled'] and SECRETS.publish_enabled_env else 'DESLIGADA (aguardando autorização)'}"]
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def cmd_run(cfg, con, dry_run: bool, sim: bool):
    steps, simulated = [], False
    if sim or not SECRETS.youtube:
        # Teste completo: duas coletas simuladas com 4 h de intervalo para medir crescimento.
        t0 = (datetime.now(timezone.utc) - timedelta(hours=4)).replace(microsecond=0).isoformat()
        cmd_collect(cfg, con, sim_hours=0, taken_at=t0)
        cmd_collect(cfg, con, sim_hours=4)
        simulated = True
        steps.append(("Coleta no YouTube (2 snapshots)", True, "DADOS SIMULADOS — sem YOUTUBE_API_KEY"))
    else:
        videos = db.recent_videos_with_snapshots(con, cfg["monitoring"]["lookback_hours"])
        if not videos:
            cmd_collect(cfg, con)
        steps.append(("Coleta no YouTube", True, "YouTube Data API v3"))

    n_ins = insights.fetch_and_store(con)
    prior = insights.prior_by_game(con)
    steps.append(("Métricas do perfil (Instagram Insights)", n_ins > 0, "sem credenciais do Instagram" if not n_ins else f"{n_ins} reels"))

    videos = db.recent_videos_with_snapshots(con, cfg["monitoring"]["lookback_hours"])
    trends = cluster.score_clusters(cfg, videos, prior)
    steps.append(("Agrupamento multilíngue e pontuação", True,
                  f"embeddings {cfg['ai']['embeddings']}" if (cfg["ai"]["embeddings"] == "gemini" and SECRETS.gemini) or (cfg["ai"]["embeddings"] == "openai" and SECRETS.openai) else "dicionário de aliases (sem embeddings)"))
    if dry_run and not cfg["selection"]["allow_preliminary_post"]:
        # Em teste (sem publicar) aceitamos sinal preliminar para sempre gerar um vídeo de amostra.
        cfg["selection"]["allow_preliminary_post"] = True
        steps.append(("Modo dry-run", True, "sinal preliminar aceito só para gerar amostra (na publicação real exige 2 coletas)"))
    trend, reason = cluster.pick(cfg, trends, db.recent_post_topics(con, cfg["selection"]["cooldown_days_same_topic"]))
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    post = {"post_key": f"{(trend or {}).get('slug', 'none')}-{today}", "topic_slug": (trend or {}).get("slug"),
            "topic_label": (trend or {}).get("label"), "status": "skipped"}
    if not trend:
        steps.append(("Seleção de pauta", False, reason))
        p = write_report(cfg, post, None, trends, None, None, None, steps, simulated, reason)
        print(f"PULADO: {reason}\nrelatório: {p}")
        return
    steps.append(("Seleção de pauta", True, trend["label"]))

    existing = db.get_post(con, post["post_key"])
    if existing and existing["status"] == "published":
        print(f"já publicado hoje: {post['post_key']} — nada a fazer (anti-duplicata)")
        return
    post = existing or post
    post.update(topic_slug=trend["slug"], topic_label=trend["label"],
                evidence_json={"game": trend["game"], "subtopic": trend["subtopic"], "score": trend["score"],
                               "views_per_hour": trend["views_per_hour"], "preliminary": trend["preliminary"],
                               "evidence": trend["evidence"]})

    # --- orçamento ---
    c = cfg["costs"]
    if db.spent_usd(con, "day") >= c["max_usd_per_day"] or db.spent_usd(con, "month") >= c["max_usd_per_month"]:
        post.update(status="skipped", error="limite de gastos atingido"); db.save_post(con, post)
        alerts.notify(cfg, f"⛔ Bot de Reels: limite de gastos atingido, postagem pulada ({post['post_key']}).")
        write_report(cfg, post, trend, trends, None, None, None, steps, simulated, "limite de gastos atingido")
        return

    workdir = OUTPUT_DIR / post["post_key"]; workdir.mkdir(exist_ok=True)
    final = workdir / f"reel_{post['post_key']}.mp4"
    script, video_info, cost = None, None, None
    try:
        if existing and existing.get("script_json") and final.exists() and existing["status"] in ("rendered", "hosted", "creating"):
            script = json.loads(existing["script_json"]); video_info = {"path": str(final), "seconds": 0, "scenes": len(script["scenes"]), "ai_images": 0}
            steps.append(("Roteiro + vídeo", True, "reaproveitados de execução anterior (anti-duplicata)"))
        else:
            script, by_llm = writer.write_script(cfg, trend)
            steps.append(("Roteiro original (en-US)", True, script.get("generated_by") if by_llm else "modelo de fallback — sem chave de LLM (GEMINI_API_KEY)"))
            scenes, real_tts = tts.narrate(cfg, script, workdir)
            steps.append(("Narração + tempos de legenda", True, f"{cfg['ai'].get('_tts_used')} (voz real)" if real_tts else "ÁUDIO PLACEHOLDER (sem voz) — edge-tts não instalado / sem chave"))
            total = sum(s["duration"] for s in scenes)
            vmin, vmax = cfg["video"]["min_seconds"], cfg["video"]["max_seconds"]
            if (total > vmax or total < vmin) and by_llm:
                target = int(writer.word_count(script) * (vmax - 3) / total) if total > vmax else int(writer.word_count(script) * (vmin + 3) / total)
                script, _ = writer.write_script(cfg, {**trend, "label": trend["label"] + f" (rewrite: exactly ~{target} words total)"})
                scenes, real_tts = tts.narrate(cfg, script, workdir); total = sum(s["duration"] for s in scenes)
            video_info = render.assemble(cfg, scenes, workdir, final, trend.get("game"), trend.get("game_name"))
            steps.append(("Render MP4 9:16 (ilustrações + legendas)", True,
                          f"{video_info['seconds']} s" + (" ⚠️ fora da faixa 30–45 s" if not vmin <= video_info["seconds"] <= vmax else "")))
            cost = estimate_cost(cfg, script, len(scenes), cfg["video"]["image_generation"] == "openai" and bool(SECRETS.openai))
            if cost["total"] > c["max_usd_per_video"]:
                raise RuntimeError(f"custo estimado {cost['total']} > max_usd_per_video")
            db.add_cost(con, post["post_key"], "video", cost["total"])
            post.update(status="rendered", video_path=str(final), script_json=script, cost_usd=cost["total"]); db.save_post(con, post)
        if cost is None:
            cost = estimate_cost(cfg, script, len(script["scenes"]), False)

        # --- publicação ---
        prov = cfg["publishing"]["provider"]
        can_publish = cfg["publishing"]["enabled"] and SECRETS.publish_enabled_env and not dry_run and not simulated
        if dry_run or not can_publish:  # em teste, manda o vídeo pelo Telegram (se configurado) para você avaliar/postar à mão
            try:
                if alerts.send_video(cfg, str(final), "🧪 Amostra (dry-run)\n" + publish.platform_texts(script, cfg)):
                    steps.append(("Vídeo enviado no Telegram", True, "para avaliação / postagem manual"))
            except Exception as e:
                steps.append(("Vídeo enviado no Telegram", False, str(e)))
        if not can_publish:
            steps.append(("Publicação", False, "desligada (dry-run / aguardando autorização / dados simulados)"))
        elif db.posts_today(con) >= cfg["publishing"]["max_posts_per_day"]:
            steps.append(("Publicação", False, "limite diário de posts atingido"))
        else:
            if prov != "telegram" and not post.get("media_url"):
                post["media_url"] = publish.host(cfg, final, post["post_key"]); post["status"] = "hosted"; db.save_post(con, post)
            caption = script["caption"] + "\n\n" + " ".join(dict.fromkeys(script.get("hashtags", []) + cfg["publishing"]["hashtags"]))
            media_id = publish.publish(cfg, con, post, caption)
            post.update(status="published", ig_media_id=media_id, error=None); db.save_post(con, post)
            steps.append(("Publicação", True, f"media_id {media_id}"))
            if prov != "telegram":
                alerts.notify(cfg, f"✅ Reel publicado: {script['title']} ({post['post_key']}), custo estimado US$ {cost['total']:.3f}")
    except Exception as e:
        post.update(status="failed" if post.get("status") not in ("hosted", "creating") else post["status"], error=str(e)); db.save_post(con, post)
        steps.append(("Erro", False, str(e)))
        alerts.notify(cfg, f"❌ Bot de Reels falhou em {post['post_key']}: {e}")
        traceback.print_exc()
    p = write_report(cfg, post, trend, trends, script, video_info, cost, steps, simulated)
    (workdir / "pauta.json").write_text(json.dumps({"trend": trend, "script": script, "cost": cost}, ensure_ascii=False, indent=2))
    print(f"status: {post['status']}\nrelatório: {p}\nvídeo: {final if final.exists() else '-'}")


def cmd_check(cfg):
    """Diagnóstico das credenciais (relata em pt-BR; nunca publica)."""
    import requests
    def ok(name, fn):
        try:
            print(f"✅ {name}: {fn()}")
        except Exception as e:
            print(f"❌ {name}: {e}")
    print("YOUTUBE_API_KEY:", "definida" if SECRETS.youtube else "ausente → dados simulados")
    if SECRETS.youtube:
        ok("YouTube", lambda: f"{len(youtube.search_recent('gta', 48, 3))} vídeos encontrados")
    print("GEMINI_API_KEY:", "definida" if SECRETS.gemini else "ausente → roteiro-modelo")
    if SECRETS.gemini:
        from . import llm
        ok("Gemini", lambda: llm.chat(cfg, "Reply with the single word OK.", "ping", 10).strip()[:20])
    try:
        import edge_tts  # noqa
        print("✅ edge-tts instalado (narração gratuita)")
    except ImportError:
        print("❌ edge-tts não instalado → áudio placeholder (pip install edge-tts)")
    print("IG_ACCESS_TOKEN:", "definido" if SECRETS.ig_token else "ausente → publicação impossível")
    if SECRETS.ig_token:
        ok("Instagram /me", lambda: publish.ig_me())
    print("Publicação:", "LIGADA" if (cfg["publishing"]["enabled"] and SECRETS.publish_enabled_env) else "desligada")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--sim-hours", type=float, default=None)
    r = sub.add_parser("run"); r.add_argument("--dry-run", action="store_true"); r.add_argument("--sim", action="store_true")
    sub.add_parser("insights")
    sub.add_parser("check")   # testa as credenciais configuradas, sem publicar nada
    a = ap.parse_args(argv)
    cfg, con = load_config(), db.connect()
    if a.cmd == "collect":
        cmd_collect(cfg, con, a.sim_hours)
    elif a.cmd == "run":
        cmd_run(cfg, con, a.dry_run, a.sim)
    elif a.cmd == "insights":
        print(f"insights atualizados: {insights.fetch_and_store(con)}")
    elif a.cmd == "check":
        cmd_check(cfg)


if __name__ == "__main__":
    sys.exit(main())
