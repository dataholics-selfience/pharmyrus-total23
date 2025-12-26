# Pharmyrus v25 - Multi-Country Patent Search API

API para busca de patentes farmacêuticas em múltiplos países.

## Endpoints

### POST /search
Busca patentes para uma molécula em países específicos.

**Request:**
```json
{
  "nome_molecula": "darolutamide",
  "nome_comercial": "Nubeqa",
  "paises_alvo": ["BR", "US", "MX", "AR"],
  "incluir_wo": true,
  "max_results": 100
}
```

**Response:**
```json
{
  "metadata": {...},
  "summary": {
    "total_wos": 139,
    "total_patents": 45,
    "by_country": {"BR": 17, "US": 15, "MX": 8, "AR": 5}
  },
  "wo_patents": ["WO2011051540", ...],
  "patents_by_country": {...},
  "all_patents": [...]
}
```

### GET /countries
Lista países suportados.

### GET /health
Health check.

## Países Suportados

- BR - Brazil
- US - United States
- EP - European Patent
- CN - China
- JP - Japan
- KR - South Korea
- IN - India
- MX - Mexico
- AR - Argentina
- CL - Chile
- CO - Colombia
- PE - Peru
- CA - Canada
- AU - Australia
- RU - Russia
- ZA - South Africa

## Deploy

```bash
railway up
```
