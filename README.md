# WR CN Meta Viewer

MVP em FastAPI para visualizar meta de campeões por rota e tier, com métricas de **winrate**, **pickrate**, **banrate** e múltiplas visões de score (**Draft Priority** e **Power (PBI-like)**).

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
- `GET /meta?role=<top|jungle|mid|adc|support>&tier=<diamond|master|challenger>&source=<auto|sample|cn>&name_lang=<global|cn>&view=<draft|power>&sort=<champion|win|pick|ban|draft_score|power_score>&dir=<asc|desc>`
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
curl "http://127.0.0.1:8000/meta?role=top&tier=diamond&source=auto&view=power&sort=power_score&dir=desc"
```

### Vistas e ordenação na UI

- A página principal possui duas abas acima da tabela:
  - **Draft Priority** (`view=draft`)
  - **Power (PBI-like)** (`view=power`)
- O clique no cabeçalho da tabela ordena por coluna (`Champion`, `Win`, `Pick`, `Ban`, `Draft Priority`/`Power`) alternando `asc/desc` com indicador visual.
- O estado atual de aba e ordenação permanece ao trocar role/tier e clicar em **Carregar**.

### Coleta CN real + cache

- Página oficial usada para descoberta: `https://lolm.qq.com/act/a20220818raider/index.html`
- Cache local: `data/cn_meta_cache.json`
- O cache salva o payload bruto CN por tier (all positions), e o filtro por rota (`position`) acontece por request.
- TTL do cache: **6 horas**
- Metadados em cache: `fetched_at` e `source_url`
- Rate limit global para `qq.com`: no máximo **1 request a cada 10s**
- Backoff em `429/503`: `2s`, `4s`, `8s` (máx. 3 tentativas)

### Mapeamentos internos

Como os códigos do endpoint CN não são 1:1 com os filtros da API local, foi aplicado mapeamento:

- Role:
  - `top -> 1`
  - `jungle -> 2`
  - `mid -> 3`
  - `adc -> 4`
  - `support -> 5`
- Tier:
  - `diamond -> 1` (钻石以上)
  - `master -> 2` (大师以上)
  - `challenger -> 3` (王者)

Quando o endpoint não trouxer nome canônico do campeão, o app normaliza para `hero_<hero_id>`.

Deduplicação por rota:

- Depois de filtrar por `position`, os itens são deduplicados por `hero_id`.
- Se houver duplicidade, vence o registro com maior `priority_score`; em empate, maior `banrate`; persistindo, maior `pickrate`.

### Nome dos campeões no `/meta`

- O cache `data/cn_hero_map.json` agora salva, por campeão, os campos:
  - `hero_name_cn`: valor original de `name` no `hero_list.js` (chinês).
  - `hero_name_global`: derivado de `poster` (basename sem sufixo `_<digits>.<ext>`).
- No endpoint `/meta`, `champion` usa **global** por padrão (`name_lang=global`).
- `name_lang=cn` força exibição do nome chinês quando disponível.
- Fallbacks de nome seguem esta ordem:
  - `global`: `hero_name_global` -> `hero_name_cn` -> `hero_<id>`
  - `cn`: `hero_name_cn` -> `hero_name_global` -> `hero_<id>`

### Cálculo dos scores

```text
PriorityScore = 0.5 * banrate + 0.3 * pickrate + 0.2 * winrate

wr_avg = média de winrate do conjunto filtrado (role+tier)

PowerScore = (winrate - wr_avg) * sqrt(pickrate) / (1 - banrate + 0.01)

contest = 0.6 * banrate + 0.4 * pickrate
strength = (winrate - wr_avg)
DraftScore = zscore(strength) + zscore(contest)
```

As taxas (`winrate`, `pickrate`, `banrate`) usam escala `0..1`; os scores derivados podem assumir valores negativos/positivos conforme o dataset filtrado.

## Testes

```bash
pytest
```
