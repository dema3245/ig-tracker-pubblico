"""
Cifra/decifra i dati del tracker con la password della dashboard.

  python scripts/vault.py decrypt   docs/data.enc -> docs/data/ (in chiaro, mai committato)
                                    docs/profiles.enc -> docs/data/profiles.json
  python scripts/vault.py encrypt   docs/data/    -> docs/data.enc

docs/profiles.enc è la lista dei profili salvata dalla dashboard ("Gestisci profili").

La password arriva dalla variabile d'ambiente DASHBOARD_PASSWORD (secret di GitHub).
Formato: AES-256-GCM, chiave derivata con PBKDF2-SHA256. La dashboard usa lo
stesso schema (WebCrypto) per decifrare nel browser.
"""

import base64
import glob
import json
import os
import sys

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "docs", "data")
HIST_DIR = os.path.join(DATA_DIR, "history")
POSTS_DIR = os.path.join(DATA_DIR, "posts")
PROFILES_VAULT = os.path.join(ROOT, "docs", "profiles.enc")
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")
LATEST_FILE = os.path.join(DATA_DIR, "latest.json")
VAULT_FILE = os.path.join(ROOT, "docs", "data.enc")
ITERATIONS = 310_000


def b64(b):
    return base64.b64encode(b).decode("ascii")


def derive_key(password, salt, iterations):
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seal(obj, password):
    plain = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(derive_key(password, salt, ITERATIONS)).encrypt(iv, plain, None)
    return {"v": 1, "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def unseal(path, password):
    """Ritorna il contenuto decifrato, o None se la password non corrisponde."""
    v = load_json(path)
    key = derive_key(password, base64.b64decode(v["salt"]), v["iter"])
    try:
        plain = AESGCM(key).decrypt(base64.b64decode(v["iv"]), base64.b64decode(v["ct"]), None)
    except Exception:  # noqa: BLE001
        return None
    return json.loads(plain)


def read_dir(path):
    return {os.path.basename(f)[:-5]: load_json(f) for f in glob.glob(os.path.join(path, "*.json"))}


def encrypt(password):
    if not os.path.exists(LATEST_FILE):
        print("Nessun dato da cifrare.")
        return 0
    bundle = {"latest": load_json(LATEST_FILE), "history": read_dir(HIST_DIR), "posts": read_dir(POSTS_DIR)}
    with open(VAULT_FILE, "w", encoding="ascii") as f:
        json.dump(seal(bundle, password), f)
    print(f"Dati cifrati in docs/data.enc ({len(bundle['history'])} storici).")
    return 0


def decrypt(password):
    if os.path.exists(PROFILES_VAULT):
        managed = unseal(PROFILES_VAULT, password)
        if managed is None:
            print("::error::Impossibile decifrare docs/profiles.enc: è stato salvato con una password "
                  "diversa da DASHBOARD_PASSWORD.")
            return 1
        save_json(PROFILES_FILE, managed)
        print(f"Lista profili dalla dashboard: {len(managed.get('profiles', []))} profili.")
    if not os.path.exists(VAULT_FILE):
        print("Nessun file di dati cifrato: primo giro.")
        return 0
    bundle = unseal(VAULT_FILE, password)
    if bundle is None:
        print("::error::Impossibile decifrare docs/data.enc: la password (DASHBOARD_PASSWORD) "
              "è diversa da quella usata in precedenza.")
        return 1
    save_json(LATEST_FILE, bundle["latest"])
    for folder, key in ((HIST_DIR, "history"), (POSTS_DIR, "posts")):
        for username, content in bundle.get(key, {}).items():
            save_json(os.path.join(folder, f"{username}.json"), content)
    print("Dati decifrati.")
    return 0


def main():
    password = os.environ.get("DASHBOARD_PASSWORD", "")
    if not password:
        print("::error::Manca il secret DASHBOARD_PASSWORD (Settings → Secrets and variables → Actions).")
        return 1
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "encrypt":
        return encrypt(password)
    if action == "decrypt":
        return decrypt(password)
    print("Uso: python scripts/vault.py encrypt|decrypt")
    return 2


if __name__ == "__main__":
    sys.exit(main())
