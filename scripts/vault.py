"""
Cifra/decifra i dati del tracker con la password della dashboard.

  python scripts/vault.py decrypt   docs/data.enc -> docs/data/ (in chiaro, mai committato)
  python scripts/vault.py encrypt   docs/data/    -> docs/data.enc

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


def encrypt(password):
    if not os.path.exists(LATEST_FILE):
        print("Nessun dato da cifrare.")
        return 0
    bundle = {"latest": load_json(LATEST_FILE), "history": {}}
    for path in glob.glob(os.path.join(HIST_DIR, "*.json")):
        bundle["history"][os.path.basename(path)[:-5]] = load_json(path)
    plain = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(derive_key(password, salt, ITERATIONS)).encrypt(iv, plain, None)
    with open(VAULT_FILE, "w", encoding="ascii") as f:
        json.dump({"v": 1, "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}, f)
    print(f"Dati cifrati in docs/data.enc ({len(bundle['history'])} storici).")
    return 0


def decrypt(password):
    if not os.path.exists(VAULT_FILE):
        print("Nessun file cifrato: primo giro.")
        return 0
    v = load_json(VAULT_FILE)
    key = derive_key(password, base64.b64decode(v["salt"]), v["iter"])
    try:
        plain = AESGCM(key).decrypt(base64.b64decode(v["iv"]), base64.b64decode(v["ct"]), None)
    except Exception:  # noqa: BLE001
        print("::error::Impossibile decifrare docs/data.enc: la password (DASHBOARD_PASSWORD) "
              "è diversa da quella usata in precedenza.")
        return 1
    bundle = json.loads(plain)
    save_json(LATEST_FILE, bundle["latest"])
    for username, history in bundle["history"].items():
        save_json(os.path.join(HIST_DIR, f"{username}.json"), history)
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
