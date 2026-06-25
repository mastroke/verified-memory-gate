"""Tests for built-in verifiers."""

from __future__ import annotations

import pytest

from verified_memory_gate.builtin_verifiers import (
    JsonSchemaVerifier,
    NumericToleranceVerifier,
    PytestExitCodeVerifier,
    extract_anchored_number,
)
from verified_memory_gate.models import CandidateExperience, MemoryScope


def _candidate(**kwargs: object) -> CandidateExperience:
    defaults: dict[str, object] = {
        "lesson": "Baseline lesson.",
        "principal": "agent-a",
        "scope": MemoryScope.PRIVATE,
    }
    defaults.update(kwargs)
    return CandidateExperience(**defaults)  # type: ignore[arg-type]


def test_extract_anchored_number_after_keyword() -> None:
    value = extract_anchored_number("Sharpe ratio is 0.62 for the run.", "sharpe")
    assert value == pytest.approx(0.62)


def test_extract_anchored_number_before_keyword() -> None:
    value = extract_anchored_number("Observed 1.05 max drawdown.", "drawdown")
    assert value == pytest.approx(1.05)


def test_pytest_verifier_passes_on_evidence_tag() -> None:
    verifier = PytestExitCodeVerifier()
    result = verifier.verify(_candidate(evidence=("pytest:passed",)))

    assert result.passed


def test_pytest_verifier_passes_on_metadata_exit_code() -> None:
    verifier = PytestExitCodeVerifier()
    result = verifier.verify(_candidate(metadata={"pytest_exit_code": 0}))

    assert result.passed


def test_pytest_verifier_fails_on_nonzero_exit_code() -> None:
    verifier = PytestExitCodeVerifier()
    result = verifier.verify(_candidate(metadata={"pytest_exit_code": 1}))

    assert result.failed
    assert any("exit code 1" in r for r in result.reasons)


def test_pytest_verifier_skips_without_signal() -> None:
    verifier = PytestExitCodeVerifier()
    result = verifier.verify(_candidate())

    assert result.skipped


def test_numeric_tolerance_passes_within_window() -> None:
    verifier = NumericToleranceVerifier(
        anchor="sharpe",
        expected=0.62,
        tolerance=0.05,
    )
    result = verifier.verify(
        _candidate(lesson="Promote when Sharpe ratio reaches 0.60.")
    )

    assert result.passed


def test_numeric_tolerance_fails_outside_window() -> None:
    verifier = NumericToleranceVerifier(
        anchor="sharpe",
        expected=0.62,
        tolerance=0.01,
    )
    result = verifier.verify(
        _candidate(lesson="Sharpe ratio only 0.50 on validation.")
    )

    assert result.failed
    assert any("outside" in r for r in result.reasons)


def test_numeric_tolerance_reads_metadata_key() -> None:
    verifier = NumericToleranceVerifier(
        anchor="sharpe",
        expected=0.62,
        tolerance=0.0,
        sources=("metadata",),
        metadata_key="sharpe",
    )
    result = verifier.verify(_candidate(metadata={"sharpe": 0.62}))

    assert result.passed


def test_json_schema_verifier_passes_valid_metadata() -> None:
    verifier = JsonSchemaVerifier(
        schema={
            "type": "object",
            "required": ("strategy_id", "sharpe"),
            "properties": {
                "strategy_id": {"type": "string"},
                "sharpe": {"type": "number", "minimum": 0.5},
            },
        }
    )
    result = verifier.verify(
        _candidate(metadata={"strategy_id": "mom-v2", "sharpe": 0.62})
    )

    assert result.passed


def test_json_schema_verifier_fails_on_missing_required_field() -> None:
    verifier = JsonSchemaVerifier(
        schema={
            "type": "object",
            "required": ("strategy_id",),
            "properties": {"strategy_id": {"type": "string"}},
        }
    )
    result = verifier.verify(_candidate(metadata={"sharpe": 0.62}))

    assert result.failed
    assert any("missing required field" in r for r in result.reasons)


def test_numeric_tolerance_rejects_negative_tolerance() -> None:
    with pytest.raises(ValueError, match="tolerance"):
        NumericToleranceVerifier(anchor="sharpe", expected=1.0, tolerance=-0.1)
