#!/usr/bin/env python3
"""
Verificador de saúde do radios.json.

Para cada estação: resolve playlists (.pls/.m3u) para a URL direta e testa o stream,
classificando em:
  OK    - respondeu como áudio (tocável)
  DOWN  - fora do ar (conexão recusada/timeout/DNS, HTTP >= 400, ou página de erro)
  CHECK - resposta ambígua (verificar manualmente)

Uso:
    python tools/check_radios.py [caminho/para/radios.json]

Saída:
    - imprime uma tabela no console
    - escreve 'radios-report.md' (usado pelo workflow para abrir issue)
    - código de saída != 0 se houver alguma estação DOWN

Depende apenas de 'requests' (pip install requests).
"""
import json
import os
import sys
import socket
from urllib.parse import urlsplit

import requests

TIMEOUT = 15
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
    """Playlist -> primeira URL de stream. URL direta é retornada como está."""
    if not is_playlist(url):
        return url
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    txt = r.text
    for line in txt.splitlines():
        line = line.strip()
        if line.lower().startswith("file") and "=" in line:
            return line.split("=", 1)[1].strip()
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith(("http://", "https://")):
            return line
    raise ValueError("playlist sem URL de stream")


def check_stream(url):
    """Retorna (status, detalhe, url_direta)."""
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
            # lê um pouquinho para garantir que há dados
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
                # shoutcast/icecast às vezes não manda content-type padrão
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


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "radios.json"
    if not os.path.exists(path):
        print(f"radios.json não encontrado em: {path}", file=sys.stderr)
        return 2

    stations = load_stations(path)
    rows, down = [], 0
    print(f"Verificando {len(stations)} estações de {path}\n")
    for st in stations:
        name = st.get("name", "(sem nome)")
        url = (st.get("streamUrl") or "").strip()
        if not url:
            tuneid = st.get("tuneInId")
            status, detail = ("SKIP", "sem streamUrl" + (f" (tuneInId {tuneid})" if tuneid else ""))
            direct = ""
        else:
            status, detail, direct = check_stream(url)
        if status == "DOWN":
            down += 1
        icon = {"OK": "✅", "DOWN": "❌", "CHECK": "⚠️", "SKIP": "⏭️"}.get(status, "•")
        print(f"{icon} {status:5} {name} — {detail}")
        rows.append((icon, status, name, detail, url, direct))

    # relatório em markdown
    lines = ["# Relatório de rádios", "", f"Total: {len(stations)} · ❌ fora do ar: {down}", "",
             "| | Estação | Status | Detalhe |", "|---|---|---|---|"]
    for icon, status, name, detail, url, direct in rows:
        lines.append(f"| {icon} | {name} | {status} | {detail} |")
    report = "\n".join(lines) + "\n"
    with open("radios-report.md", "w", encoding="utf-8") as f:
        f.write(report)

    # resumo no GitHub Actions, se aplicável
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)

    print(f"\nResumo: {down} fora do ar. Relatório salvo em radios-report.md")
    return 1 if down > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
