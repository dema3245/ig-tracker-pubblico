"""
Tracker Instagram senza token.

Legge i profili dalla lista gestita dalla dashboard (docs/profiles.enc, decifrata da
vault.py), oppure dal secret PROFILES o da profiles.json; scarica i dati PUBBLICI di ogni profilo
(follower, seguiti, post, ultimi ~12 post con like/commenti/views) e li salva in:
  docs/data/latest.json            -> stato attuale di tutti i profili
  docs/data/history/<username>.json -> storico per i grafici di crescita
  docs/data/posts/<username>.json   -> archivio dei post (ultime metriche di ognuno)

Usa solo la libreria standard di Python: nessuna dipendenza da installare.
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_FILE = os.path.join(ROOT, "profiles.json")
DATA_DIR = os.path.join(ROOT, "docs", "data")
HIST_DIR = os.path.join(DATA_DIR, "history")
POSTS_DIR = os.path.join(DATA_DIR, "posts")
MANAGED_PROFILES = os.path.join(DATA_DIR, "profiles.json")  # da docs/profiles.enc
MAX_ARCHIVED_POSTS = 500
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
# Se c'è il secret APIFY_TOKEN i dati arrivano da Apify, che non viene bloccato
# come i server di GitHub (HTTP 429). Senza token si interroga Instagram direttamente.
APIFY_URL = ("https://api.apify.com/v2/acts/apify~instagram-profile-scraper/"
             "run-sync-get-dataset-items?timeout=280")
# Per alcuni profili lo scraper dei profili non restituisce i post: li chiediamo a quello dei post
APIFY_POSTS_URL = ("https://api.apify.com/v2/acts/apify~instagram-post-scraper/"
                   "run-sync-get-dataset-items?timeout=280")
POSTS_PER_PROFILE = 12
# Lo scraper dei post costa crediti per ogni post: lo usiamo al massimo una volta al giorno
# per profilo (20 ore, così con un giro ogni 8 ore scatta un giro su tre)
POSTS_REFRESH_HOURS = 20
MAX_ATTEMPTS = 2
TIMEOUT = 15  # secondi di attesa massima per ogni risposta di Instagram


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
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
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
        if attempt == MAX_ATTEMPTS - 1:
            break
        # Pausa prima del nuovo tentativo (limita i blocchi 401/429)
        wait = 15 + random.uniform(0, 10)
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
            "thumb": n.get("thumbnail_src") or n.get("display_url"),
        })
    return {
        "username": u.get("username"),
        "pic": u.get("profile_pic_url"),
        "full_name": u.get("full_name") or "",
        "bio": u.get("biography") or "",
        "is_verified": bool(u.get("is_verified")),
        "is_private": bool(u.get("is_private")),
        "followers": count(u.get("edge_followed_by")),
        "following": count(u.get("edge_follow")),
        "posts_count": count(media),
        "recent_posts": posts,
    }


def apify_call(url, payload, token):
    req = urllib.request.Request(
        url, method="POST", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=330) as resp:
            items = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        hint = {401: "token non valido", 402: "crediti Apify esauriti"}.get(e.code, "")
        raise RuntimeError(f"Apify HTTP {e.code} {hint}".strip())
    return [it for it in items if isinstance(it, dict)]


def fetch_apify(usernames, token):
    """Un'unica chiamata per tutti i profili: ritorna {username: risultato Apify}."""
    items = apify_call(APIFY_URL, {"usernames": usernames}, token)
    return {(it.get("username") or "").lower(): it for it in items}


def fetch_apify_posts(usernames, token):
    """Ultimi post dei profili per cui lo scraper dei profili non li ha dati: {username: [post]}."""
    items = apify_call(APIFY_POSTS_URL, {"username": usernames, "resultsLimit": POSTS_PER_PROFILE}, token)
    out = {}
    for it in items:
        owner = (it.get("ownerUsername") or "").lower()
        if owner and not it.get("error"):
            out.setdefault(owner, []).append(it)
    return out


def num(v):
    return v if isinstance(v, int) and v >= 0 else None


