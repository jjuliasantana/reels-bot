"""Estado persistente em SQLite: snapshots de vídeos, clusters, posts, custos, métricas."""
import json
import sqlite3
from datetime import datetime, timezone
from .config import STATE_DIR

DB_PATH = STATE_DIR / "bot.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY, title TEXT, channel_id TEXT, channel_title TEXT,
  published_at TEXT, lang TEXT, query TEXT, simulated INTEGER DEFAULT 0, first_seen TEXT
);
CREATE TABLE IF NOT EXISTS snapshots (
  video_id TEXT, taken_at TEXT, views INTEGER, likes INTEGER, comments INTEGER,
  PRIMARY KEY (video_id, taken_at)
);
CREATE TABLE IF NOT EXISTS posts (
  post_key TEXT PRIMARY KEY,         -- idempotência: topic_slug + data
  topic_slug TEXT, topic_label TEXT, angle TEXT, status TEXT,  -- planned|rendered|hosted|creating|published|failed|skipped
  video_path TEXT, media_url TEXT, ig_creation_id TEXT, ig_media_id TEXT,
  evidence_json TEXT, script_json TEXT, cost_usd REAL, created_at TEXT, updated_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS costs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, post_key TEXT, item TEXT, usd REAL, estimated INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS insights (
  ig_media_id TEXT, taken_at TEXT, plays INTEGER, reach INTEGER, likes INTEGER, saves INTEGER, shares INTEGER, comments INTEGER,
  PRIMARY KEY (ig_media_id, taken_at)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_videos(con, videos: list[dict], taken_at: str):
    for v in videos:
        con.execute(
            """INSERT INTO videos(video_id,title,channel_id,channel_title,published_at,lang,query,simulated,first_seen)
               VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET title=excluded.title""",
            (v["video_id"], v["title"], v["channel_id"], v["channel_title"], v["published_at"],
             v.get("lang"), v.get("query"), int(v.get("simulated", False)), taken_at),
        )
        con.execute(
            "INSERT OR REPLACE INTO snapshots(video_id,taken_at,views,likes,comments) VALUES(?,?,?,?,?)",
            (v["video_id"], taken_at, v.get("views", 0), v.get("likes", 0), v.get("comments", 0)),
        )
    con.commit()


def recent_videos_with_snapshots(con, lookback_hours: int) -> list[dict]:
    rows = con.execute(
        """SELECT v.*, s.taken_at, s.views FROM videos v JOIN snapshots s ON s.video_id=v.video_id
           WHERE v.published_at >= datetime('now', ?) ORDER BY v.video_id, s.taken_at""",
        (f"-{lookback_hours} hours",),
    ).fetchall()
    out: dict[str, dict] = {}
    for r in rows:
        d = out.setdefault(r["video_id"], {**{k: r[k] for k in r.keys() if k not in ("taken_at", "views")}, "snapshots": []})
        d["snapshots"].append({"taken_at": r["taken_at"], "views": r["views"]})
    return list(out.values())


def recent_post_topics(con, days: int) -> list[dict]:
    rows = con.execute(
        "SELECT topic_slug, topic_label, status FROM posts WHERE created_at >= datetime('now', ?) AND status IN ('published','hosted','creating')",
        (f"-{days} days",),
    ).fetchall()
    return [dict(r) for r in rows]


def posts_today(con) -> int:
    return con.execute(
        "SELECT COUNT(*) FROM posts WHERE status='published' AND date(updated_at)=date('now')"
    ).fetchone()[0]


def spent_usd(con, period: str) -> float:
    q = {"day": "date(at)=date('now')", "month": "strftime('%Y-%m',at)=strftime('%Y-%m','now')"}[period]
    return con.execute(f"SELECT COALESCE(SUM(usd),0) FROM costs WHERE {q}").fetchone()[0]


def add_cost(con, post_key: str, item: str, usd: float, estimated=True):
    con.execute("INSERT INTO costs(at,post_key,item,usd,estimated) VALUES(?,?,?,?,?)",
                (now_iso(), post_key, item, usd, int(estimated)))
    con.commit()


def save_post(con, post: dict):
    post.setdefault("created_at", now_iso())
    post["updated_at"] = now_iso()
    cols = ["post_key", "topic_slug", "topic_label", "angle", "status", "video_path", "media_url", "ig_creation_id",
            "ig_media_id", "evidence_json", "script_json", "cost_usd", "created_at", "updated_at", "error"]
    vals = [post.get(c) for c in cols]
    for c in ("evidence_json", "script_json"):
        i = cols.index(c)
        if vals[i] is not None and not isinstance(vals[i], str):
            vals[i] = json.dumps(vals[i], ensure_ascii=False)
    con.execute(
        f"INSERT INTO posts({','.join(cols)}) VALUES({','.join('?' * len(cols))}) "
        f"ON CONFLICT(post_key) DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in cols if c != "post_key"),
        vals,
    )
    con.commit()


def get_post(con, post_key: str) -> dict | None:
    r = con.execute("SELECT * FROM posts WHERE post_key=?", (post_key,)).fetchone()
    return dict(r) if r else None
