# Arquitetura

> Baseado no template da §7.2 do `CONTRATO_TRABALHO_FINAL.md` da disciplina.

## Visão geral

Lakehouse em camadas, adaptado de `projeto_modelo/youtube_ingestor` (prof. Cassio
Pinheiro). Diferença deliberada em relação ao template padrão da disciplina: em vez
de systemd, o deploy é via **Docker Compose** (decisão do autor — ver
"Decisões técnicas" abaixo).

```
descobrir (incremental via watermark, YouTube Data API v3)
   └─ para TODO video descoberto (mesmo o ja ingerido):
         registrar snapshot de metricas (views/likes/comments) ... metrics_snapshot (SQLite)
         persistir titulo+descricao+tags limpos ................ SILVER "metadata" (Parquet)
   └─ para cada video NOVO e NAO-ingerido (idempotencia):
         captar transcricao (youtube_transcript_api) ........... BRONZE
         limpar + contrato Pandera .............................. SILVER (Parquet, dominio=/dt=)
         (falha de contrato -> _quarentena/, nao descarta)
         atualizar estado SQLite (idempotencia: video_id + content_hash)
   └─ rodar analitico do dominio (DuckDB, une transcricao+metadados) . GOLD
   └─ avancar o watermark do canal

Apresentacao: dashboard Streamlit le o GOLD (Parquet) + controle (SQLite)
Producao:     Docker Compose (2 servicos: api + frontend) na VPS, deploy via GitHub Actions
```

## Camadas

| Camada | O que faz neste projeto | Onde |
|---|---|---|
| **Bronze** | Captura bruta da transcrição (`youtube_transcript_api`, `video_id` → texto) | `api/doctrend_ingestor/ingestor/transcript.py` |
| **Silver** | Limpeza + contrato Pandera (transcrição **e** metadados) + quarentena | `api/doctrend_ingestor/ingestor/pipeline.py` |
| **Gold** | Densidade de menções do vocabulário de saúde, unindo transcrição + título/descrição/tags | `pipeline.py` (`_gold`, via DuckDB) |
| **Controle** | Watermark por canal + idempotência (`content_hash`) + snapshots de métricas | `ingestor/state.py` (SQLite, `StateStore`) |
| **Agendamento** | Ingestão perene por canal (APScheduler, intervalo declarado em `canais.yaml`) | `scheduler.py` + `config/canais.yaml` |
| **Apresentação** | Dashboard de insights | `frontend/streamlit_app.py` |

## Decisões técnicas

- **Docker Compose em vez de systemd (divergência deliberada do template da
  disciplina):** o autor optou por manter a stack inteira dockerizada — inclusive
  para treinar CI/CD via GitHub Actions como exercício adicional — em vez de
  systemd puro na VPS. Efeito prático: o `deploy/` com `.service` do template não
  se aplica aqui; o equivalente é `docker-compose.yml` + `.github/workflows/`.
- **Parquet particionado por `dominio=`/`dt=`:** a ingestão é contínua e cobre
  vários canais/domínio; particionar por data torna a leitura incremental barata e
  evita reescrever o histórico inteiro a cada ciclo.
- **SQLite só para controle, nunca para os dados em si:** o volume de dados
  (transcrição, metadados, Gold) escala mais rápido do que o que faz sentido
  guardar num único arquivo SQLite; watermark e idempotência, por outro lado, são
  exatamente o tipo de leitura/escrita pontual (`PRIMARY KEY`, `UPSERT`) que SQLite
  resolve bem sem precisar de um serviço de banco à parte.
- **Estratégia de cota da API (`playlistItems.list` em vez de `search.list`):**
  `search.list` custa 100 unidades por chamada; a estratégia usada
  (`channels.list` uma vez para achar a playlist de uploads, depois
  `playlistItems.list` + `videos.list` em lote) custa ~2 unidades por canal por
  ciclo — dá para rodar os 10 canais várias vezes ao dia bem dentro do limite
  diário gratuito de 10.000 unidades.
- **Frequência de ingestão (360 min / 6h por canal):** conteúdo de saúde não tem a
  urgência de notícia (diferente de geopolítica ou mercado financeiro no exemplo
  do professor), mas rodar 4x/dia em vez de 1x/dia gera mais pontos na curva de
  velocidade de views/likes (`metrics_snapshot`) sem custo relevante de cota.
- **Camada de metadados (título+descrição+tags) como Silver paralelo:** descoberta
  na prática — a `youtube_transcript_api` é bloqueada por IP de datacenter/VPS
  (`IpBlocked`) na maioria das chamadas, tanto em ambiente de desenvolvimento
  quanto na própria VPS de produção. Sem essa camada, o Gold ficaria vazio sempre
  que o bloqueio ocorresse. Com ela, todo vídeo descoberto contribui com pelo
  menos título/descrição/tags (que a Data API real já devolve de graça, sem
  chamada extra), mesmo que a transcrição falhe.
- **Como o Gold responde às perguntas da Carta:** a tabela
  `densidade_termos.parquet` (termo × menções × vídeos distintos) responde
  diretamente as perguntas 1 e 2; a pergunta 3 (velocidade de crescimento) é
  respondida pela série temporal em `metrics_snapshot`, exposta no dashboard como
  gráfico de views/likes por vídeo ao longo do tempo.

## Princípios de engenharia (§4.2 — avaliados)

- **Idempotência:** `StateStore.ja_ingerido` checa `status='INGESTED'` +
  `content_hash` antes de reprocessar um vídeo; rodar o mesmo ciclo N vezes não
  duplica arquivo Parquet nem linha no Gold (o Gold é recalculado do zero a cada
  ciclo a partir do Silver acumulado, não é incrementado).
- **Tratamento de erro:** toda falha (sem legenda, IP bloqueado, contrato Pandera
  inválido) é capturada e registrada — nunca propaga e derruba o ciclo de outro
  vídeo/canal. Linhas que falham o contrato Silver vão para `_quarentena/` com uma
  coluna `motivo`, em vez de serem descartadas silenciosamente.
- **Rastreabilidade:** `ingestion_state` guarda status por vídeo
  (`DISCOVERED`/`INGESTED`/`FAILED`) e o motivo real da falha (`IpBlocked`,
  `TranscriptsDisabled`, erro de schema etc.) — não um genérico "sem legenda"
  para tudo.
- **Observabilidade:** logs estruturados (`logging`, um resumo por ciclo/canal);
  `python -m doctrend_ingestor.scheduler --status` mostra a contagem de vídeos por
  status sem precisar abrir o código ou um editor SQL.
