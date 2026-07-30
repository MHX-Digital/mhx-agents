# ADR-0002: Limite de segurança deny-by-default do MCP

- Status: proposta para revisão humana
- Data: 2026-07-29
- Issue: [LexNotify-Web #792](https://github.com/LexNotify/LexNotify-Web/issues/792)
- Dependências: PRs do kit #32 e #36

## Ameaças consideradas

- cliente sem identidade, credencial inválida/expirada/revogada;
- enumeração cross-project e cross-tenant;
- vazamento de SHA/status antes da autorização;
- traversal, caminho absoluto, NUL, Unicode ambíguo e symlink escape;
- prompt injection armazenada em código/ADR;
- tokens, connection strings, paths pessoais e segredos simulados em saída/log;
- abuso de paginação, payload e taxa;
- rotação de chave e replay por JTI revogado.

## Decisão

Toda tool executa a mesma ordem:

```text
autenticar
  -> autorizar tool + projeto + tenant
  -> validar entrada/path
  -> verificar freshness
  -> ler somente o índice/ADR permitido
  -> redigir e limitar a resposta
  -> auditar somente metadados
```

Chamadores não autorizados recebem erro estável sem repo, tenant, SHA, contagem ou freshness. O serviço continua read-only; não existem tools mutáveis ou shell.

Nesta fase local/sanitizada, o boundary valida tokens HMAC-SHA256 com `kid`, expiração, JTI e allowlist de tools. Chaves entram exclusivamente por ambiente e podem coexistir durante rotação; nenhum valor é versionado. O emissor corporativo e o transporte remoto continuam desabilitados até ADR/rollout próprios.

## Matriz

| Papel | Projeto | Tenant | Permitido | Proibido |
|---|---|---|---|---|
| reader | claim exato | claim exato | tools read-only na allowlist do token | mutação e escopo lateral |
| auditor | claim exato | claim exato aprovado | status, consulta e verificação na allowlist | mutação e enumeração lateral |
| admin | claim exato | claim exato aprovado | mesmas tools read-only desta fase | shell, filesystem arbitrário e mutação |

A posse de um `repoId` ou `tenantId` não concede acesso; ambos precisam coincidir com claims autenticadas. Avancard/Fênix usa tenant `avancard-fenix` e não recebe índice/log/cache de outro tenant.

## Filesystem e conteúdo não confiável

A única leitura derivada de input é ADR por slug ASCII estrito. O caminho é resolvido canonicamente e precisa continuar filho direto da raiz de ADRs; symlinks externos são rejeitados. Component IDs são comparados com paths já indexados, não usados para abrir arquivos.

Conteúdo de ADR é retornado em envelope com `contentTrust=untrusted_repository_data` e política explícita de não execução. O MCP não executa comandos, interpreta instruções do repositório ou amplia autorização com base no conteúdo.

## Redaction, limites e auditoria

Redaction recursiva cobre bearer tokens, nomes comuns de credenciais, connection strings e paths pessoais. Respostas excedentes falham com `RESPONSE_TOO_LARGE`. Rate limit é por JTI/janela. Auditoria contém correlation ID, sujeito, projeto, tenant, tool, decisão e código — nunca token, payload ou conteúdo jurídico.

## Compatibilidade

Os sete nomes de tools permanecem. Novos campos são opcionais no schema para compatibilidade de parsing, mas chamadas sem autenticação/tenant são negadas. `get_adr` passa de texto cru para envelope estruturado; consumidores precisam tratar o conteúdo como dado não confiável.

## Limitações e rollout

- HMAC local não é a identidade definitiva para transporte remoto.
- TLS, gateway, armazenamento/rotação corporativa e retenção precisam ser definidos antes de qualquer exposição remota.
- Timeout/cancelamento e carga integrados pertencem à #795.
- O rate limiter em memória é por processo; modo distribuído exigirá backend compartilhado.
- Nenhum rollout ou credencial real foi usado.

## Rollback

Reverter o PR restaura o servidor anterior. O transporte remoto continua desabilitado em ambos os estados. Não há migration, dado ou índice a reverter. Um rollout futuro só poderá desativar o boundary retornando ao perfil local anterior após aprovação explícita.
