---
description: Ultrathink forçado + N subagentes Explore read-only em paralelo sobre a mesma pergunta, com síntese final
argument-hint: [N] <pergunta ou tarefa>
---

Modo ultracode para: "$ARGUMENTS"

Interpretação de `$ARGUMENTS`: se o primeiro token for um número, use-o como N (número de subagentes, 2-4); senão N=3 por padrão. O resto do texto é a pergunta/tarefa real.

1. **Ultrathink**: pense com o máximo de profundidade possível antes de agir — não pule pra uma resposta rápida ou óbvia.
2. **Dispare N subagentes `Explore` (read-only) EM PARALELO** (uma única mensagem, múltiplas chamadas de tool), investigando a MESMA pergunta mas cada um com um ângulo/foco explícito e diferente dos outros (ex.: um foca em código/implementação existente, outro em testes/cobertura, outro em decisões de arquitetura já documentadas/ADRs/incidentes conhecidos) — não mande todos fazerem a mesma busca genérica.
3. Espere os N subagentes retornarem de verdade. Não adivinhe, preveja ou preencha o resultado de nenhum antes dele voltar.
4. **Síntese final**: cruze os achados dos N subagentes — onde concordam, onde divergem — e chegue a uma resposta/recomendação final considerando tudo. Cite qual subagente trouxe qual achado quando isso importar pra credibilidade da conclusão.
5. Se a pergunta pedir implementação (não só pesquisa) e a mudança for não-trivial, a síntese vira um plano a confirmar, não uma implementação direta sem checar escopo antes.
