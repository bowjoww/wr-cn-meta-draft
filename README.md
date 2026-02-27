# WR CN Meta Viewer

MVP em FastAPI para visualizar meta de campeões por rota e tier, com métricas de **winrate**, **pickrate**, **banrate** e **PriorityScore**.

## Requisitos

- Python 3.10+

## Como rodar

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abra no navegador:

- http://127.0.0.1:8000/

## Endpoints

- `GET /health` → `{"status":"ok"}`
- `GET /meta?role=<top|jungle|mid|adc|support>&tier=<diamond|master|challenger>&source=<auto|sample|cn>&name_lang=<global|cn>`
- `GET /meta/source`

### Fontes de dados (`source`)

- `source=auto` (padrão): tenta cache CN e, se necessário, busca no site oficial. Em caso de falha, faz fallback para sample.
- `source=sample`: força uso de `data/sample_cn_meta.json`.
- `source=cn`: força CN/cache CN; se falhar, retorna `502` com mensagem clara.

Exemplos:

```bash
curl "http://127.0.0.1:8000/meta?role=top&tier=diamond&source=auto"
curl "http://127.0.0.1:8000/meta?role=top&tier=diamond&source=sample"
curl "http://127.0.0.1:8000/meta?role=top&tier=diamond&source=cn"
curl "http://127.0.0.1:8000/meta?role=top&tier=diamond&source=cn&name_lang=cn"
```

### Coleta CN real + cache

- Página oficial usada para descoberta: `https://lolm.qq.com/act/a20220818raider/index.html`
- Cache local: `data/cn_meta_cache.json`
- TTL do cache: **6 horas**
- Metadados em cache: `fetched_at` e `source_url`
- Rate limit global para `qq.com`: no máximo **1 request a cada 10s**
- Backoff em `429/503`: `2s`, `4s`, `8s` (máx. 3 tentativas)

### Mapeamentos internos

Como os códigos do endpoint CN não são 1:1 com os filtros da API local, foi aplicado mapeamento:

- Role:
  - `top -> 2`
  - `jungle -> 5`
  - `mid -> 3`
  - `adc -> 4`
  - `support -> 6`
- Tier:
  - `diamond -> 1` (钻石以上)
  - `master -> 2` (大师以上)
  - `challenger -> 3` (王者)

Quando o endpoint não trouxer nome canônico do campeão, o app normaliza para `hero_<hero_id>`.


### Nome dos campeões no `/meta`

- O cache `data/cn_hero_map.json` agora salva, por campeão, os campos:
  - `hero_name_cn`: valor original de `name` no `hero_list.js` (chinês).
  - `hero_name_global`: derivado de `poster` (basename sem sufixo `_<digits>.<ext>`).
- No endpoint `/meta`, `champion` usa **global** por padrão (`name_lang=global`).
- `name_lang=cn` força exibição do nome chinês quando disponível.
- Fallbacks de nome seguem esta ordem:
  - `global`: `hero_name_global` -> `hero_name_cn` -> `hero_<id>`
  - `cn`: `hero_name_cn` -> `hero_name_global` -> `hero_<id>`

### Cálculo do PriorityScore

```text
PriorityScore = 0.5 * banrate + 0.3 * pickrate + 0.2 * winrate
```

Todos os valores são normalizados entre `0` e `1`.

## Testes

```bash
pytest
```
