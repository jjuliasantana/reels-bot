"""Hospedagem do MP4 em URL pública + publicação (Instagram Graph API ou Buffer). Idempotente."""
import time
from pathlib import Path
import requests
from .config import SECRETS
from . import db

GRAPH = "https://graph.facebook.com/v21.0"


# ---------- hospedagem (o Instagram só aceita video_url público) ----------
def host_github_release(video: Path, post_key: str) -> str:
    tok, repo = SECRETS.github_token, SECRETS.github_repo
    if not (tok and repo):
        raise RuntimeError("GITHUB_TOKEN/GITHUB_REPOSITORY ausentes para hospedar o MP4")
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    tag = f"reel-{post_key}"
    r = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{tag}", headers=h, timeout=30)
    if r.status_code == 404:
        r = requests.post(f"https://api.github.com/repos/{repo}/releases", headers=h,
                          json={"tag_name": tag, "name": tag, "body": "Reel gerado automaticamente"}, timeout=30)
    r.raise_for_status()
    rel = r.json()
    for a in rel.get("assets", []):
        if a["name"] == video.name:
            return a["browser_download_url"]
    up = rel["upload_url"].split("{")[0]
    with open(video, "rb") as f:
        r = requests.post(f"{up}?name={video.name}", headers={**h, "Content-Type": "video/mp4"}, data=f, timeout=600)
    r.raise_for_status()
    return r.json()["browser_download_url"]


def host_s3(video: Path, post_key: str) -> str:
    import os
    import boto3  # só necessário se hosting == s3
    bucket, region = os.environ["S3_BUCKET"], os.environ.get("AWS_REGION", "us-east-1")
    key = f"reels/{post_key}/{video.name}"
    boto3.client("s3", region_name=region).upload_file(str(video), bucket, key,
                                                       ExtraArgs={"ContentType": "video/mp4", "ACL": "public-read"})
    base = os.environ.get("S3_PUBLIC_BASE") or f"https://{bucket}.s3.{region}.amazonaws.com"
    return f"{base}/{key}"


def host(cfg: dict, video: Path, post_key: str) -> str:
    return {"github_release": host_github_release, "s3": host_s3}[cfg["publishing"]["hosting"]](video, post_key)


# ---------- Instagram Graph API (conta profissional) ----------
def ig_publish(con, post: dict, caption: str) -> str:
    tok, uid = SECRETS.ig_token, SECRETS.ig_user_id
    if not (tok and uid):
        raise RuntimeError("IG_ACCESS_TOKEN/IG_USER_ID ausentes")
    creation_id = post.get("ig_creation_id")
    if not creation_id:  # evita container duplicado após falha: salva o id antes de qualquer retry
        r = requests.post(f"{GRAPH}/{uid}/media", data={
            "media_type": "REELS", "video_url": post["media_url"], "caption": caption,
            "share_to_feed": "true", "access_token": tok}, timeout=60)
        r.raise_for_status()
        creation_id = r.json()["id"]
        post.update(ig_creation_id=creation_id, status="creating")
        db.save_post(con, post)
    for _ in range(40):  # até ~10 min de processamento
        s = requests.get(f"{GRAPH}/{creation_id}", params={"fields": "status_code,status", "access_token": tok}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError(f"Instagram rejeitou o vídeo: {s}")
        time.sleep(15)
    else:
        raise RuntimeError("Timeout esperando o Instagram processar o vídeo")
    r = requests.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": creation_id, "access_token": tok}, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


# ---------- Buffer (alternativa; depende do acesso à API da sua conta Buffer) ----------
def buffer_publish(post: dict, caption: str) -> str:
    tok, prof = SECRETS.buffer_token, SECRETS.buffer_profile
    if not (tok and prof):
        raise RuntimeError("BUFFER_ACCESS_TOKEN/BUFFER_PROFILE_ID ausentes")
    r = requests.post("https://api.bufferapp.com/1/updates/create.json", data={
        "access_token": tok, "profile_ids[]": prof, "text": caption, "now": "true",
        "media[video]": post["media_url"]}, timeout=60)
    r.raise_for_status()
    return str(r.json().get("updates", [{}])[0].get("id", ""))


def publish(cfg: dict, con, post: dict, caption: str) -> str:
    prov = cfg["publishing"]["provider"]
    return ig_publish(con, post, caption) if prov == "instagram" else buffer_publish(post, caption)
