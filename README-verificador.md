# Verificador de rádios — drop-in para o repo do catálogo

Estes arquivos vão para o **repositório que já alimenta o app**:
`okacorp-inc/httpradio` (o app lê `.../okacorp-inc/httpradio/main/radios.json`).
NÃO crie repo novo — isso mantém a lista das versões em uso funcionando.

## Onde colocar
Na raiz do repo `okacorp-inc/httpradio`, junto do `radios.json` que já está lá:

    httpradio/
    ├── radios.json                        (já existe — não mexer no endereço)
    ├── tools/check_radios.py              (novo)
    └── .github/workflows/check-radios.yml (novo)

## Como subir (garante a pasta .github)
    # clonando o repo existente:
    git clone https://github.com/okacorp-inc/httpradio.git
    cd httpradio
    # copie tools/ e .github/ para cá, então:
    git add tools .github
    git commit -m "Verificador automático de rádios"
    git push

## Depois
- Settings → Actions → General → Workflow permissions → **Read and write** (pra abrir issue).
- Actions → "Verificar rádios" → **Run workflow** (teste).
- Roda 2x/dia (06:00 e 18:00 de Brasília). Abre issue atribuída a você quando algo cai e
  fecha sozinha quando volta.

## Nada muda para o app
O `CATALOG_URL` do app continua o mesmo. Este verificador só LÊ o `radios.json` do repo;
não altera endereço nem formato. As versões instaladas seguem lendo a mesma lista.
