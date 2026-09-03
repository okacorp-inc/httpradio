#!/usr/bin/env python3
"""
Verificador de saúde do radios.json.

- Testa cada estação e classifica OK / DOWN / CHECK / SKIP.
- Escreve 'radios-report.md' (relatório legível, usado para abrir issue).
- Escreve/atualiza 'radios-status.json' — status por estação que o APP lê para
  cinzar/desabilitar as indisponíveis e reativá-las quando voltarem. Guarda desde
  quando está fora do ar (since) e quantos dias (daysDown), para ação futura de remoção.
- Código de saída != 0 se houver alguma estação DOWN.

Uso: python tools/check_radios.py [radios.json]
Depende de 'requests'.
"""
import json
import os
import sys
import socket
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

import requests

TIMEOUT = 15
STATUS_FILE = "radios-status.json"
REPORT_FILE = "radios-report.md"
HEADERS = {
    "User-Agent": "HTTPRadio-LinkChecker/1.0 (+https://github.com/)",
    "Icy-MetaData": "0",
    "Accept": "*/*",
}
AUDIO_HINTS = ("audio", "mpeg", "aac", "ogg", "mp3", "octet-stream", "mpegurl", "x-scpls", "x-mpegurl")


def load_stations(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("stations", [])
    return data if isinstance(data, list) else []


def is_playlist(url):
    p = urlsplit(url).path.lower()
    return p.endswith((".pls", ".m3u"))


def resolve(url):
    if not is_playlist(url):
        return url
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    for line in r.text.splitlines():
        line = line.strip()
        if line.lower().startswith("file") and "=" in line:
            return line.split("=", 1)[1].strip()
    for line in r.text.splitlines():
        line = line.strip()
        if line.startswith(("http://", "https://")):
            return line
    raise ValueError("playlist sem URL de stream")


def check_stream(url):
    try:
        direct = resolve(url)
    except Exception as e:
        return "DOWN", f"playlist não resolveu: {e}", url
    try:
        with requests.get(direct, headers=HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=True) as r:
            code = r.status_code
            ctype = (r.headers.get("Content-Type") or "").lower()
            if code >= 400:
                return "DOWN", f"HTTP {code}", direct
            chunk = b""
            try:
                for c in r.iter_content(chunk_size=1024):
                    chunk = c
                    break
            except Exception:
                pass
            if any(h in ctype for h in AUDIO_HINTS):
                return "OK", f"HTTP {code} · {ctype or 'sem content-type'}", direct
            if "html" in ctype or "json" in ctype or "xml" in ctype:
                return "DOWN", f"resposta não-áudio ({ctype})", direct
            if code == 200 and chunk:
                return "CHECK", f"HTTP 200, content-type '{ctype or 'vazio'}' — provável áudio", direct
            return "CHECK", f"HTTP {code}, content-type '{ctype or 'vazio'}'", direct
    except requests.exceptions.SSLError as e:
        return "CHECK", f"erro SSL: {e}", direct
    except (requests.exceptions.ConnectionError, socket.gaierror) as e:
        return "DOWN", f"conexão falhou/DNS: {e}", direct
    except requests.exceptions.Timeout:
        return "DOWN", "timeout", direct
    except Exception as e:
        return "CHECK", f"erro: {e}", direct


def load_prev_status(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8")).get("stations", {})
        except Exception:
            return {}
    return {}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "radios.json"
    if not os.path.exists(path):
        print(f"radios.json não encontrado em: {path}", file=sys.stderr)
        return 2

    stations = load_stations(path)
    prev = load_prev_status(STATUS_FILE)
    today = date.today().isoformat()
    status_map = {}
    rows, down = [], 0

    print(f"Verificando {len(stations)} estações de {path}\n")
    for st in stations:
        name = st.get("name", "(sem nome)")
        url = (st.get("streamUrl") or "").strip()
        if not url:
            tuneid = st.get("tuneInId")
            status, detail, direct = "SKIP", "sem streamUrl" + (f" (tuneInId {tuneid})" if tuneid else ""), ""
        else:
            status, detail, direct = check_stream(url)

        # atualiza status persistente (só para estações com streamUrl)
        if url:
            p = prev.get(url, {})
            if status == "DOWN":
                since = p.get("since") or today
                days = (date.fromisoformat(today) - date.fromisoformat(since)).days
                status_map[url] = {"name": name, "status": "DOWN", "since": since,
                                   "daysDown": days, "lastChecked": today}
                down += 1
            else:
                status_map[url] = {"name": name, "status": status, "since": None,
                                   "daysDown": 0, "lastChecked": today}

        icon = {"OK": "✅", "DOWN": "❌", "CHECK": "⚠️", "SKIP": "⏭️"}.get(status, "•")
        extra = ""
        if url and status_map.get(url, {}).get("status") == "DOWN":
            extra = f" · fora do ar há {status_map[url]['daysDown']} dia(s)"
        print(f"{icon} {status:5} {name} — {detail}{extra}")
        rows.append((icon, status, name, detail, extra))

    # radios-status.json (consumido pelo app)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "stations": status_map}, f, ensure_ascii=False, indent=2)

    # relatório em markdown
    lines = ["# Relatório de rádios", "",
             f"Total: {len(stations)} · ❌ fora do ar: {down}", "",
             "| | Estação | Status | Detalhe |", "|---|---|---|---|"]
    for icon, status, name, detail, extra in rows:
        lines.append(f"| {icon} | {name} | {status} | {detail}{extra} |")
    report = "\n".join(lines) + "\n"
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)

    print(f"\nResumo: {down} fora do ar. Arquivos: {REPORT_FILE}, {STATUS_FILE}")
    return 1 if down > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
