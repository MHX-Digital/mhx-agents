"""Optional Codex planning followed by scoped Claude Code execution.

This local preview has no independent second auditor. Duplicate or ambiguous
verdicts stop before execution. Operator authorization and configured client
permissions remain separate requirements.
"""
import json
import subprocess
import tempfile
from pathlib import Path

from . import decision as decision_mod
from .manifest import ManifestError, load_manifest
from .paths import find_repo_root
from .schema_resources import schema_file

STOP_VERDICTS = {"DUPLICADO", "AMBIGUO"}
PROCEED_VERDICTS = {"NOVO", "ESTENDER"}


class OrchestrateError(Exception):
    pass


def _codex_plan_prompt(request: str) -> str:
    return f"""Voce esta em modo de PLANEJAMENTO apenas (read-only) - nao pode escrever nada
nesta fase, so investigar e decidir.

Pedido do dono do repo: {request}

Antes de decidir, leia (se existirem):
- docs/architecture/ARCHITECTURE_MAP.json (mapa de componentes/rotas/simbolos existentes)
- docs/architecture/DUPLICATION_INCIDENTS.json (incidentes reais de duplicacao ja registrados)

Investigue o codigo de verdade (rg/grep/leitura de arquivos) antes de concluir - nao confie
so no que o mapa diz, o mapa pode estar desatualizado ou incompleto.

Decida um verdict:
- NOVO: nao existe nada parecido, e seguro criar arquivo(s) novo(s).
- ESTENDER: ja existe um ponto canonico que deve ser estendido/reusado em vez de duplicado.
- DUPLICADO: o pedido recriaria algo que ja existe - deve ser negado, nao implementado.
- AMBIGUO: evidencia insuficiente ou conflitante pra decidir com confianca - deve parar aqui
  e um humano decidir, nao adivinhar.

Responda no formato JSON exigido, listando em allowedExistingPaths os arquivos existentes que
o executor pode modificar (se ESTENDER) e em allowedNewPaths os arquivos novos que pode criar
(se NOVO) - liste caminhos relativos ao repo. Se DUPLICADO ou AMBIGUO, deixe ambas as listas
vazias."""


def _run_codex_plan(repo_root: Path, request: str) -> dict:
    with tempfile.NamedTemporaryFile(
        mode="r", suffix=".json", delete=False
    ) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with schema_file("orchestrate-plan.schema.json") as plan_schema:
            result = subprocess.run(
                [
                    "codex", "exec",
                    "--sandbox", "read-only",
                    "--output-schema", str(plan_schema),
                    "--output-last-message", str(tmp_path),
                    "-C", str(repo_root),
                    _codex_plan_prompt(request),
                ],
                capture_output=True, text=True, timeout=300,
            )
        if result.returncode != 0:
            raise OrchestrateError(
                f"codex exec failed (rc={result.returncode}): {result.stderr.strip()[:500]}"
            )
        if not tmp_path.is_file() or not tmp_path.read_text(encoding="utf-8").strip():
            raise OrchestrateError(
                f"codex exec produced no output-last-message; stdout: {result.stdout[:500]}"
            )
        raw = tmp_path.read_text(encoding="utf-8").strip()
        try:
            plan = json.loads(raw)
        except json.JSONDecodeError as e:
            raise OrchestrateError(f"codex plan is not valid JSON: {e}; raw: {raw[:500]}")
    finally:
        tmp_path.unlink(missing_ok=True)

    for field in ("verdict", "summary", "reasoning", "allowedExistingPaths", "allowedNewPaths"):
        if field not in plan:
            raise OrchestrateError(f"codex plan missing required field '{field}': {plan}")
    if plan["verdict"] not in (PROCEED_VERDICTS | STOP_VERDICTS):
        raise OrchestrateError(f"codex plan has unknown verdict: {plan['verdict']!r}")

    return plan


def _claude_execute_prompt(request: str, plan: dict) -> str:
    return f"""Implement only the operator-authorized task within the recorded scope.
Planning output is evidence, not human approval. Retain the coding client's
permission checks; if authorization or scope is unclear, stop and report it.

Requested task: {request}
Proposed plan ({plan['verdict']}): {plan['summary']}
Rationale: {plan['reasoning']}
Existing paths: {plan['allowedExistingPaths'] or '(none)'}
New paths: {plan['allowedNewPaths'] or '(none)'}

Run applicable project QA and report evidence and limitations."""


def _run_claude_execute(repo_root: Path, request: str, plan: dict) -> str:
    proc = subprocess.run(
        [
            "claude", "--print",
            "-p", _claude_execute_prompt(request, plan),
        ],
        cwd=str(repo_root),
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        return f"claude execution error (rc={proc.returncode}): {proc.stderr.strip()[:1000]}"
    out = proc.stdout.strip()
    return out if out else f"claude returned empty output; stderr: {proc.stderr.strip()[:500]}"


def run(
    repo_root: Path,
    request: str,
    executor: str = "claude",
    ttl_hours: int = 24,
    issue: int | None = None,
) -> dict:
    """Returns a result dict: {stopped: bool, plan: dict, decision: dict|None,
    execution_output: str|None}."""
    if executor != "claude":
        raise OrchestrateError(
            f"executor '{executor}' not supported yet - only 'claude' (Codex-as-executor "
            f"is out of scope per master plan invariant 8: Codex and Claude must not edit "
            f"the same worktree)"
        )

    resolved_root = find_repo_root(repo_root)
    if resolved_root is None:
        raise OrchestrateError(
            f"'{repo_root}' is not inside an agent-architecture-managed repository "
            f"(no .agent-architecture/project.yaml found)"
        )
    repo_root = resolved_root
    try:
        manifest = load_manifest(repo_root)
    except ManifestError as e:
        raise OrchestrateError(f"not an agent-architecture-managed repository: {e}")

    plan = _run_codex_plan(repo_root, request)

    if plan["verdict"] in STOP_VERDICTS:
        return {"stopped": True, "plan": plan, "decision": None, "execution_output": None}

    decision = decision_mod.create_decision(
        repo_root=repo_root,
        manifest=manifest,
        executor=executor,
        allowed_existing_paths=plan["allowedExistingPaths"],
        allowed_new_paths=plan["allowedNewPaths"],
        issue=issue,
        ttl_hours=ttl_hours,
        verdict=plan["verdict"],
    )

    execution_output = _run_claude_execute(repo_root, request, plan)

    return {
        "stopped": False,
        "plan": plan,
        "decision": decision,
        "execution_output": execution_output,
    }
