# Runbook — Operação

> Baseado no template da §7.2 do `CONTRATO_TRABALHO_FINAL.md`. Adaptado para
> **Docker Compose** (o projeto não usa systemd — ver [`ARQUITETURA.md`](ARQUITETURA.md)
> "Decisões técnicas" para o porquê).

## Pré-requisitos

- Docker + Docker Compose instalados (local ou na VPS).
- `.env` preenchido a partir de `.env.example` (`YOUTUBE_API_KEY`,
  `HISTORICAL_START_DATE`, `ENVIRONMENT`) — **nunca commitado no Git**.

## Rodar localmente

```bash
cp .env.example .env   # preencha YOUTUBE_API_KEY (opcional — sem ela só funciona modo_demo)
docker compose up --build
```

| Serviço | URL local |
|---|---|
| Dashboard (Streamlit) | http://localhost |

Rodar um ciclo manual sem esperar o agendamento:

```bash
docker compose exec api python -m doctrend_ingestor.scheduler --once
docker compose exec api python -m doctrend_ingestor.scheduler --status
```

## Produção (VPS — Docker Compose)

O deploy é automático: todo merge na `main` dispara `.github/workflows/cd-deploy.yml`,
que sincroniza o código via `rsync` e roda `docker compose up -d --build --remove-orphans`
na VPS via SSH. Não precisa intervenção manual no dia a dia.

**Status**
```bash
ssh deploy@187.77.248.197
cd /opt/doctrend
docker compose ps
docker compose exec api python -m doctrend_ingestor.scheduler --status
```

**Reiniciar sem rebuild** (ex.: depois de editar `.env` na mão)
```bash
docker compose restart api frontend
```

**Forçar rebuild manual** (normalmente desnecessário — o CD já faz isso)
```bash
docker compose up -d --build --remove-orphans
```

**Parar tudo**
```bash
docker compose down          # mantém o volume datalake_data
docker compose down -v       # CUIDADO: apaga o volume (perde todo o histórico coletado)
```

**Logs (observabilidade)**
```bash
docker compose logs -f api          # tempo real, ingestor
docker compose logs -f frontend     # tempo real, dashboard
docker compose logs --tail 50 api   # últimas 50 linhas
```

## Adicionar / remover um canal

Editar
[`api/doctrend_ingestor/config/canais.yaml`](../api/doctrend_ingestor/config/canais.yaml):

- **Adicionar:** copiar um bloco existente, trocar `nome`/`channel_id`. Sem
  `channel_id`? Resolver a partir do `@handle` (gasta 1 unidade de cota):
  ```bash
  docker compose exec api python -m doctrend_ingestor.scripts.resolver_handle @nomedocanal
  ```
- **Remover:** apagar o bloco ou marcar `ativo: false`. Não apaga o histórico já
  coletado no datalake — só para de coletar vídeo novo desse canal.

Depois: `git add`, `git commit`, `git push`, abrir PR, aguardar CI verde, mergear.
O CD faz o resto.

## Troubleshooting

| Sintoma | Causa provável | Ação |
|---|---|---|
| `descobertos: 0` no ciclo | fora da `janela_descoberta_dias` ou watermark já passou do vídeo mais recente | conferir `channel_watermark` no SQLite; normal se o canal não postou nada recente |
| Gold vazio | nenhum Silver (transcrição nem metadados) ainda persistido | rodar `--once` manualmente e checar `docker compose logs api` |
| `error=IpBlocked` em muitos vídeos | bloqueio de IP de datacenter contra `youtube_transcript_api` (VPS é afetada) | esperado, sem solução gratuita — o Gold continua funcionando via a camada de metadados |
| `error=TranscriptsDisabled` | o canal desabilitou legendas nesse vídeo | esperado, sem contorno — segue via metadados |
| Erro de cota da API (`quotaExceeded`) | muitos canais / intervalo curto demais | aumentar `intervalo_min` em `canais.yaml`; a estratégia atual usa ~2 unidades/canal/ciclo |
| Dashboard fora do ar | container `frontend` caiu ou não ficou `healthy` | `docker compose ps`; `docker compose logs frontend`; `docker compose restart frontend` |
| `docker compose ps` mostra containers antigos depois de um deploy | reconstrua manualmente: `docker compose up -d --build --remove-orphans` (não deveria mais acontecer — bug de detecção de mudanças via `git log` no CD foi corrigido) |

## Contatos

| Papel | Nome | Contato |
|---|---|---|
| Autor / deploy | Arthur Natureza | arthurnatureza@gmail.com |
