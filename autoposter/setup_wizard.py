"""Interactive first-run setup: asks for the keys, connects the Instagram account,
tests everything and saves it in .env."""
import os
import webbrowser

import requests

from .config import ROOT

ENV_FILE = ROOT / ".env"


def _save_env(values: dict) -> None:
    lines, seen = [], set()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            key = line.split("=", 1)[0].strip()
            if key in values:
                lines.append(f"{key}={values[key]}")
                seen.add(key)
            else:
                lines.append(line)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ.update(values)


def _ask(prompt: str, current: str | None = None, optional=False) -> str:
    hint = " [Enter = păstrează cea salvată]" if current else (" [Enter = sari peste]" if optional else "")
    while True:
        value = input(f"{prompt}{hint}: ").strip()
        if value:
            return value
        if current:
            return current
        if optional:
            return ""


def _open(url: str) -> None:
    print(f"   -> {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass


def run_setup(cfg: dict) -> None:
    from .instagram import InstagramError, check_connection, connect_account

    print("\n================  CONFIGURARE (doar prima dată)  ================\n")

    # 1. Gemini
    print("1) Cheia Google Gemini (gratuită) - scrie textele și caption-urile.")
    _open("https://aistudio.google.com/apikey")
    while True:
        key = _ask("   Lipește cheia Gemini", os.environ.get("GEMINI_API_KEY"))
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": key}, timeout=30)
        if r.ok:
            _save_env({"GEMINI_API_KEY": key})
            print("   ✓ Cheia Gemini funcționează.\n")
            break
        print(f"   ✗ Cheia nu merge ({r.status_code}). Mai încearcă.")

    # 2. Pexels (optional)
    if cfg["video"].get("background") == "pexels":
        print("2) Cheia Pexels (gratuită) - clipuri video pentru fundal.")
        _open("https://www.pexels.com/api/new/")
        key = _ask("   Lipește cheia Pexels", os.environ.get("PEXELS_API_KEY"), optional=True)
        if key:
            _save_env({"PEXELS_API_KEY": key})
        print()

    # 3. Instagram
    print("3) Conectarea contului de Instagram (API-ul oficial Meta, fără parolă).")
    print("   Ai nevoie de: cont Instagram Business/Creator legat de o pagină de Facebook,")
    print("   și o aplicație pe developers.facebook.com (pașii sunt în README.md).")
    if os.environ.get("IG_USER_ID") and os.environ.get("IG_ACCESS_TOKEN"):
        try:
            user = check_connection(cfg)
            if input(f"   Ești deja conectat ca @{user}. Reconectezi? (d/N): ").strip().lower() != "d":
                print("   ✓ Gata!\n")
                return
        except Exception:
            print("   Conexiunea salvată nu mai merge, o refacem.")

    app_id = _ask("   App ID (din App settings → Basic)", os.environ.get("META_APP_ID"))
    app_secret = _ask("   App Secret", os.environ.get("META_APP_SECRET"))
    _save_env({"META_APP_ID": app_id, "META_APP_SECRET": app_secret})
    print("\n   Acum se deschide Graph API Explorer. Alege aplicația ta, apasă 'Generate Access Token'")
    print("   și bifează: instagram_basic, instagram_content_publish, pages_show_list,")
    print("   pages_read_engagement, business_management. Apoi copiază token-ul.")
    _open("https://developers.facebook.com/tools/explorer/")
    while True:
        short = _ask("   Lipește token-ul din Explorer")
        try:
            accounts = connect_account(app_id, app_secret, short, cfg["instagram"]["graph_version"])
        except InstagramError as e:
            print(f"   ✗ Nu a mers: {e}\n   Verifică App ID/Secret și permisiunile, apoi încearcă iar.")
            continue
        if not accounts:
            print("   ✗ N-am găsit niciun cont Instagram Business legat de paginile tale de Facebook.")
            continue
        break

    if len(accounts) == 1:
        acc = accounts[0]
    else:
        for i, a in enumerate(accounts, 1):
            print(f"   {i}) @{a['username']}  (pagina {a['page']})")
        acc = accounts[int(_ask("   Pe care cont postez? (număr)")) - 1]
    _save_env({"IG_USER_ID": acc["ig_user_id"], "IG_ACCESS_TOKEN": acc["token"]})
    print(f"   ✓ Conectat la @{check_connection(cfg)}. Token-ul nu expiră.\n")
