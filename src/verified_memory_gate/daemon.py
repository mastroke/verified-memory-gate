"""Optional FastAPI daemon exposing the append-only audit trail."""

from __future__ import annotations

from typing import Any, Literal

from verified_memory_gate.audit_log import AppendOnlyAuditLog, AuditEventKind
from verified_memory_gate.gate import MemoryGate
from verified_memory_gate.models import MemoryEntry


def create_app(
    gate: MemoryGate | None = None,
    audit_log: AppendOnlyAuditLog | None = None,
) -> Any:
    """Build a FastAPI app that serves audit export and gate health."""
    try:
        from fastapi import FastAPI, HTTPException, Query
        from fastapi.responses import JSONResponse, PlainTextResponse
    except ImportError as exc:
        raise ImportError(
            "FastAPI is required for the audit daemon. "
            "Install with: pip install 'verified-memory-gate[daemon]'"
        ) from exc

    memory_gate = gate or MemoryGate()
    log = audit_log or memory_gate.audit_log or AppendOnlyAuditLog()
    if memory_gate.audit_log is None:
        memory_gate.audit_log = log

    app = FastAPI(
        title="Verified Memory Gate Audit Daemon",
        version="0.1.0",
        description="Local append-only audit trail export for compliance review.",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/audit")
    def list_audit(
        kind: AuditEventKind | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        records = log.list(kind=kind, actor=actor)
        return {
            "count": len(records),
            "records": [record.to_dict() for record in records],
        }

    @app.get("/audit/export")
    def export_audit(
        format: Literal["json", "ndjson"] = Query(default="json"),
    ) -> Any:
        if format == "ndjson":
            return PlainTextResponse(
                content=log.export_ndjson(),
                media_type="application/x-ndjson",
            )
        return JSONResponse(content=log.export_records())

    @app.get("/memories")
    def list_memories() -> dict[str, Any]:
        entries: list[MemoryEntry] = memory_gate.retrieve()
        return {
            "count": len(entries),
            "memories": [
                {
                    "memory_id": entry.memory_id,
                    "principal": entry.principal,
                    "scope": entry.scope,
                    "classification": entry.classification,
                    "created_at": entry.created_at.isoformat(),
                }
                for entry in entries
            ],
        }

    @app.get("/audit/{event_id}")
    def get_audit_event(event_id: str) -> dict[str, Any]:
        for record in log.list():
            if record.event_id == event_id:
                return record.to_dict()
        raise HTTPException(status_code=404, detail=f"unknown event_id: {event_id}")

    return app


def main() -> None:
    """Run the audit daemon with uvicorn when installed."""
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "uvicorn is required to run the audit daemon. "
            "Install with: pip install 'verified-memory-gate[daemon]'"
        ) from exc

    uvicorn.run(create_app(), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
