# MCP — baseline, SLOs e runbook operacional

Data: 2026-07-29
Issue: [LexNotify-Web #795](https://github.com/LexNotify/LexNotify-Web/issues/795)
Ambiente: local sanitizado, Python 3.12.3, um host, cache de filesystem aquecido, sem transporte de rede.

## Método reproduzível

```bash
PYTHONPATH=src python scripts/benchmark_mcp.py --iterations 5000 --concurrency 32 --components 848
PYTHONPATH=src python scripts/benchmark_mcp.py --iterations 1000 --concurrency 1 --components 848
PYTHONPATH=src python -m pytest -q
```

O corpus tem 848 componentes sintéticos, igual ao volume observado no índice LexNotify. Não contém código, PII, documentos jurídicos ou secrets. O benchmark mede o caminho real `authn/authz → freshness/Git → busca → redaction/limit` e publicação/rollback local.

## Resultados medidos

### Antes do cache de provas Git imutáveis

5.000 consultas, concorrência 32:

| Métrica | Resultado |
|---|---:|
| p50 | 230,9845 ms |
| p95 | 326,7186 ms |
| p99 | 364,9813 ms |
| máximo | 432,6683 ms |
| throughput | 136,45 req/s |
| erro | 0/5.000 |
| CPU | 39,7895 s |
| RSS máximo | 88.820 KiB |

### Depois

O cache é limitado a 512 provas `commit existe/é ancestral`, chaveadas por repo, commit e `observedCommit`. HEAD, marker e freshness nunca são cacheados.

| Perfil | p50 | p95 | p99 | Throughput | Erro | RSS máximo |
|---|---:|---:|---:|---:|---:|---:|
| 5.000 / concorrência 32 | 112,8391 ms | 184,0001 ms | 214,8937 ms | 274,60 req/s | 0% | 77.804 KiB |
| 1.000 / concorrência 1 | 5,7312 ms | 8,7320 ms | 34,1938 ms | 154,13 req/s | 0% | 58.732 KiB |

Comparação concorrente: p95 -43,7%, throughput +101,2%, RSS máximo -12,4%. Como são execuções únicas locais, não constituem ainda série estatística de produção.

### Publicação e rollback

| Execução | Publicação | Rollback | Estado |
|---|---:|---:|---|
| concorrência 32 | 55,6954 ms | 5,1027 ms | published / rolled_back |
| serial | 97,0507 ms | 7,3853 ms | published / rolled_back |

Índice: 64.404 bytes. Estado/snapshots/auditoria: 131.766 bytes. O tempo total do scanner completo do LexNotify não foi medido nesta fase; os números acima cobrem validação, worktree, snapshot, promoção e rollback do fixture.

## SLOs propostos (não implantados)

| Indicador | Objetivo futuro | Evidência atual | Situação |
|---|---|---|---|
| disponibilidade read-only | 99,9% mensal | não há serviço remoto | não verificável |
| query serial p95 / p99 | ≤25 / ≤75 ms | 8,73 / 34,19 ms | atende local |
| query a 32 threads p95 / p99 | ≤250 / ≤300 ms | 184,00 / 214,89 ms | atende local |
| erro interno em índice healthy | <0,1% | 0/6.000 benchmarks | atende fixture |
| freshness lag | 0 commits; stale bloqueado na mesma consulta | HEAD/marker não cacheados | coberto em teste |
| publicação de índice ~64 KiB | ≤500 ms | 55,70–97,05 ms | amostra insuficiente |
| rollback técnico | ≤1 s | 5,10–7,39 ms | amostra insuficiente |
| RTO operacional | ≤5 min | automação local existe; operação humana não cronometrada | não validado |
| RPO | último índice válido, zero perda do ativo anterior | snapshot+CAS testados | atende fixture |
| RSS local | ≤128 MiB | 58–89 MiB | atende local |
| disco transitório | ≤3× índice + auditoria | 2,05× no fixture | atende local |

Alertas futuros: `INDEX_BACKEND_UNAVAILABLE`, freshness diferente de `fresh`, marker ativo acima da janela, falha/rollback, auth denies anormais, rate limit, p95/p99 acima do SLO, crescimento de snapshot e disco livre abaixo de 3× o próximo candidato.

## Triagem

1. Correlacionar pelo request/run ID; nunca coletar token ou payload.
2. Verificar autenticação/autorização antes de inspecionar freshness.
3. Consultar marker, state, manifesto, checksum e audit metadata-only.
4. Se `indexing`, confirmar lock/PID e duração. Lock ilegível bloqueia; lock órfão verificável é preservado e recuperado.
5. Se `failed`, manter candidato e snapshot para investigação; não limpar.
6. Validar o último snapshot antes de qualquer rollback.
7. Executar rollback sanitizado, confirmar checksum, status/freshness e smoke tests.
8. Escalar se houver divergência de repo/tenant, segredo em log, checksum inválido ou falha repetida.

## Plano futuro de rollout (não executado)

### Pré-requisitos obrigatórios

- PR #32 revisado/aprovado e #791 integrada;
- PR #36 revisado/aprovado e #793 integrada;
- PR #37 revisado/aprovado e #792 integrada;
- #795 integrada com CI obrigatória concluída;
- testes de isolamento e rollback aprovados;
- identidade corporativa, TLS, rotação e retenção aprovados em ADR;
- ambiente sanitizado separado;
- varredura de logs sem secrets;
- revisão humana e autorização explícita.

### Sequência

1. Nomear owner, operador, security reviewer e incident commander.
2. Fazer backup do índice ativo e snapshot com checksum; registrar source SHA.
3. Implantar somente em ambiente sanitizado, com transporte remoto ainda bloqueado externamente.
4. Executar contratos, segurança, falhas, carga e rollback.
5. Canário com um projeto e tenant sintéticos, read-only.
6. Observar por janela aprovada: auth denies, freshness, erros, p95/p99, CPU, memória e disco.
7. Avançar apenas com 0 vazamento, 0 resposta stale conclusiva, rollback verde e SLOs atendidos.
8. Parar diante de checksum/schema/repo divergente, erro >0,1%, p95 acima do gate, segredo em log, isolamento falho ou freshness desconhecida.
9. Rollback: bloquear tráfego, validar snapshot, troca atômica, smoke/freshness, preservar artefato falho e comunicar.
10. Registrar evidências, decisão e validação posterior no Epic/issues/PRs.

## Limitações

- Nenhum teste de rede, TLS, multi-host, identidade real ou produção.
- Sem teste de saturação real de disco/memória; falha `ENOSPC` foi injetada.
- Sem série temporal longa para disponibilidade, taxa de rollback ou alertas.
- Sem medição do scanner completo do LexNotify.
- #794 permanece explicitamente fora desta fase.
