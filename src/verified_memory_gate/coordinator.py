"""Multi-window coordinator for EDV stage output and synchronized commit."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from verified_memory_gate.edv import (
    STAGE_DISTILL,
    STAGE_EXECUTE,
    STAGE_VERIFY,
    DistillContext,
    EDVPipeline,
    EDVPipelineResult,
    ExecutorTrace,
    StageOutput,
    WindowBinding,
)
from verified_memory_gate.models import CommitResult, CommitStatus, MemoryEntry
from verified_memory_gate.store import InMemoryStore


RenderCallback = Callable[[str, StageOutput], None]


@dataclass
class EDVCoordinator:
    """Run EDV pipeline and fan stage output to bound display windows."""

    pipeline: EDVPipeline
    bindings: tuple[WindowBinding, ...] = ()
    store: InMemoryStore | None = None
    on_render: RenderCallback | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _latest: EDVPipelineResult | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = InMemoryStore()

    def commit(
        self,
        traces: tuple[ExecutorTrace, ...],
        context: DistillContext,
    ) -> CommitResult:
        """Run EDV stages and persist only after verify quorum passes."""
        result = self.pipeline.run(traces, context)
        with self._lock:
            self._latest = result

        self._render_all(result)

        if not result.ok:
            return CommitResult(
                status=CommitStatus.REJECTED,
                reasons=result.reasons,
            )

        if result.candidate is None:
            return CommitResult(
                status=CommitStatus.REJECTED,
                reasons=("pipeline succeeded without candidate",),
            )

        entry = MemoryEntry.from_candidate(result.candidate)
        self.store.insert(entry)
        return CommitResult(status=CommitStatus.COMMITTED, memory_id=entry.memory_id)

    def stage_output(self, stage: str) -> StageOutput:
        """Return the latest rendered output for one EDV stage."""
        with self._lock:
            result = self._latest
        if result is None:
            return StageOutput(stage=stage, content=f"{stage}: idle")
        return result.output_for(stage)

    def _render_all(self, result: EDVPipelineResult) -> None:
        if not self.bindings:
            return
        for binding in self.bindings:
            output = result.output_for(binding.stage)
            if self.on_render is not None:
                self.on_render(binding.window_id, output)

    @staticmethod
    def default_bindings() -> tuple[WindowBinding, ...]:
        return (
            WindowBinding(window_id="display-execute", stage=STAGE_EXECUTE),
            WindowBinding(window_id="display-distill", stage=STAGE_DISTILL),
            WindowBinding(window_id="display-verify", stage=STAGE_VERIFY),
        )
