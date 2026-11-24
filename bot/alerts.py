"""Avisos em português (Telegram e/ou webhook Discord/Slack). Silencioso se não configurado."""
import requests
from .config import SECRETS


def notify(cfg: dict, text: str):
    sent = False
    if cfg["alerts"].get("telegram") and SECRETS.telegram_token and SECRETS.telegram_chat:
        try:
            requests.post(f"https://api.telegram.org/bot{SECRETS.telegram_token}/sendMessage",
                          json={"chat_id": SECRETS.telegram_chat, "text": text[:4000]}, timeout=20)
            sent = True
        except Exception:
            pass
    if cfg["alerts"].get("webhook") and SECRETS.webhook:
        try:
            requests.post(SECRETS.webhook, json={"content": text[:1900], "text": text[:1900]}, timeout=20)
            sent = True
        except Exception:
            pass
    if not sent:
        print("[aviso — nenhum canal de alerta configurado]\n" + text)


def send_video(cfg: dict, path: str, caption: str) -> bool:
    """Envia o MP4 pelo Telegram (limite do Bot API: 50 MB). Retorna True se enviou."""
    if not (SECRETS.telegram_token and SECRETS.telegram_chat):
        return False
    with open(path, "rb") as f:
        r = requests.post(f"https://api.telegram.org/bot{SECRETS.telegram_token}/sendVideo",
                          data={"chat_id": SECRETS.telegram_chat, "caption": caption[:1000], "supports_streaming": "true"},
                          files={"video": f}, timeout=300)
    r.raise_for_status()
    return True