def parse_apify_post(p):
    ts = None
    try:
        ts = int(datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")).timestamp())
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    sc = p.get("shortCode")
    return {
        "shortcode": sc,
        "url": p.get("url") or (f"https://www.instagram.com/p/{sc}/" if sc else None),
        "ts": ts,
        "type": {"Video": "reel", "Sidecar": "carosello", "Image": "foto"}.get(p.get("type"), "post"),
        "likes": num(p.get("likesCount")),
        "comments": num(p.get("commentsCount")),
        "views": num(p.get("videoViewCount")) or num(p.get("videoPlayCount")),
        "caption": " ".join((p.get("caption") or "").split())[:160],
        "thumb": p.get("displayUrl"),
    }


def parse_apify(it, extra_posts=None):
    raw = it.get("latestPosts") or extra_posts or []
    posts = sorted((parse_apify_post(p) for p in raw), key=lambda p: p["ts"] or 0, reverse=True)
    return {
        "username": (it.get("username") or "").lower(),
        "pic": it.get("profilePicUrl"),
        "full_name": it.get("fullName") or "",
        "bio": it.get("biography") or "",
        "is_verified": bool(it.get("verified")),
        "is_private": bool(it.get("private")),
        "followers": num(it.get("followersCount")),
        "following": num(it.get("followsCount")),
        "posts_count": num(it.get("postsCount")),
        "recent_posts": posts[:POSTS_PER_PROFILE],
    }


def archive_posts(username, posts, ts):
    """Tiene l'ultima versione di ogni post visto, per la tabella e gli orari migliori."""
    path = os.path.join(POSTS_DIR, f"{username}.json")
    archive = load_json(path, {})
    for p in posts:
        if not p.get("shortcode"):
            continue
        entry = archive.get(p["shortcode"], {"first_seen": ts})
        entry.update(p)
        entry["updated"] = ts
        archive[p["shortcode"]] = entry
    newest = sorted(archive.items(), key=lambda kv: kv[1].get("ts") or 0, reverse=True)
    save_json(path, dict(newest[:MAX_ARCHIVED_POSTS]))


def avg(values):
    vals = [v for v in values if isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 1) if vals else None


def load_usernames():
    """Dalla lista gestita dalla dashboard; se non c'è, dal secret PROFILES
    (username separati da virgola, spazio o a capo), altrimenti da profiles.json."""
    managed = load_json(MANAGED_PROFILES, {}).get("profiles")
    raw = os.environ.get("PROFILES", "").replace(",", " ").split()
    names = managed if isinstance(managed, list) else (raw or load_json(PROFILES_FILE, []))
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

    print(f"Avvio: {len(usernames)} profili da aggiornare")
    latest = load_json(LATEST_FILE, {"profiles": {}})
    profiles = latest.get("profiles", {})
    ts = now_iso()
    ok_count = 0

    apify = None
    apify_error = None
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if token:
        print("Fonte: Apify")
        try:
            apify = fetch_apify(usernames, token)
        except Exception as e:  # noqa: BLE001
            apify, apify_error = {}, str(e)
        missing, reused = [], 0
        for u, it in apify.items():
            if not it.get("username") or it.get("private") or it.get("latestPosts"):
                continue
            prev = profiles.get(u, {})
            last = prev.get("posts_fetched_at")
            if (last and prev.get("recent_posts") and datetime.now(timezone.utc) - datetime.fromisoformat(last)
                    < timedelta(hours=POSTS_REFRESH_HOURS)):
                it["_reuse_posts"], it["_posts_fetched_at"] = prev["recent_posts"], last
                reused += 1
            else:
                missing.append(u)
        if reused:
            print(f"Post di {reused} profili già letti nelle ultime {POSTS_REFRESH_HOURS} ore: riuso quelli")
        if missing:
            print(f"Post mancanti per {len(missing)} profili: li chiedo allo scraper dei post")
            try:
                extra = fetch_apify_posts(missing, token)
                for u in missing:
                    apify[u]["_extra_posts"], apify[u]["_posts_fetched_at"] = extra.get(u, []), ts
            except Exception as e:  # noqa: BLE001
                print(f"  non riuscito: {e}")
    else:
        print("Fonte: Instagram diretto (nessun APIFY_TOKEN)")

    for i, username in enumerate(usernames):
        if i and apify is None:
            time.sleep(random.uniform(8, 18))  # ritmo "umano" tra un profilo e l'altro
        # Il repo è pubblico e i log di Actions pure: niente username nei log
        print(f"Profilo {i + 1}/{len(usernames)}")
        try:
            if apify is None:
                data = parse_user(fetch_profile(username))
            else:
                item = apify.get(username)
                if apify_error or not item:
                    raise RuntimeError(apify_error or "profilo non restituito da Apify")
                if item.get("error") or not item.get("username"):
                    raise RuntimeError("profilo inesistente o non leggibile")
                data = parse_apify(item, item.get("_extra_posts"))
                if item.get("_reuse_posts"):
                    data["recent_posts"] = item["_reuse_posts"]
                if item.get("_posts_fetched_at"):
                    data["posts_fetched_at"] = item["_posts_fetched_at"]
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
        if not (apify and apify.get(username, {}).get("_reuse_posts")):
            archive_posts(username, posts, ts)

    # Togli dalla dashboard i profili rimossi da profiles.json (lo storico resta)
    profiles = {u: profiles[u] for u in usernames if u in profiles}
    save_json(LATEST_FILE, {"updated": ts, "order": usernames, "profiles": profiles})

    print(f"\nFatto: {ok_count}/{len(usernames)} profili aggiornati.")
    return 0 if ok_count else 1  # rosso su GitHub solo se fallisce tutto


if __name__ == "__main__":
    sys.exit(main())
