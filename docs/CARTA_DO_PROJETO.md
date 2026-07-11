# Carta do Projeto

> Baseado no template da §3 do `CONTRATO_TRABALHO_FINAL.md` da disciplina.

## 3.1 Identidade

| Campo | Preenchimento |
|---|---|
| **Nome do projeto** | DocTrend — Radar de Temas de Saúde no YouTube |
| **Tema / domínio** | Saúde Pública |
| **Equipe** | Arthur Natureza — engenharia de dados, qualidade, deploy e produto (projeto solo) |
| **Data de início** | 2026-07-10 |

## 3.2 Problema e propósito

| Campo | Preenchimento |
|---|---|
| **Problema** | Criadores de conteúdo e equipes de comunicação em saúde não têm visibilidade rápida sobre quais doenças, sintomas e temas estão sendo mais discutidos nos principais canais de saúde do YouTube. Hoje isso exige assistir manualmente dezenas de vídeos por semana para perceber um padrão — inviável de escalar e sujeito a viés (só se percebe o que já se está acompanhando de perto). |
| **Propósito** | Automatiza a coleta diária/perene de vídeos, métricas e transcrições de canais de saúde, cruza o conteúdo com um vocabulário de doenças/sintomas/hábitos, e apresenta em um dashboard quais temas mais aparecem e quanto engajamento (visualizações, curtidas) cada um gera — sem exigir que alguém assista um único vídeo. |
| **Público-alvo** | Criadores de conteúdo de saúde definindo pauta; equipes de comunicação de hospitais/clínicas; qualquer pessoa curiosa sobre quais temas de saúde estão "em alta" no YouTube brasileiro. |
| **Hipótese de valor** | "Se monitorarmos perenemente os principais canais de saúde do YouTube, conseguimos identificar em poucos dias quais temas estão ganhando tração — mais rápido e com menos viés do que o acompanhamento manual." |

## 3.3 Escopo técnico

| Campo | Preenchimento |
|---|---|
| **Fontes de dados** | 10 canais de saúde reais (ver [`config/canais.yaml`](../api/doctrend_ingestor/config/canais.yaml)): Dr. Drauzio Varella, Doutor Ajuda, Dr. Dayan Siebra, Dra. Ana Beatriz Barbosa (PodPeople), Dr. Julio Pereira (Neurocirurgião), Dr. Roberto Yano, Dr. Fernando Lemos (Planeta Intestino), Saúde da Mulher c/ Dra. Laura Lucia, Hospital Albert Einstein, Dr. Lucas Fustinoni. Vocabulário de 28 termos (doenças, sintomas, hábitos). Idiomas de legenda: pt, pt-BR, en. |
| **Frequência de ingestão** | 360 min (6h, 4x/dia) por canal. Justificativa: conteúdo de saúde não é notícia urgente (diferente de geopolítica/mercado), mas rodar várias vezes ao dia gera mais pontos na curva de velocidade de views/likes (`metrics_snapshot`) sem pressionar a cota da API (~2 unidades/canal/ciclo, muito abaixo do limite diário de 10.000). |
| **Métrica principal (KPI)** | Tema de saúde com maior densidade de menções (`mencoes`) no vocabulário, cruzando transcrição + título/descrição/tags dos vídeos coletados. |
| **Perguntas analíticas** | Ver lista abaixo (mínimo 3). |
| **Fora de escopo** | Não ranqueia canais por tamanho/popularidade; não faz diagnóstico médico nem valida a informação de saúde veiculada nos vídeos; não trata YouTube Shorts separadamente do fluxo normal; não analisa comentários dos vídeos. |

### Perguntas analíticas (mínimo 3)

1. Quais doenças/temas de saúde são mais mencionados pelos canais monitorados (transcrição + título/descrição/tags)?
2. Um tema é recorrente (aparece em muitos vídeos distintos) ou concentrado (poucos vídeos falam muito dele)?
3. Como as visualizações e curtidas de um vídeo evoluem nos dias seguintes à publicação (comparando snapshots ao longo do tempo) — um tema está ganhando ou perdendo tração de audiência?

## 3.4 Critérios de sucesso

| Campo | Preenchimento |
|---|---|
| **Definição de pronto** | Pipeline roda sozinho e agendado (sem intervenção manual na ingestão); dashboard publicado em URL estável (`http://187.77.248.197`); 7 dias corridos de observação em produção sem intervenção manual na coleta. |
| **Riscos** | (1) Cota da API esgotar — mitigado pela estratégia de baixo custo (`playlistItems.list`/`videos.list` em vez de `search.list`, ~2 unidades/canal/ciclo). (2) `youtube_transcript_api` bloqueada por IP de datacenter/VPS (`IpBlocked`) — risco confirmado e recorrente, sem solução gratuita; mitigado pela camada de metadados (título/descrição/tags) que mantém o Gold alimentado mesmo sem transcrição. (3) Canal desabilita legendas (`TranscriptsDisabled`) — mesma mitigação. (4) VPS indisponível — plano B é reiniciar via SSH; dados persistem em volume Docker nomeado, sobrevivem a restart/rebuild dos containers. |

---

## Assinaturas

| Integrante | E-mail | Papel |
|---|---|---|
| Arthur Natureza | arthurnatureza@gmail.com | Engenharia de dados, qualidade, deploy, produto |
