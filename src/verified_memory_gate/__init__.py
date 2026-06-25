"""Verified Memory Gate — governance and verification before agent memory writes."""

from verified_memory_gate.coordinator import EDVCoordinator
from verified_memory_gate.edv import (
    DistillContext,
    Distiller,
    EDVPipeline,
    EDVPipelineResult,
    EDVStageResult,
    ExecuteBundle,
    ExecuteStage,
    ExecutorTrace,
    RuleBasedDistiller,
    STAGE_DISTILL,
    STAGE_EXECUTE,
    STAGE_VERIFY,
    StageOutput,
    VerifyStage,
    WindowBinding,
)
from verified_memory_gate.gate import GateMode, MemoryGate
from verified_memory_gate.governance import can_read, parse_leak_targets
from verified_memory_gate.models import (
    CandidateExperience,
    CommitResult,
    CommitStatus,
    MemoryEntry,
    MemoryScope,
    PendingCandidate,
    RetrievalFilter,
    Tombstone,
)
from verified_memory_gate.store import InMemoryStore
from verified_memory_gate.verifiers import (
    ConsensusResult,
    QuorumConfig,
    Verifier,
    VerifierOutcome,
    VerifierRegistry,
    VerifierResult,
)

__all__ = [
    "Tombstone",
    "can_read",
    "parse_leak_targets",
    "CandidateExperience",
    "CommitResult",
    "CommitStatus",
    "ConsensusResult",
    "DistillContext",
    "Distiller",
    "EDVCoordinator",
    "EDVPipeline",
    "EDVPipelineResult",
    "EDVStageResult",
    "ExecuteBundle",
    "ExecuteStage",
    "ExecutorTrace",
    "GateMode",
    "InMemoryStore",
    "MemoryEntry",
    "MemoryGate",
    "MemoryScope",
    "PendingCandidate",
    "QuorumConfig",
    "RetrievalFilter",
    "RuleBasedDistiller",
    "STAGE_DISTILL",
    "STAGE_EXECUTE",
    "STAGE_VERIFY",
    "StageOutput",
    "VerifyStage",
    "Verifier",
    "VerifierOutcome",
    "VerifierRegistry",
    "VerifierResult",
    "WindowBinding",
]

__version__ = "0.1.0"
