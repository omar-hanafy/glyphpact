from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

_DIAGNOSTIC_CODE = re.compile(r"[A-Z][A-Z0-9_]*")


def _validated_text(value: object, label: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str or (not allow_empty and not value):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise ValueError(f"{label} must be {qualifier}.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{label} must contain only Unicode scalar values.") from error
    return value


def _copy_json_value(value: Any, label: str, *, depth: int = 0) -> Any:
    if depth > 64:
        raise ValueError(f"{label} exceeds the 64-level diagnostic nesting limit.")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{label} cannot contain non-finite numbers.")
        return value
    if type(value) is str:
        return _validated_text(value, label, allow_empty=True)
    if type(value) is list:
        return [
            _copy_json_value(item, f"{label}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    if type(value) is dict:
        items: list[tuple[str, Any]] = []
        for key, item in value.items():
            key = _validated_text(key, f"{label} key", allow_empty=True)
            items.append((key, item))
        result: dict[str, Any] = {}
        for key, item in sorted(items, key=lambda entry: entry[0].encode("utf-8")):
            result[key] = _copy_json_value(item, f"{label}.{key}", depth=depth + 1)
        return result
    raise ValueError(f"{label} must contain only JSON values, not {type(value).__name__}.")


def _copy_json_object(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object.")
    return cast(dict[str, Any], _copy_json_value(value, label))


class SvgFeatureClass(str, Enum):
    """How an SVG feature relates to an opaque monochrome glyph."""

    LOSSY = "lossy"
    UNREPRESENTABLE = "unrepresentable"


class IssueAction(str, Enum):
    CONVERTED = "converted"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    source: str | None = None
    hint: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        code = _validated_text(self.code, "Diagnostic code")
        if _DIAGNOSTIC_CODE.fullmatch(code) is None:
            raise ValueError("Diagnostic code must use uppercase letters, digits, and underscores.")
        _validated_text(self.message, "Diagnostic message")
        if self.source is not None:
            _validated_text(self.source, "Diagnostic source")
        if self.hint is not None:
            _validated_text(self.hint, "Diagnostic hint")
        object.__setattr__(self, "details", _copy_json_object(self.details, "Diagnostic details"))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.source is not None:
            result["source"] = self.source
        if self.hint is not None:
            result["hint"] = self.hint
        if self.details:
            result["details"] = _copy_json_object(self.details, "Diagnostic details")
        return result

    def render(self) -> str:
        location = f"{self.source}: " if self.source else ""
        rendered = f"[{self.code}] {location}{self.message}"
        if self.hint:
            rendered += f"\n  hint: {self.hint}"
        return rendered


@dataclass(frozen=True)
class ConversionIssue:
    code: str
    message: str
    source: str
    classification: SvgFeatureClass
    action: IssueAction
    feature: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.classification, SvgFeatureClass):
            raise ValueError("Conversion issue classification must be a SvgFeatureClass.")
        if not isinstance(self.action, IssueAction):
            raise ValueError("Conversion issue action must be an IssueAction.")
        expected = {
            SvgFeatureClass.LOSSY: IssueAction.CONVERTED,
            SvgFeatureClass.UNREPRESENTABLE: IssueAction.SKIPPED,
        }[self.classification]
        if self.action is not expected:
            raise ValueError(
                f"{self.classification.value} issues must use action {expected.value}."
            )
        code = _validated_text(self.code, "Conversion issue code")
        if _DIAGNOSTIC_CODE.fullmatch(code) is None:
            raise ValueError(
                "Conversion issue code must use uppercase letters, digits, and underscores."
            )
        _validated_text(self.message, "Conversion issue message")
        _validated_text(self.source, "Conversion issue source")
        _validated_text(self.feature, "Conversion issue feature")
        object.__setattr__(
            self,
            "details",
            _copy_json_object(self.details, "Conversion issue details"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "classification": self.classification.value,
            "action": self.action.value,
            "feature": self.feature,
        }
        if self.details:
            result["details"] = _copy_json_object(self.details, "Conversion issue details")
        return result

    def render(self) -> str:
        return (
            f"[{self.code}] {self.source}: {self.message} "
            f"({self.classification.value}, {self.action.value})"
        )


class IconFontError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        source: str | None = None,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.diagnostic = Diagnostic(
            code=code,
            message=message,
            source=source,
            hint=hint,
            details=details if details is not None else {},
        )
        super().__init__(self.diagnostic.render())


class SvgFeatureError(IconFontError):
    """A policy-addressable SVG feature, distinct from malformed or unsafe input."""

    def __init__(
        self,
        classification: SvgFeatureClass,
        feature: str,
        code: str,
        message: str,
        *,
        source: str | None = None,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(classification, SvgFeatureClass):
            raise ValueError("SVG feature classification must be a SvgFeatureClass.")
        _validated_text(feature, "SVG feature name")
        self.classification = classification
        self.feature = feature
        raw_details = details if details is not None else {}
        if type(raw_details) is not dict:
            raise ValueError("SVG feature details must be a JSON object.")
        classified_details: dict[str, Any] = {
            "classification": classification.value,
            "feature": feature,
            **raw_details,
        }
        super().__init__(
            code,
            message,
            source=source,
            hint=hint,
            details=classified_details,
        )


class SvgFeatureBatchError(Exception):
    def __init__(self, errors: Iterable[SvgFeatureError]) -> None:
        collected = tuple(errors)
        if not collected:
            raise ValueError("A feature batch must contain at least one error.")
        if any(not isinstance(error, SvgFeatureError) for error in collected):
            raise ValueError("A feature batch can contain only SvgFeatureError values.")
        self.errors = tuple(
            sorted(
                collected,
                key=lambda error: (
                    (error.diagnostic.source or "").encode("utf-8"),
                    error.classification.value,
                    error.diagnostic.code,
                    error.feature,
                ),
            )
        )
        super().__init__(f"{len(self.errors)} unsupported SVG feature(s)")


def conversion_notice(
    code: str,
    message: str,
    *,
    source: str,
    feature: str,
    details: dict[str, Any] | None = None,
) -> ConversionIssue:
    """Create a deterministic record for an explicitly approved lossy conversion."""

    return ConversionIssue(
        code=code,
        message=message,
        source=source,
        classification=SvgFeatureClass.LOSSY,
        action=IssueAction.CONVERTED,
        feature=feature,
        details=details if details is not None else {},
    )


def skipped_issue(error: SvgFeatureError) -> ConversionIssue:
    return ConversionIssue(
        code=error.diagnostic.code,
        message=error.diagnostic.message,
        source=error.diagnostic.source or "<unknown>",
        classification=SvgFeatureClass.UNREPRESENTABLE,
        action=IssueAction.SKIPPED,
        feature=error.feature,
        details={
            key: value
            for key, value in error.diagnostic.details.items()
            if key not in {"classification", "feature"}
        },
    )


def issue_to_diagnostic(issue: ConversionIssue) -> Diagnostic:
    return Diagnostic(
        code=issue.code,
        message=issue.message,
        source=issue.source,
        details={
            "classification": issue.classification.value,
            "feature": issue.feature,
            "action": issue.action.value,
            **issue.details,
        },
    )


class BatchError(Exception):
    def __init__(self, diagnostics: Iterable[Diagnostic]) -> None:
        collected = tuple(diagnostics)
        if not collected:
            raise ValueError("An input error batch must contain at least one diagnostic.")
        if any(not isinstance(diagnostic, Diagnostic) for diagnostic in collected):
            raise ValueError("An input error batch can contain only Diagnostic values.")
        self.diagnostics = tuple(
            sorted(
                collected,
                key=lambda item: (
                    (item.source or "").encode("utf-8"),
                    item.code,
                    item.message,
                ),
            )
        )
        super().__init__(f"{len(self.diagnostics)} input error(s)")


def as_diagnostic(error: Exception, *, source: str | None = None) -> Diagnostic:
    if isinstance(error, IconFontError):
        diagnostic = error.diagnostic
        if diagnostic.source is not None or source is None:
            return diagnostic
        return Diagnostic(
            code=diagnostic.code,
            message=diagnostic.message,
            source=source,
            hint=diagnostic.hint,
            details=diagnostic.details,
        )
    return Diagnostic(
        code="INTERNAL_CONVERSION_ERROR",
        message="An unexpected internal error occurred while converting this SVG.",
        source=source,
        hint="Report this input and diagnostic if the failure is reproducible.",
        details={"exceptionType": error.__class__.__name__},
    )
