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
- `GET /meta?role=<top|jungle|mid|adc|support>&tier=<diamond|master|challenger>`

### Cálculo do PriorityScore

```text
PriorityScore = 0.5 * banrate + 0.3 * pickrate + 0.2 * winrate
```

Todos os valores são normalizados entre `0` e `1`.

## Testes

```bash
pytest
```
