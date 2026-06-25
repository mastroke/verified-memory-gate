"""Built-in verifiers: pytest exit code, numeric tolerance, JSON schema."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from verified_memory_gate.models import CandidateExperience
from verified_memory_gate.verifiers import VerifierResult


def extract_anchored_number(text: str, anchor: str) -> float | None:
    """Extract a numeric value near a keyword anchor in free text.

  Grading-the-Grader-style parsing: locate the anchor token, then read the
  nearest number within a short window before or after it. This tolerates
  natural-language agent output better than exact-string equality.
    """
    if not anchor or not text:
        return None

    escaped = re.escape(anchor)
    after = re.compile(
        rf"{escaped}[^\d]{{0,40}}(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)",
        re.IGNORECASE,
    )
    match = after.search(text)
    if match:
        return float(match.group(1))

    before = re.compile(
        rf"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)[^\d]{{0,20}}{escaped}",
        re.IGNORECASE,
    )
    match = before.search(text)
    if match:
        return float(match.group(1))

    return None


def _validate_json_value(value: Any, schema: Mapping[str, Any]) -> list[str]:
    """Validate a value against a minimal JSON-schema subset (no extra deps)."""
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return [f"expected object, got {type(value).__name__}"]
        required = schema.get("required", ())
        for key in required:
            if key not in value:
                errors.append(f"missing required field: {key}")
        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, subschema in properties.items():
                if key in value and isinstance(subschema, Mapping):
                    errors.extend(_validate_json_value(value[key], subschema))
    elif expected_type == "string":
        if not isinstance(value, str):
            errors.append(f"expected string, got {type(value).__name__}")
    elif expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"expected number, got {type(value).__name__}")
        else:
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(f"value {value} below minimum {schema['minimum']}")
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(f"value {value} above maximum {schema['maximum']}")
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"expected integer, got {type(value).__name__}")
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            errors.append(f"expected boolean, got {type(value).__name__}")
    elif expected_type == "array":
        if not isinstance(value, list):
            errors.append(f"expected array, got {type(value).__name__}")
        else:
            item_schema = schema.get("items")
            if isinstance(item_schema, Mapping):
                for index, item in enumerate(value):
                    for err in _validate_json_value(item, item_schema):
                        errors.append(f"[{index}] {err}")

    return errors


@dataclass(frozen=True, slots=True)
class PytestExitCodeVerifier:
    """Require pytest success via metadata exit code or evidence tag."""

    name: str = "pytest_exit_code"

    def verify(self, candidate: CandidateExperience) -> VerifierResult:
        if "pytest_exit_code" in candidate.metadata:
            code = candidate.metadata["pytest_exit_code"]
            if code == 0:
                return VerifierResult.pass_(self.name)
            return VerifierResult.fail(
                self.name, f"pytest exit code {code}, expected 0"
            )

        for item in candidate.evidence:
            if item == "pytest:passed":
                return VerifierResult.pass_(self.name)
            if item.startswith("pytest:") and item != "pytest:passed":
                return VerifierResult.fail(self.name, f"evidence {item}")

        return VerifierResult.skip(self.name, "no pytest signal in candidate")


@dataclass(frozen=True, slots=True)
class NumericToleranceVerifier:
    """Compare an anchor-extracted number against an expected value ± tolerance."""

    anchor: str
    expected: float
    tolerance: float = 0.0
    sources: tuple[str, ...] = ("lesson", "evidence", "metadata")
    metadata_key: str | None = None
    name: str = field(default="", init=False)

    def __post_init__(self) -> None:
        if self.tolerance < 0:
            raise ValueError("tolerance must be non-negative")
        object.__setattr__(
            self,
            "name",
            f"numeric_tolerance:{self.anchor}",
        )

    def verify(self, candidate: CandidateExperience) -> VerifierResult:
        observed = self._extract(candidate)
        if observed is None:
            return VerifierResult.skip(
                self.name,
                f"no numeric value found near anchor '{self.anchor}'",
            )

        delta = abs(observed - self.expected)
        if delta <= self.tolerance:
            return VerifierResult.pass_(self.name)

        return VerifierResult.fail(
            self.name,
            (
                f"anchor '{self.anchor}' value {observed} outside "
                f"{self.expected} ± {self.tolerance}"
            ),
        )

    def _extract(self, candidate: CandidateExperience) -> float | None:
        if "metadata" in self.sources and self.metadata_key:
            raw = candidate.metadata.get(self.metadata_key)
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return float(raw)

        texts: list[str] = []
        if "lesson" in self.sources:
            texts.append(candidate.lesson)
        if "evidence" in self.sources:
            texts.extend(candidate.evidence)

        for text in texts:
            value = extract_anchored_number(text, self.anchor)
            if value is not None:
                return value

        return None


@dataclass(frozen=True, slots=True)
class JsonSchemaVerifier:
    """Validate a candidate field against a JSON-schema-shaped dict."""

    schema: Mapping[str, Any]
    field: str = "metadata"
    name: str = "json_schema"

    def verify(self, candidate: CandidateExperience) -> VerifierResult:
        value = getattr(candidate, self.field, None)
        if value is None:
            return VerifierResult.skip(self.name, f"candidate has no {self.field}")

        errors = _validate_json_value(value, self.schema)
        if not errors:
            return VerifierResult.pass_(self.name)

        return VerifierResult.fail(self.name, *errors)
