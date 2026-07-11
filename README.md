# DocTrend

Equipe: Arthur Natureza, Eliak Lima, Raul Teles e Renan Madeira

Projeto acadêmico da disciplina **Linguagem de Programação para Engenharia de Dados**
(Pós-Graduação em Engenharia de Dados). Pipeline de dados que coleta vídeos, métricas
e transcrições de canais de **Saúde** no YouTube para identificar quais doenças, sintomas
e temas de saúde são mais abordados — e quais geram mais engajamento (visualizações,
curtidas) — sem se preocupar em ranquear canais.

**Dashboard publicado:** http://187.77.248.197

## O que tem no dashboard

- **KPI em destaque**: o tema de saúde mais mencionado no período.
- **Ranking de termos**: quantas menções e em quantos vídeos distintos cada termo do
  vocabulário (diabetes, ansiedade, hipertensão, depressão etc.) aparece.
- **Curva de velocidade**: views/likes de um vídeo ao longo do tempo — cada ciclo de
  coleta grava um snapshot, então dá pra comparar D-1, D+7, D+15 e ver se um tema está
  ganhando ou perdendo tração.
- **Métricas de confiabilidade**: quantos vídeos foram ingeridos, quantos falharam,
  quando foi a última coleta.

## Arquitetura

```
┌──────────────────────────────────────────────────────────────┐
│                      Docker Compose (VPS)                     │
│                                                                │
│  ┌────────────────┐              ┌─────────────────────────┐ │
│  │   api           │   escreve   │      frontend            │ │
│  │  (ingestor +    │ ──────────► │  (dashboard Streamlit,    │ │
│  │   scheduler)    │             │   le o mesmo volume)      │ │
│  └────────┬────────┘             └─────────────┬─────────────┘ │
│           │                                    │               │
│           ▼                     volume: datalake_data          │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  control/ingestion.db (SQLite: watermark + idempotência)  │ │
│  │  silver/dominio=saude/dt=.../*.parquet   (transcrição)    │ │
│  │  silver/dominio=saude/metadata/*.parquet (título+desc+tag)│ │
│  │  silver/dominio=saude/_quarentena/dt=.../*.parquet        │ │
│  │  gold/dominio=saude/densidade_termos.parquet               │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

- **Bronze → Silver → Gold**, adaptado de `projeto_modelo/youtube_ingestor` do
  professor Cassio Pinheiro. `discovery.py` usa a YouTube Data API v3 (título, views,
  likes, data de publicação); `transcript.py` usa a biblioteca separada
  `youtube_transcript_api` (não oficial) para captar a legenda a partir do `video_id`.
  São duas fontes diferentes — a Data API nunca devolve transcrição, e vice-versa.
- **SQLite** guarda só o controle (watermark por canal + idempotência via
  `content_hash`) — os dados em si (transcrição, metadados, Gold) ficam em
  **Parquet**, particionado por domínio e data.
- Todo vídeo descoberto entra em `silver/.../metadata/`, mesmo que a transcrição
  falhe depois — assim o Gold ainda enxerga título/descrição/tags de vídeos sem
  legenda disponível.
- Linhas que violam o contrato Pandera do Silver vão para `_quarentena/` em vez de
  serem descartadas silenciosamente.
- Deploy: GitHub Actions (CI de lint em todo PR, CD que builda e sobe os dois
  serviços via Docker Compose na VPS a cada push na `main`).

## Canais monitorados e limitação conhecida

Os 10 canais de Saúde estão em
[`api/doctrend_ingestor/config/canais.yaml`](api/doctrend_ingestor/config/canais.yaml).

**Sobre transcrições ausentes:** a `youtube_transcript_api` (biblioteca usada para
captar legendas) é bloqueada pela YouTube para IPs de provedores de nuvem/datacenter
— e isso afeta tanto ambientes de desenvolvimento quanto a própria VPS de produção.
Não é um problema de configuração do projeto nem de um canal específico: é uma
política da Google contra esse tipo de IP, sem solução gratuita (contornos reais
exigem proxy residencial pago). Por isso boa parte dos vídeos aparece com
`status=FAILED` e `error=IpBlocked` no banco de controle. A camada de metadados
(título + descrição + tags, que vem de graça na descoberta) existe justamente para
que o Gold não fique vazio quando isso acontece. Vídeos onde o próprio canal
desabilitou legendas aparecem como `error=TranscriptsDisabled` — esse caso é
legítimo e não tem contorno (nem pago).

## Adicionando ou removendo um canal

Editar [`config/canais.yaml`](api/doctrend_ingestor/config/canais.yaml):
adicionar um bloco novo (copie um existente e troque `nome`/`channel_id`) ou apagar
um bloco / marcar `ativo: false`. Não precisa de `channel_id`? Rode (dentro do
container `api`, gasta 1 unidade de cota por canal):

```bash
docker compose exec api python -m doctrend_ingestor.scripts.resolver_handle @nomedocanal
```

Depois é só `git commit` + `git push` + abrir PR + merge — o deploy acontece sozinho.

## Rodando localmente

> Rodar localmente (sua máquina, IP residencial) é útil não só para
> desenvolvimento: como a `youtube_transcript_api` bloqueia IPs de
> datacenter/VPS (ver seção acima), transcrições que falham na VPS podem
> funcionar rodando daqui de casa. Pode valer usar isso pra mostrar
> resultados com transcrição completa, e não só via metadados.

### 1. Pré-requisitos

- Docker + Docker Compose instalados ([docs oficiais](https://docs.docker.com/get-docker/)).
- Git.

### 2. Clonar e configurar

```bash
git clone git@github.com:arthurnatureza/doctrend.git
cd doctrend
cp .env.example .env
```

Edite o `.env` e preencha pelo menos `YOUTUBE_API_KEY` (sem ela, só o
`modo_demo: true` funciona — ver `api/doctrend_ingestor/config/canais.yaml`).
`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` são opcionais — deixe em branco se não
quiser notificação rodando local (evita duplicar aviso se a VPS já está
notificando).

### 3. Subir os containers

```bash
docker compose up --build -d
docker compose ps          # confirma os dois containers "healthy"
```

| Serviço | URL local | O que é |
|---|---|---|
| Dashboard | **http://localhost** | abra no navegador — mesmo dashboard da VPS, com os dados coletados localmente |
| Ingestor (`api`) | sem porta exposta, roda em background | consultar via `docker compose logs`/`exec`, ver abaixo |

### 4. Rodar um ciclo manual (sem esperar o agendamento)

```bash
docker compose exec api python -m doctrend_ingestor.scheduler --once     # 1 ciclo em todos os canais ativos
docker compose exec api python -m doctrend_ingestor.scheduler --status   # resumo do estado (INGESTED/FAILED/...)
```

Depois de rodar `--once`, recarregue http://localhost no navegador — o
dashboard lê o mesmo volume que o ingestor acabou de escrever (cache de 60s,
`ttl=60` no Streamlit; se não atualizar na hora, espere um pouco ou aperte
"Rerun" no menu do Streamlit).

### 5. Acompanhar logs

```bash
docker compose logs -f api        # ver os ciclos rodando em tempo real
docker compose logs -f frontend   # logs do Streamlit
```

### 6. Parar / limpar

```bash
docker compose down          # para os containers, mantém os dados coletados (volume datalake_data)
docker compose down -v       # também apaga o volume — recomeça do zero
```

## Mais documentação

- [`docs/CARTA_DO_PROJETO.md`](docs/CARTA_DO_PROJETO.md) — problema, propósito, escopo
- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — decisões técnicas em detalhe
- [`docs/RUNBOOK.md`](docs/RUNBOOK.md) — operar, reiniciar, ler logs, diagnosticar
- [`docs/RELATORIO_7_DIAS.md`](docs/RELATORIO_7_DIAS.md) — observação em produção
