"""
Tracker Instagram senza token.

Legge i profili dal secret PROFILES (o da profiles.json, se esiste), scarica i dati PUBBLICI di ogni profilo
(follower, seguiti, post, ultimi ~12 post con like/commenti/views) e li salva in:
  docs/data/latest.json            -> stato attuale di tutti i profili
  docs/data/history/<username>.json -> storico per i grafici di crescita

Usa solo la libreria standard di Python: nessuna dipendenza da installare.
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(ROOT, "profiles.json")
DATA_DIR = os.path.join(ROOT, "docs", "data")
HIST_DIR = os.path.join(DATA_DIR, "history")
LATEST_FILE = os.path.join(DATA_DIR, "latest.json")

ENDPOINTS = [
    "https://i.instagram.com/api/v1/users/web_profile_info/?username={}",
    "https://www.instagram.com/api/v1/users/web_profile_info/?username={}",
]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
        "Instagram 302.0.0.23.114"
    ),
    "x-ig-app-id": "936619743392459",
    "Accept": "application/json",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}
MAX_ATTEMPTS = 4


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def http_get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_profile(username):
    """Ritorna il dict 'user' di Instagram, oppure solleva l'ultimo errore."""
    last_err = None
    for attempt in range(MAX_ATTEMPTS):
        for tpl in ENDPOINTS:
            url = tpl.format(username)
            try:
                payload = http_get_json(url)
                user = (payload.get("data") or {}).get("user")
                if user:
                    return user
                last_err = RuntimeError("profilo non trovato o privato")
                # Se Instagram risponde ma senza utente, ritentare non serve
                if payload.get("status") == "ok":
                    raise last_err
            except urllib.error.HTTPError as e:
                last_err = RuntimeError(f"HTTP {e.code}")
                if e.code == 404:
                    raise RuntimeError("profilo inesistente (404)")
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = RuntimeError(f"rete/risposta non valida: {e}")
        # Pausa crescente prima del nuovo tentativo (limita i blocchi 401/429)
        wait = 20 * (attempt + 1) + random.uniform(0, 10)
        print(f"  tentativo {attempt + 1} fallito ({last_err}), attendo {wait:.0f}s")
        time.sleep(wait)
    raise last_err or RuntimeError("errore sconosciuto")


def count(edge):
    """I conteggi nascosti arrivano come -1: li trattiamo come assenti."""
    if not isinstance(edge, dict):
        return None
    c = edge.get("count")
    return c if isinstance(c, int) and c >= 0 else None


def parse_user(u):
    media = u.get("edge_owner_to_timeline_media") or {}
    posts = []
    for e in media.get("edges") or []:
        n = e.get("node") or {}
        cap_edges = (n.get("edge_media_to_caption") or {}).get("edges") or []
        caption = cap_edges[0]["node"].get("text", "") if cap_edges else ""
        sc = n.get("shortcode")
        views = n.get("video_view_count")
        posts.append({
            "shortcode": sc,
            "url": f"https://www.instagram.com/p/{sc}/" if sc else None,
            "ts": n.get("taken_at_timestamp"),
            "type": {"GraphVideo": "reel", "GraphSidecar": "carosello",
                     "GraphImage": "foto"}.get(n.get("__typename"), "post"),
            "likes": count(n.get("edge_liked_by")) if n.get("edge_liked_by") else count(n.get("edge_media_preview_like")),
            "comments": count(n.get("edge_media_to_comment")),
            "views": views if isinstance(views, int) and views >= 0 else None,
            "caption": " ".join(caption.split())[:160],
        })
    return {
        "username": u.get("username"),
        "full_name": u.get("full_name") or "",
        "bio": u.get("biography") or "",
        "is_verified": bool(u.get("is_verified")),
        "is_private": bool(u.get("is_private")),
        "followers": count(u.get("edge_followed_by")),
        "following": count(u.get("edge_follow")),
        "posts_count": count(media),
        "recent_posts": posts,
    }


def avg(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 1) if vals else None


def load_usernames():
    """Dal secret PROFILES (username separati da virgola, spazio o a capo),
    altrimenti da profiles.json."""
    raw = os.environ.get("PROFILES", "").replace(",", " ").split()
    names = raw or load_json(PROFILES_FILE, [])
    out = []
    for u in names:
        u = u.strip().lstrip("@").lower()
        if u and u not in out:
            out.append(u)
    return out


def main():
    usernames = load_usernames()
    if not usernames:
        print("::error::Nessun profilo: imposta il secret PROFILES con gli username da seguire.")
        return 1

    latest = load_json(LATEST_FILE, {"profiles": {}})
    profiles = latest.get("profiles", {})
    ts = now_iso()
    ok_count = 0

    for i, username in enumerate(usernames):
        if i:
            time.sleep(random.uniform(8, 18))  # ritmo "umano" tra un profilo e l'altro
        # Il repo è pubblico e i log di Actions pure: niente username nei log
        print(f"Profilo {i + 1}/{len(usernames)}")
        try:
            data = parse_user(fetch_profile(username))
        except Exception as e:  # noqa: BLE001
            print(f"  ERRORE: {e}")
            prev = profiles.get(username, {"username": username})
            prev.update({"ok": False, "error": str(e), "last_attempt": ts})
            profiles[username] = prev
            continue

        ok_count += 1
        posts = data["recent_posts"]
        data.update({
            "ok": True, "error": None, "fetched_at": ts, "last_attempt": ts,
            "avg_likes": avg(p["likes"] for p in posts),
            "avg_comments": avg(p["comments"] for p in posts),
            "avg_views": avg(p["views"] for p in posts),
        })
        profiles[username] = data
        print(f"  ok: {data['followers']} follower, {len(posts)} post recenti")

        hist_path = os.path.join(HIST_DIR, f"{username}.json")
        history = load_json(hist_path, [])
        history.append({
            "t": ts,
            "followers": data["followers"],
            "following": data["following"],
            "posts": data["posts_count"],
            "avg_likes": data["avg_likes"],
            "avg_comments": data["avg_comments"],
            "avg_views": data["avg_views"],
        })
        save_json(hist_path, history)

    # Togli dalla dashboard i profili rimossi da profiles.json (lo storico resta)
    profiles = {u: profiles[u] for u in usernames if u in profiles}
    save_json(LATEST_FILE, {"updated": ts, "order": usernames, "profiles": profiles})

    print(f"\nFatto: {ok_count}/{len(usernames)} profili aggiornati.")
    return 0 if ok_count else 1  # rosso su GitHub solo se fallisce tutto


if __name__ == "__main__":
    sys.exit(main())
