# ADR-0001: Publicação atômica e recuperável do índice

- Status: proposta para revisão humana
- Data: 2026-07-29
- Issue: [LexNotify-Web #793](https://github.com/LexNotify/LexNotify-Web/issues/793)
- Dependência: [agent-architecture-kit #32](https://github.com/MHX-Digital/agent-architecture-kit/pull/32)

## Contexto

O scanner canônico escrevia diretamente o JSON consumido pelo MCP. Uma interrupção, concorrência ou candidato inválido poderia deixar metadados e artefato divergentes. O índice ativo precisa continuar legível durante todo o rebuild, e falhas não podem substituir a última versão válida.

## Decisão

O scanner existente continua responsável pelo conteúdo. `IndexLifecycle` adiciona o lifecycle operacional:

```text
requested -> indexing -> validating -> ready -> publishing -> published
                 |            |          |          |
                 +------------+----------+----------+-> failed
                 +------------+----------+------------> cancelled
snapshot válido --------------------------------------> rolled_back
```

1. O commit é um SHA completo, existente e ancestral da branch solicitada.
2. A fonte é materializada em worktree detached temporário no commit resolvido.
3. O scanner grava somente em `runs/<runId>/candidate/index.json`.
4. Schema, repositório, commit, componentes e checksums são validados antes da promoção.
5. Um lock `O_EXCL` serializa publicadores. Lock órfão só é recuperado quando seu PID é verificavelmente inexistente; o lock antigo é preservado para investigação.
6. O hash do índice ativo é capturado e revalidado antes da troca (compare-and-swap contra alteração externa).
7. A versão ativa anterior é copiada para snapshot com checksum.
8. A promoção copia o candidato para arquivo temporário adjacente e usa `os.replace`, atômico no mesmo filesystem.
9. Rollback valida o snapshot e também usa `os.replace`.
10. Estados e eventos são gravados atomicamente; auditoria contém somente metadados, não conteúdo indexado.

## Manifesto

O manifesto registra `repositoryId`, branch, commits solicitado/resolvido/indexado, versões de schema/indexador, timestamps, contagens, escopos, checksums, estado, run ID, snapshot anterior, operador e origem. O próprio manifesto recebe SHA-256 canônico.

## Segurança

- O caminho ativo e a raiz de estado devem estar dentro da raiz do repositório.
- O builder recebe um worktree isolado e nunca o caminho ativo.
- IDs de snapshot aceitam somente o formato emitido pelo lifecycle.
- Erros externos não incluem conteúdo do índice ou saída do Git.
- Artefatos candidatos e snapshots falhos são preservados para investigação.
- Somente o worktree temporário criado pela execução é removido.

## Limitações

- A atomicidade de `os.replace` pressupõe temporário e destino no mesmo filesystem.
- Coordenação distribuída entre hosts exige um lock/lease externo; esta implementação governa o modo local de um host.
- Retenção automática de snapshots não é aplicada nesta fase para evitar remoção sem política aprovada.
- Métricas agregadas, testes de carga e SLOs pertencem à #795.
- Autenticação, autorização e isolamento por tenant pertencem à #792.

## Rollback da mudança

Reverter o PR remove o lifecycle sem tocar em índices ou snapshots já existentes. Para rollback operacional, selecionar um snapshot íntegro pelo ID, executar `rollback`, validar checksum/freshness e preservar o índice substituído para investigação. Nenhum rollout é realizado por este ADR.
