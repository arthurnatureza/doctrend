# Relatório dos 7 Dias de Observação

> Baseado no template da §6 do `CONTRATO_TRABALHO_FINAL.md`. Preenchido durante o
> período de observação em produção — registrado com honestidade técnica: erros
> explicados valem mais que "zero erros" forjado.

## Marco inicial

| Campo | Valor |
|---|---|
| **D0 — início da observação** (data/hora) | 2026-07-11, ~05:48 UTC (primeiro ciclo real, após limpar o datalake de dados de teste/demo) |
| URL do dashboard | http://187.77.248.197 |
| Commit/tag do deploy | `fb298e3` — fix: CD sempre rebuilda api+frontend |

### Resultado do ciclo D0

10 canais reais consultados, 43 vídeos descobertos (janela de 15 dias, cobrindo
desde ~26/06 — inclui o `HISTORICAL_START_DATE=2026-07-01`). 0 transcrições
capturadas nesse ciclo (VPS bloqueada pela `youtube_transcript_api`,
`error=IpBlocked` — ver [`ARQUITETURA.md`](ARQUITETURA.md)); o Gold foi populado
via a camada de metadados (título+descrição+tags), com os termos mais mencionados
sendo: ansiedade (11), depressão (9), coluna (5), infarto (4), intestino (3),
anemia (3), alzheimer (2), colesterol (2), diabetes (2).

## Checagens diárias (D1–D6)

| Dia | Serviço ativo? | Última execução | Dashboard no ar? | Observações |
|---|---|---|---|---|
| D1 | ☐ | | ☐ | |
| D2 | ☐ | | ☐ | |
| D3 | ☐ | | ☐ | |
| D4 | ☐ | | ☐ | |
| D5 | ☐ | | ☐ | |
| D6 | ☐ | | ☐ | |

## Métricas finais (D7)

| Métrica | Valor |
|---|---|
| Total de ciclos de ingestão executados | |
| Vídeos descobertos | |
| Vídeos processados (INGESTED) | |
| Vídeos em quarentena / falha | |
| Erros por tipo (sem legenda, API, validação Pandera…) | |

## Evolução do KPI principal

_Preencher ao final dos 7 dias, comparando o termo/tema mais mencionado no D0 com o D7._

| Dia | KPI | Comentário |
|---|---|---|
| D0 | ansiedade (11 menções, 11 vídeos) | primeiro ciclo real, só metadados (transcrição bloqueada) |
| D7 | | |

## Incidentes

| Data | Incidente | Causa | Como foi resolvido |
|---|---|---|---|
| 2026-07-11 | CD não reconstruía a imagem depois do 1º deploy | detecção de mudanças via `git log` num diretório sem `.git` (rsync exclui) | workflow simplificado para sempre rebuildar (`docker compose up -d --build --remove-orphans`) — ver PR #5 |
| 2026-07-11 | Transcrições falhando silenciosamente como "sem legenda" | `youtube_transcript_api` bloqueada por IP de datacenter (`IpBlocked`), mas o erro genérico escondia a causa real | diagnóstico corrigido para registrar o motivo real; camada de metadados adicionada como rede de segurança para o Gold — ver PR #4 |

## Capturas de tela do dashboard

- [ ] Início do período (D0/D1)
- [ ] Meio (D3/D4)
- [ ] Fim (D7)

## Aprendizados e próximos passos

_Preencher ao final dos 7 dias._
