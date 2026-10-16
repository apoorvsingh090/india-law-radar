"""Optional external-model summariser via a local command (Milestone 4).

Disabled by default. When ``ai.enabled`` is true and ``ai.command`` names
an executable, this summariser sends ``{system, draft, evidence}`` as JSON
on stdin and reads ``{"summary", "claims", "warnings"}`` from stdout.

Trust rules (spec section 9):
- Malformed JSON or wrong shapes are rejected, never repaired.
- Claims citing unknown citation ids are rejected (no invented sources).
- Claims without citations must set ``unsupported: true`` explicitly.
- ``document contents`` travel as *data* under ``evidence``; the system
  instruction forbids following instructions embedded in them.
- A rejection leaves the stored report untouched and is recorded as a
  failed attempt in the returned warnings (caller surfaces them).
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess

from lawradar.ai.base import AISummariserError, SYSTEM_INSTRUCTION
from lawradar.reporting.schema import CLAIM_TYPES

MAX_OUTPUT_BYTES = 1_000_000


def build_prompt(draft: dict, evidence: dict) -> dict:
    """Prompt payload: instruction + draft + evidence-as-data."""
    return {
        "system": SYSTEM_INSTRUCTION,
        "draft_summary": draft.get("summary", ""),
        "draft_claims": draft.get("claims", []),
        "evidence": evidence,
        "required_output": {
            "summary": "plain-language rewording grounded in the evidence",
            "claims": ("subset/rewording of the draft claims, each with "
                       "citation_ids drawn ONLY from evidence.citation_ids"),
            "warnings": ["uncertainty flags where evidence is insufficient"],
        },
    }


def validate_output(output: dict, allowed_citation_ids: set[str]) -> dict:
    """Validate model output. Raises AISummariserError on any violation."""
    if not isinstance(output, dict):
        raise AISummariserError("model output must be a JSON object")
    if "summary" not in output or not isinstance(output["summary"], str):
        raise AISummariserError("model output missing string 'summary'")
    if not output["summary"].strip():
        raise AISummariserError("model returned an empty summary")
    claims = output.get("claims", [])
    if not isinstance(claims, list):
        raise AISummariserError("model 'claims' must be a list")
    for claim in claims:
        if not isinstance(claim, dict):
            raise AISummariserError("each model claim must be an object")
        for key in ("claim", "claim_type", "citation_ids"):
            if key not in claim:
                raise AISummariserError(f"model claim missing {key!r}")
        if claim["claim_type"] not in CLAIM_TYPES:
            raise AISummariserError(
                f"unknown claim_type {claim['claim_type']!r}")
        unknown = [c for c in claim["citation_ids"]
                   if c not in allowed_citation_ids]
        if unknown:
            raise AISummariserError(
                f"model cited unknown sources: {unknown} "
                "(invented citations are rejected)")
        if not claim["citation_ids"] and not claim.get("unsupported", False):
            raise AISummariserError(
                "model claim has no citations and is not marked unsupported")
    warnings = output.get("warnings", [])
    if not isinstance(warnings, list):
        raise AISummariserError("model 'warnings' must be a list")
    return {"summary": output["summary"],
            "claims": claims,
            "warnings": [str(w) for w in warnings]}


class CommandSummariser:
    """Summariser backed by a local executable (e.g. a local-LLM wrapper)."""

    name = "external-command"

    def __init__(self, command: str, timeout_seconds: int = 120) -> None:
        if not command or not command.strip():
            raise AISummariserError("no AI command configured (ai.command)")
        try:
            argv = shlex.split(command.strip(), posix=False)
        except ValueError as exc:
            raise AISummariserError(f"cannot parse ai.command: {exc}") from exc
        if not argv or shutil.which(argv[0].strip('"')) is None:
            raise AISummariserError(
                f"AI command not found on PATH: {argv[0] if argv else command!r}")
        self.argv = [part.strip('"') for part in argv]
        self.timeout_seconds = timeout_seconds

    def summarise(self, draft: dict, evidence: dict) -> dict:
        allowed = set(evidence.get("citation_ids", []))
        payload = json.dumps(build_prompt(draft, evidence))
        try:
            proc = subprocess.run(
                self.argv,
                input=payload.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AISummariserError(f"AI command failed to run: {exc}") from exc
        if proc.returncode != 0:
            raise AISummariserError(
                f"AI command exited {proc.returncode}: "
                f"{proc.stderr.decode('utf-8', 'replace')[:500]}")
        if len(proc.stdout) > MAX_OUTPUT_BYTES:
            raise AISummariserError("AI output exceeded size limit")
        try:
            output = json.loads(proc.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AISummariserError(
                f"AI output is not valid JSON and was rejected: {exc}") from exc
        result = validate_output(output, allowed)
        result["warnings"].append(
            "summary reworded by an external model; facts and citations "
            "are restricted to the supplied evidence")
        return result
