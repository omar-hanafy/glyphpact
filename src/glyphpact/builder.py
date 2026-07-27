from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from .attribution import generate_attribution
from .config import (
    BuildConfig,
    ConversionPolicy,
    LossyPolicy,
    UnrepresentablePolicy,
    private_use_range,
)
from .dart_generator import DartLayer, generate_dart
from .discovery import SvgSource, discover_svg_sources
from .errors import (
    BatchError,
    ConversionIssue,
    Diagnostic,
    IconFontError,
    IssueAction,
    SvgFeatureBatchError,
    SvgFeatureClass,
    SvgFeatureError,
    as_diagnostic,
    issue_to_diagnostic,
    skipped_issue,
)
from .font_builder import FontArtifact, GlyphInput, build_font
from .identity import GENERATOR_ID
from .manifest import (
    LockGlyph,
    LockState,
    assign_glyphs,
    finalize_glyphs,
    format_codepoint,
    load_lock,
    lock_json,
    with_geometry_digests,
)
from .output_lock import output_lock
from .publisher import (
    MARKER,
    compare_artifacts,
    marker_bytes,
    publish_artifacts,
    recover_output,
    validate_output_tree,
    verify_output_ownership,
)
from .svg_compiler import CanonicalGlyph, CanonicalLayer, compile_svg
from .text_outliner import validate_text_fonts
from .version import __version__

_PATH_COMMAND = re.compile(r"[AaCcHhLlMmQqSsTtVvZz]")
_CODEPOINT_RANGE_WARNING_NUMERATOR = 4
_CODEPOINT_RANGE_WARNING_DENOMINATOR = 5
_CODEPOINT_RANGE_WARNING_THRESHOLD = (
    _CODEPOINT_RANGE_WARNING_NUMERATOR / _CODEPOINT_RANGE_WARNING_DENOMINATOR
)


@dataclass(frozen=True)
class BuildResult:
    output_dir: Path
    font_path: Path
    dart_path: Path
    lock_path: Path
    report_path: Path
    layer_font_paths: tuple[Path, ...]
    glyph_count: int
    discovered_icon_count: int
    lossless_glyph_count: int
    approximated_glyph_count: int
    skipped_icon_count: int
    issues: tuple[ConversionIssue, ...]
    policy: ConversionPolicy
    font_sha256: str
    checked: bool
    codepoints_remaining: int = field(default=0, kw_only=True)
    range_utilization: float = field(default=0.0, kw_only=True)
    warnings: tuple[Diagnostic, ...] = field(default=(), kw_only=True)

    @property
    def quality(self) -> str:
        if self.skipped_icon_count:
            return "partial"
        if self.approximated_glyph_count:
            return "approximated"
        return "lossless"


@dataclass(frozen=True)
class _CodepointCapacity:
    start: int
    end: int
    capacity: int
    consumed: int
    remaining: int
    utilization: float

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        if (
            self.consumed * _CODEPOINT_RANGE_WARNING_DENOMINATOR
            < self.capacity * _CODEPOINT_RANGE_WARNING_NUMERATOR
        ):
            return ()
        noun = "codepoint" if self.remaining == 1 else "codepoints"
        verb = "remains" if self.remaining == 1 else "remain"
        return (
            Diagnostic(
                code="CODEPOINT_RANGE_NEAR_EXHAUSTION",
                message=(
                    f"{self.consumed:,} of {self.capacity:,} codepoints in the "
                    "configured private-use allocation window are consumed "
                    f"({self.utilization:.4%}); {self.remaining:,} {noun} {verb}."
                ),
                hint=(
                    "Split the pack into another stable font family before this window "
                    "is exhausted. Never recycle retired codepoints."
                ),
                details={
                    "startCodepoint": format_codepoint(self.start),
                    "endCodepoint": format_codepoint(self.end),
                    "capacity": self.capacity,
                    "consumed": self.consumed,
                    "codepointsRemaining": self.remaining,
                    "rangeUtilization": self.utilization,
                    "threshold": _CODEPOINT_RANGE_WARNING_THRESHOLD,
                },
            ),
        )


def _codepoint_capacity(state: LockState, config: BuildConfig) -> _CodepointCapacity:
    bounds = private_use_range(config.start_codepoint)
    assert bounds is not None
    end = bounds[1]
    capacity = end - config.start_codepoint + 1
    assignments = (*state.active, *state.retired)
    if any(not config.start_codepoint <= glyph.codepoint <= end for glyph in assignments):
        raise IconFontError(
            "INTERNAL_CODEPOINT_RANGE_MISMATCH",
            "The finalized lock contains a codepoint outside its allocation window.",
            hint="Report this invariant failure. No output was published.",
        )
    consumed = len(assignments)
    remaining = capacity - consumed
    utilization = consumed / capacity
    return _CodepointCapacity(
        start=config.start_codepoint,
        end=end,
        capacity=capacity,
        consumed=consumed,
        remaining=remaining,
        utilization=utilization,
    )


@dataclass(frozen=True)
class _Compiled:
    source: SvgSource
    lock: LockGlyph
    geometry: CanonicalGlyph

    def __post_init__(self) -> None:
        if not isinstance(self.source, SvgSource) or not isinstance(self.lock, LockGlyph):
            raise ValueError("Compiled outcomes require typed source and lock values.")
        if not isinstance(self.geometry, CanonicalGlyph):
            raise ValueError("Compiled outcomes require typed canonical geometry.")
        if self.lock.source != self.source.source_id:
            raise ValueError("Compiled source and lock identities must match.")
        if self.lock.geometry_sha256 is None:
            raise ValueError("Compiled lock entries require a geometry digest.")


@dataclass(frozen=True)
class _LayerFont:
    index: int
    family: str
    file: PurePosixPath
    font: FontArtifact


@dataclass(frozen=True)
class _Skipped:
    source: SvgSource
    lock: LockGlyph
    issues: tuple[ConversionIssue, ...]
    previously_emitted: bool

    def __post_init__(self) -> None:
        if not isinstance(self.source, SvgSource) or not isinstance(self.lock, LockGlyph):
            raise ValueError("Skipped outcomes require typed source and lock values.")
        if self.lock.source != self.source.source_id:
            raise ValueError("Skipped source and lock identities must match.")
        if type(self.previously_emitted) is not bool:
            raise ValueError("Skipped previously-emitted state must be boolean.")
        if (
            type(self.issues) is not tuple
            or not self.issues
            or any(
                not isinstance(issue, ConversionIssue)
                or issue.classification is not SvgFeatureClass.UNREPRESENTABLE
                or issue.action is not IssueAction.SKIPPED
                or issue.source != self.source.source_id
                for issue in self.issues
            )
        ):
            raise ValueError("Skipped inputs require unrepresentable/skipped issues.")


@dataclass(frozen=True)
class _WorkerCompiled:
    source: SvgSource
    geometry: CanonicalGlyph
    work_charge: int

    def __post_init__(self) -> None:
        if not isinstance(self.source, SvgSource) or not isinstance(self.geometry, CanonicalGlyph):
            raise ValueError("Compiled worker outcomes require typed source and geometry values.")
        if type(self.work_charge) is not int or self.work_charge <= 0:
            raise ValueError("Compiled worker work charge must be a positive integer.")
        if self.work_charge != self.geometry.path_command_count:
            raise ValueError("Compiled worker work charge must equal canonical path commands.")
        if type(self.geometry.issues) is not tuple or any(
            not isinstance(issue, ConversionIssue)
            or issue.classification is not SvgFeatureClass.LOSSY
            or issue.action is not IssueAction.CONVERTED
            or issue.source != self.source.source_id
            for issue in self.geometry.issues
        ):
            raise ValueError("Compiled inputs can carry only lossy/converted issues.")


@dataclass(frozen=True)
class _WorkerSkipped:
    source: SvgSource
    issues: tuple[ConversionIssue, ...]
    work_charge: int

    def __post_init__(self) -> None:
        if not isinstance(self.source, SvgSource):
            raise ValueError("Skipped worker outcomes require a typed source.")
        if type(self.work_charge) is not int or self.work_charge <= 0:
            raise ValueError("Skipped worker work charge must be a positive integer.")
        if (
            type(self.issues) is not tuple
            or not self.issues
            or any(
                not isinstance(issue, ConversionIssue)
                or issue.classification is not SvgFeatureClass.UNREPRESENTABLE
                or issue.action is not IssueAction.SKIPPED
                or issue.source != self.source.source_id
                for issue in self.issues
            )
        ):
            raise ValueError("Skipped worker outcomes require unrepresentable issues.")


@dataclass(frozen=True)
class _WorkerFailed:
    source: SvgSource
    diagnostics: tuple[Diagnostic, ...]
    work_charge: int

    def __post_init__(self) -> None:
        if not isinstance(self.source, SvgSource):
            raise ValueError("Failed worker outcomes require a typed source.")
        if type(self.work_charge) is not int or self.work_charge <= 0:
            raise ValueError("Failed worker work charge must be a positive integer.")
        if (
            type(self.diagnostics) is not tuple
            or not self.diagnostics
            or any(not isinstance(diagnostic, Diagnostic) for diagnostic in self.diagnostics)
        ):
            raise ValueError("Failed worker outcomes require at least one diagnostic.")


_WorkerResult = _WorkerCompiled | _WorkerSkipped | _WorkerFailed


def _invalid_worker_result(message: str, source: SvgSource) -> IconFontError:
    return IconFontError(
        "INTERNAL_WORKER_RESULT_INVALID",
        message,
        source=source.source_id,
        hint="Report this invariant failure. No output was published.",
    )


def _same_source(left: SvgSource, right: SvgSource) -> bool:
    return (
        left.path == right.path
        and left.source_id == right.source_id
        and left.sha256 == right.sha256
        and left.byte_count == right.byte_count
    )


def _scoped_layered_fallback_issues(
    source: SvgSource,
    geometry: CanonicalGlyph,
    config: BuildConfig,
) -> bool:
    override = config.icons.get(source.source_id)
    partial_alpha = override.partial_alpha if override is not None else None
    if partial_alpha is None or not geometry.layers or not geometry.issues:
        return False
    expected_code = (
        "SVG_PARTIAL_ALPHA_DROPPED"
        if partial_alpha.fallback.value == "opaque-only"
        else "SVG_PARTIAL_ALPHA_APPROXIMATED"
    )
    return all(
        issue.code == expected_code
        and issue.feature == "fractional-alpha"
        and issue.details.get("scope") == "single-glyph-fallback"
        and issue.details.get("losslessLayeredOutput") is True
        for issue in geometry.issues
    )


def _validate_canonical_geometry(
    source: SvgSource,
    geometry: CanonicalGlyph,
    config: BuildConfig,
) -> None:
    if not isinstance(geometry, CanonicalGlyph):
        raise _invalid_worker_result("The compiler returned an untyped canonical glyph.", source)
    if type(geometry.paths) is not tuple or not geometry.paths:
        raise _invalid_worker_result("Canonical glyph paths must be a non-empty tuple.", source)
    if type(geometry.fill_rules) is not tuple or len(geometry.fill_rules) != len(geometry.paths):
        raise _invalid_worker_result(
            "Canonical paths and fill rules must have identical non-zero lengths.", source
        )
    actual_commands = 0
    for path in geometry.paths:
        if type(path) is not str or not path:
            raise _invalid_worker_result("Canonical paths must be non-empty strings.", source)
        try:
            path.encode("ascii")
        except UnicodeEncodeError as error:
            raise _invalid_worker_result(
                "Canonical paths must contain only ASCII syntax.", source
            ) from error
        actual_commands += len(_PATH_COMMAND.findall(path))
    if type(geometry.layers) is not tuple:
        raise _invalid_worker_result("Canonical layers must be a tuple.", source)
    for layer in geometry.layers:
        if not isinstance(layer, CanonicalLayer):
            raise _invalid_worker_result("Canonical layers must be typed layer values.", source)
        if (
            type(layer.paths) is not tuple
            or not layer.paths
            or type(layer.fill_rules) is not tuple
            or len(layer.fill_rules) != len(layer.paths)
        ):
            raise _invalid_worker_result(
                "Canonical layer paths and fill rules must have identical non-zero lengths.",
                source,
            )
        layer_commands = 0
        for path in layer.paths:
            if type(path) is not str or not path:
                raise _invalid_worker_result(
                    "Canonical layer paths must be non-empty strings.", source
                )
            try:
                path.encode("ascii")
            except UnicodeEncodeError as error:
                raise _invalid_worker_result(
                    "Canonical layer paths must contain only ASCII syntax.", source
                ) from error
            layer_commands += len(_PATH_COMMAND.findall(path))
        if any(
            type(fill_rule) is not str or fill_rule not in {"evenodd", "nonzero"}
            for fill_rule in layer.fill_rules
        ):
            raise _invalid_worker_result(
                "Canonical layer fill rules must be evenodd or nonzero.", source
            )
        if (
            type(layer.opacity) not in {int, float}
            or not math.isfinite(layer.opacity)
            or not 0 < layer.opacity <= 1
        ):
            raise _invalid_worker_result(
                "Canonical layer opacity must be finite and in (0, 1].", source
            )
        if (
            type(layer.bounds) is not tuple
            or len(layer.bounds) != 4
            or any(
                type(value) not in {int, float} or not math.isfinite(value)
                for value in layer.bounds
            )
            or layer.bounds[2] <= layer.bounds[0]
            or layer.bounds[3] <= layer.bounds[1]
        ):
            raise _invalid_worker_result(
                "Canonical layer bounds must enclose positive finite area.", source
            )
        if type(layer.path_command_count) is not int or layer.path_command_count <= 0:
            raise _invalid_worker_result(
                "Canonical layer path-command count must be positive.", source
            )
        if layer.path_command_count != layer_commands:
            raise _invalid_worker_result(
                "Canonical layer path-command accounting does not match emitted data.",
                source,
            )
        actual_commands += layer_commands
    if any(
        type(fill_rule) is not str or fill_rule not in {"evenodd", "nonzero"}
        for fill_rule in geometry.fill_rules
    ):
        raise _invalid_worker_result("Canonical fill rules must be evenodd or nonzero.", source)
    if type(geometry.source_shape_count) is not int or geometry.source_shape_count <= 0:
        raise _invalid_worker_result(
            "Canonical source-shape count must be a positive integer.", source
        )
    if type(geometry.path_command_count) is not int or geometry.path_command_count <= 0:
        raise _invalid_worker_result(
            "Canonical path-command count must be a positive integer.", source
        )
    if geometry.path_command_count != actual_commands:
        raise _invalid_worker_result(
            "Canonical path-command accounting does not match the emitted path data.", source
        )
    if geometry.path_command_count > config.max_path_commands:
        raise _invalid_worker_result(
            "Canonical path-command accounting exceeds the configured per-icon limit.", source
        )
    for label, values in (("viewBox", geometry.view_box), ("bounds", geometry.bounds)):
        if (
            type(values) is not tuple
            or len(values) != 4
            or any(type(value) not in {int, float} or not math.isfinite(value) for value in values)
        ):
            raise _invalid_worker_result(
                f"Canonical {label} must contain four finite numbers.", source
            )
    if geometry.view_box[2] <= 0 or geometry.view_box[3] <= 0:
        raise _invalid_worker_result("Canonical viewBox dimensions must be positive.", source)
    if geometry.bounds[2] <= geometry.bounds[0] or geometry.bounds[3] <= geometry.bounds[1]:
        raise _invalid_worker_result("Canonical bounds must enclose positive area.", source)
    if type(geometry.issues) is not tuple or any(
        not isinstance(issue, ConversionIssue)
        or issue.classification is not SvgFeatureClass.LOSSY
        or issue.action is not IssueAction.CONVERTED
        or issue.source != source.source_id
        for issue in geometry.issues
    ):
        raise _invalid_worker_result(
            "Canonical issues must be lossy conversions for the same source.", source
        )
    if (
        geometry.issues
        and config.policy.lossy is LossyPolicy.ERROR
        and not _scoped_layered_fallback_issues(source, geometry, config)
    ):
        raise IconFontError(
            "INTERNAL_POLICY_VIOLATION",
            "A lossy canonical glyph crossed a strict lossy=error boundary.",
            source=source.source_id,
            hint="Report this invariant failure. No lossy output was published.",
        )


def _validate_worker_result(
    result: _WorkerResult,
    expected_source: SvgSource,
    config: BuildConfig,
) -> None:
    if not isinstance(result, (_WorkerCompiled, _WorkerSkipped, _WorkerFailed)):
        raise _invalid_worker_result("A worker returned an unknown outcome type.", expected_source)
    if not _same_source(result.source, expected_source):
        raise _invalid_worker_result(
            "A worker returned an outcome for a different source.", expected_source
        )
    if type(result.work_charge) is not int or result.work_charge <= 0:
        raise _invalid_worker_result(
            "Worker work charge must be a positive integer.", expected_source
        )
    if isinstance(result, _WorkerCompiled):
        _validate_canonical_geometry(expected_source, result.geometry, config)
        if result.work_charge != result.geometry.path_command_count:
            raise _invalid_worker_result(
                "Compiled work charge must equal canonical path-command work.", expected_source
            )
        return
    if result.work_charge != config.max_path_commands:
        raise _invalid_worker_result(
            "Skipped and failed workers must retain the full attempted work charge.",
            expected_source,
        )
    if isinstance(result, _WorkerSkipped):
        if config.policy.unrepresentable is not UnrepresentablePolicy.SKIP:
            raise IconFontError(
                "INTERNAL_POLICY_VIOLATION",
                "A skipped outcome crossed a strict unrepresentable=error boundary.",
                source=expected_source.source_id,
                hint="Report this invariant failure. No source was silently skipped.",
            )
        if any(issue.source != expected_source.source_id for issue in result.issues):
            raise _invalid_worker_result(
                "Skipped issues must identify the skipped source.", expected_source
            )


def _compile_worker_outcome(source: SvgSource, config: BuildConfig) -> _WorkerResult:
    try:
        geometry = compile_svg(source, config)
        _validate_canonical_geometry(source, geometry, config)
        return _WorkerCompiled(
            source=source,
            geometry=geometry,
            work_charge=geometry.path_command_count,
        )
    except SvgFeatureBatchError as error:
        work_charge = config.max_path_commands
        if (
            all(item.classification is SvgFeatureClass.UNREPRESENTABLE for item in error.errors)
            and config.policy.unrepresentable is UnrepresentablePolicy.SKIP
        ):
            return _WorkerSkipped(
                source=source,
                issues=tuple(skipped_issue(item) for item in error.errors),
                work_charge=work_charge,
            )
        return _WorkerFailed(
            source=source,
            diagnostics=tuple(
                as_diagnostic(item, source=source.source_id) for item in error.errors
            ),
            work_charge=work_charge,
        )
    except SvgFeatureError as error:
        work_charge = config.max_path_commands
        if (
            error.classification is SvgFeatureClass.UNREPRESENTABLE
            and config.policy.unrepresentable is UnrepresentablePolicy.SKIP
        ):
            return _WorkerSkipped(
                source=source,
                issues=(skipped_issue(error),),
                work_charge=work_charge,
            )
        return _WorkerFailed(
            source=source,
            diagnostics=(as_diagnostic(error, source=source.source_id),),
            work_charge=work_charge,
        )


def _compile_worker(source: SvgSource, config: BuildConfig) -> _WorkerResult:
    try:
        result = _compile_worker_outcome(source, config)
        _validate_worker_result(result, source, config)
        return result
    except Exception as error:
        return _WorkerFailed(
            source=source,
            diagnostics=(as_diagnostic(error, source=source.source_id),),
            work_charge=config.max_path_commands,
        )


def _compile_chunk_worker(
    sources: tuple[SvgSource, ...], config: BuildConfig
) -> tuple[_WorkerResult, ...]:
    return tuple(_compile_worker(source, config) for source in sources)


def _parallel_results(
    sources: tuple[SvgSource, ...], config: BuildConfig
) -> Iterator[_WorkerResult]:
    preferred_chunk_size = max(1, len(sources) // (config.jobs * 8))
    source_index = 0
    accounted_commands = 0
    reserved_commands = 0
    with ProcessPoolExecutor(max_workers=config.jobs) as executor:
        pending: deque[tuple[Future[tuple[_WorkerResult, ...]], tuple[SvgSource, ...], int]] = (
            deque()
        )

        def fill_pending() -> None:
            nonlocal source_index, reserved_commands
            while source_index < len(sources) and len(pending) < config.jobs:
                remaining = config.max_total_path_commands - accounted_commands - reserved_commands
                affordable = remaining // config.max_path_commands
                if affordable < 1:
                    if pending:
                        return
                    if accounted_commands >= config.max_total_path_commands:
                        raise IconFontError(
                            "SVG_BATCH_TOO_COMPLEX",
                            "The batch exhausted its attempted path-work budget.",
                            details={
                                "pathWork": accounted_commands,
                                "maxTotalPathCommands": config.max_total_path_commands,
                            },
                            hint="Fix rejected inputs, simplify the pack, or split it.",
                        )
                    # One speculative icon is necessary when the remaining real budget is
                    # smaller than the per-icon ceiling. Its actual result is checked before
                    # any further work is submitted.
                    count = 1
                else:
                    available_slots = min(
                        config.jobs - len(pending),
                        len(sources) - source_index,
                    )
                    count = min(
                        preferred_chunk_size,
                        max(1, affordable // available_slots),
                        len(sources) - source_index,
                    )
                chunk = sources[source_index : source_index + count]
                source_index += count
                reservation = count * config.max_path_commands
                reserved_commands += reservation
                pending.append(
                    (executor.submit(_compile_chunk_worker, chunk, config), chunk, reservation)
                )

        fill_pending()
        while pending:
            future, chunk, reservation = pending.popleft()
            results = future.result()
            if len(results) != len(chunk):
                raise _invalid_worker_result(
                    "A worker chunk returned an incomplete outcome set.", chunk[0]
                )
            for result, expected_source in zip(results, chunk, strict=True):
                _validate_worker_result(result, expected_source, config)
            reserved_commands -= reservation
            accounted_commands += sum(result.work_charge for result in results)
            yield from results
            fill_pending()


def _geometry_digest(geometry: CanonicalGlyph) -> str:
    digest = hashlib.sha256()
    for path, fill_rule in zip(geometry.paths, geometry.fill_rules, strict=True):
        digest.update(path.encode("ascii"))
        digest.update(b"\0")
        digest.update(fill_rule.encode("ascii"))
        digest.update(b"\0")
    digest.update(",".join(format(value, ".12g") for value in geometry.view_box).encode())
    for layer in geometry.layers:
        digest.update(b"\0layer\0")
        digest.update(format(layer.opacity, ".17g").encode("ascii"))
        digest.update(b"\0")
        for path, fill_rule in zip(layer.paths, layer.fill_rules, strict=True):
            digest.update(path.encode("ascii"))
            digest.update(b"\0")
            digest.update(fill_rule.encode("ascii"))
            digest.update(b"\0")
    return digest.hexdigest()


def _compile_all(
    sources: tuple[SvgSource, ...],
    state: LockState,
    config: BuildConfig,
) -> tuple[tuple[_Compiled, ...], tuple[_Skipped, ...], LockState]:
    lock_by_source = {glyph.source: glyph for glyph in state.active}
    diagnostics: list[Diagnostic] = []
    compiled: list[_Compiled] = []
    skipped: list[_Skipped] = []
    geometry_digests: dict[str, str] = {}
    if config.jobs == 1 or len(sources) < 16:
        results: Iterable[_WorkerResult] = (_compile_worker(source, config) for source in sources)
    else:
        results = _parallel_results(sources, config)

    total_path_commands = 0
    result_count = 0
    try:
        for index, result in enumerate(results):
            if index >= len(sources):
                raise _invalid_worker_result(
                    "Workers returned more outcomes than discovered sources.", sources[-1]
                )
            source = sources[index]
            _validate_worker_result(result, source, config)
            result_count = index + 1
            total_path_commands += result.work_charge
            if total_path_commands > config.max_total_path_commands:
                raise IconFontError(
                    "SVG_BATCH_TOO_COMPLEX",
                    "The batch exceeds the configured total canonical or attempted "
                    "path-work limit.",
                    details={
                        "pathWork": total_path_commands,
                        "maxTotalPathCommands": config.max_total_path_commands,
                    },
                    hint="Fix rejected inputs, simplify the pack, or split it.",
                )
            if isinstance(result, _WorkerFailed):
                diagnostics.extend(result.diagnostics)
            elif isinstance(result, _WorkerSkipped):
                skipped.append(
                    _Skipped(
                        source=source,
                        lock=lock_by_source[source.source_id],
                        issues=result.issues,
                        previously_emitted=(
                            lock_by_source[source.source_id].geometry_sha256 is not None
                        ),
                    )
                )
            else:
                geometry = result.geometry
                try:
                    geometry_digest = _geometry_digest(geometry)
                    geometry_digests[source.source_id] = geometry_digest
                    lock = lock_by_source[source.source_id]
                    compiled.append(
                        _Compiled(
                            source=source,
                            lock=LockGlyph(
                                source=lock.source,
                                name=lock.name,
                                codepoint=lock.codepoint,
                                source_sha256=lock.source_sha256,
                                geometry_sha256=geometry_digest,
                                match_text_direction=lock.match_text_direction,
                                metadata=lock.metadata,
                            ),
                            geometry=geometry,
                        )
                    )
                except Exception as error:
                    diagnostics.append(as_diagnostic(error, source=source.source_id))
            if total_path_commands >= config.max_total_path_commands and index + 1 < len(sources):
                raise IconFontError(
                    "SVG_BATCH_TOO_COMPLEX",
                    "The batch exhausted its canonical or attempted path-work budget.",
                    details={
                        "pathWork": total_path_commands,
                        "maxTotalPathCommands": config.max_total_path_commands,
                    },
                    hint="Fix rejected inputs, simplify the pack, or split it.",
                )
    except (BatchError, IconFontError):
        raise
    except Exception as error:
        raise IconFontError(
            "WORKER_POOL_FAILED",
            str(error) or error.__class__.__name__,
            hint="Retry with --jobs 1 to isolate the failing input.",
        ) from error
    if result_count != len(sources):
        raise _invalid_worker_result(
            "Workers returned fewer outcomes than discovered sources.", sources[result_count]
        )
    if diagnostics:
        diagnostics.extend(issue_to_diagnostic(issue) for item in skipped for issue in item.issues)
        raise BatchError(diagnostics)
    emitted_sources = frozenset(item.source.source_id for item in compiled)
    skipped_sources = frozenset(item.source.source_id for item in skipped)
    state = with_geometry_digests(state, geometry_digests)
    state = finalize_glyphs(
        state,
        emitted_sources=emitted_sources,
        skipped_sources=skipped_sources,
    )
    if not compiled:
        raise BatchError(issue_to_diagnostic(issue) for item in skipped for issue in item.issues)
    return tuple(compiled), tuple(skipped), state


def _layer_font_family(font_family: str, index: int) -> str:
    suffix = f" Layer {index + 1}"
    return f"{font_family[: 63 - len(suffix)]}{suffix}"


def _layer_geometry(item: _Compiled, index: int) -> CanonicalGlyph:
    layer = item.geometry.layers[index]
    return CanonicalGlyph(
        paths=layer.paths,
        fill_rules=layer.fill_rules,
        view_box=item.geometry.view_box,
        bounds=layer.bounds,
        source_shape_count=len(layer.paths),
        path_command_count=layer.path_command_count,
    )


def _build_layer_fonts(
    compiled: tuple[_Compiled, ...],
    config: BuildConfig,
) -> tuple[_LayerFont, ...]:
    layer_count = max((len(item.geometry.layers) for item in compiled), default=0)
    fonts: list[_LayerFont] = []
    for index in range(layer_count):
        family = _layer_font_family(config.font_family, index)
        file = PurePosixPath("layer_fonts") / f"layer_{index + 1}.otf"
        inputs: list[GlyphInput] = []
        for item in compiled:
            if index >= len(item.geometry.layers):
                continue
            geometry = _layer_geometry(item, index)
            inputs.append(
                GlyphInput(
                    lock=replace(
                        item.lock,
                        geometry_sha256=_geometry_digest(geometry),
                    ),
                    geometry=geometry,
                )
            )
        layer_config = replace(config, font_family=family)
        fonts.append(
            _LayerFont(
                index=index,
                family=family,
                file=file,
                font=build_font(inputs, layer_config),
            )
        )
    return tuple(fonts)


def _dart_layers(
    compiled: tuple[_Compiled, ...],
    layer_fonts: tuple[_LayerFont, ...],
) -> dict[str, tuple[DartLayer, ...]]:
    return {
        item.source.source_id: tuple(
            DartLayer(
                font_family=layer_fonts[index].family,
                opacity=layer.opacity,
            )
            for index, layer in enumerate(item.geometry.layers)
        )
        for item in compiled
        if item.geometry.layers
    }


def _report(
    compiled: tuple[_Compiled, ...],
    skipped: tuple[_Skipped, ...],
    font: FontArtifact,
    layer_fonts: tuple[_LayerFont, ...],
    state: LockState,
    config: BuildConfig,
    capacity: _CodepointCapacity,
) -> bytes:
    font_by_source = {glyph.source: glyph for glyph in font.glyphs}
    layer_font_by_source = {
        layer_font.index: {glyph.source: glyph for glyph in layer_font.font.glyphs}
        for layer_font in layer_fonts
    }
    glyphs: list[dict[str, Any]] = []
    for item in sorted(compiled, key=lambda value: value.lock.codepoint):
        font_glyph = font_by_source[item.source.source_id]
        layered_rendering: dict[str, Any] = {}
        if item.geometry.layers:
            override = config.icons[item.source.source_id]
            assert override.partial_alpha is not None
            layered_rendering = {
                "layeredRendering": {
                    "lossless": True,
                    "fallback": override.partial_alpha.fallback.value,
                    "layers": [
                        {
                            "paintOrder": index,
                            "opacity": layer.opacity,
                            "fontFamily": layer_fonts[index].family,
                            "fontFile": layer_fonts[index].file.as_posix(),
                            "codepoint": format_codepoint(item.lock.codepoint),
                            "fontBounds": [
                                round(value, 6)
                                for value in layer_font_by_source[index][
                                    item.source.source_id
                                ].bounds
                            ],
                        }
                        for index, layer in enumerate(item.geometry.layers)
                    ],
                }
            }
        glyphs.append(
            {
                "source": item.source.source_id,
                "name": item.lock.name,
                "codepoint": format_codepoint(item.lock.codepoint),
                "sourceSha256": item.source.sha256,
                "geometrySha256": item.lock.geometry_sha256,
                "sourceBytes": item.source.byte_count,
                "sourceShapes": item.geometry.source_shape_count,
                "pathCommands": item.geometry.path_command_count,
                "viewBox": list(item.geometry.view_box),
                "fontBounds": [round(value, 6) for value in font_glyph.bounds],
                "advance": font_glyph.advance,
                "matchTextDirection": item.lock.match_text_direction,
                "conversion": "approximated" if item.geometry.issues else "lossless",
                "issues": [issue.to_dict() for issue in item.geometry.issues],
                **layered_rendering,
                **(
                    {"metadata": dict(sorted(item.lock.metadata.items()))}
                    if item.lock.metadata
                    else {}
                ),
            }
        )
    skipped_icons = [
        {
            "source": item.source.source_id,
            "name": item.lock.name,
            "codepoint": format_codepoint(item.lock.codepoint),
            "sourceSha256": item.source.sha256,
            "sourceBytes": item.source.byte_count,
            "previouslyEmitted": item.previously_emitted,
            "issues": [issue.to_dict() for issue in item.issues],
            **(
                {"metadata": dict(sorted(item.lock.metadata.items()))} if item.lock.metadata else {}
            ),
        }
        for item in sorted(skipped, key=lambda value: value.source.source_id.encode("utf-8"))
    ]
    approximated_count = sum(bool(item.geometry.issues) for item in compiled)
    all_issues = tuple(
        sorted(
            (
                *(issue for item in compiled for issue in item.geometry.issues),
                *(issue for item in skipped for issue in item.issues),
            ),
            key=lambda issue: (
                issue.source.encode("utf-8"),
                issue.classification.value,
                issue.code,
                issue.feature,
            ),
        )
    )
    quality = "partial" if skipped else "approximated" if approximated_count else "lossless"
    payload = {
        "schemaVersion": 3,
        "generator": GENERATOR_ID,
        "generatorVersion": __version__,
        "status": "success",
        "quality": quality,
        "policy": {
            "lossy": config.policy.lossy.value,
            "unrepresentable": config.policy.unrepresentable.value,
        },
        "discoveredIconCount": len(compiled) + len(skipped),
        "glyphCount": len(compiled),
        "losslessGlyphCount": len(compiled) - approximated_count,
        "approximatedGlyphCount": approximated_count,
        "skippedIconCount": len(skipped),
        "issueCount": len(all_issues),
        "issues": [issue.to_dict() for issue in all_issues],
        "retiredCodepointCount": len(state.retired),
        "codepointsRemaining": capacity.remaining,
        "rangeUtilization": capacity.utilization,
        "textFonts": [
            {"family": family, "sha256": text_font.sha256}
            for family, text_font in sorted(
                config.text_fonts.items(), key=lambda item: item[0].casefold()
            )
        ],
        "font": {
            "family": config.font_family,
            "format": "OpenType/CFF",
            "file": config.font_file.as_posix() if config.font_file else None,
            "sha256": font.sha256,
            "bytes": len(font.data),
            "unitsPerEm": config.units_per_em,
            "ascent": font.ascent,
            "descent": font.descent,
            "tables": list(font.tables),
        },
        "layerFonts": [
            {
                "paintOrder": layer_font.index,
                "family": layer_font.family,
                "format": "OpenType/CFF",
                "file": layer_font.file.as_posix(),
                "sha256": layer_font.font.sha256,
                "bytes": len(layer_font.font.data),
                "glyphCount": len(layer_font.font.glyphs),
                "unitsPerEm": config.units_per_em,
                "ascent": layer_font.font.ascent,
                "descent": layer_font.font.descent,
                "tables": list(layer_font.font.tables),
            }
            for layer_font in layer_fonts
        ],
        "dart": {
            "className": config.class_name,
            "file": config.dart_file.as_posix() if config.dart_file else None,
            "fontPackage": config.font_package,
        },
        "lockFile": config.lock_file.as_posix(),
        "attributionFile": "ATTRIBUTION.md",
        "glyphs": glyphs,
        "skippedIcons": skipped_icons,
    }
    return (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
        "utf-8"
    )


def _artifacts(
    compiled: tuple[_Compiled, ...],
    skipped: tuple[_Skipped, ...],
    state: LockState,
    font: FontArtifact,
    layer_fonts: tuple[_LayerFont, ...],
    config: BuildConfig,
    capacity: _CodepointCapacity,
) -> dict[PurePosixPath, bytes]:
    assert config.font_file is not None
    assert config.dart_file is not None
    artifacts = {
        PurePosixPath(MARKER): marker_bytes(),
        PurePosixPath("ATTRIBUTION.md"): generate_attribution(state.active, config),
        config.font_file: font.data,
        config.dart_file: generate_dart(
            state.active,
            config,
            layers_by_source=_dart_layers(compiled, layer_fonts),
        ),
        config.lock_file: lock_json(state, config),
        config.report_file: _report(
            compiled,
            skipped,
            font,
            layer_fonts,
            state,
            config,
            capacity,
        ),
        **{layer_font.file: layer_font.font.data for layer_font in layer_fonts},
    }
    if len(artifacts) != 6 + len(layer_fonts):
        raise IconFontError(
            "OUTPUT_ARTIFACT_CONFLICT",
            "Generated artifact paths are not unique.",
        )
    return artifacts


def build(
    config: BuildConfig,
    *,
    check: bool = False,
    adopt_output: bool = False,
) -> BuildResult:
    config = config.validated()
    with output_lock(config.output_dir):
        return _build_locked(config, check=check, adopt_output=adopt_output)


def _build_locked(
    config: BuildConfig,
    *,
    check: bool,
    adopt_output: bool,
) -> BuildResult:
    assert config.font_file is not None
    assert config.dart_file is not None
    validate_text_fonts(dict(config.text_fonts))
    lock_path = config.output_dir.joinpath(*config.lock_file.parts)
    recover_output(config.output_dir, lock_path=lock_path, read_only=check)
    owned_output = verify_output_ownership(
        config.output_dir,
        adopt=adopt_output and not check,
    )
    if owned_output:
        validate_output_tree(config.output_dir)
    if owned_output and (not lock_path.is_file() or lock_path.is_symlink()):
        raise IconFontError(
            "LOCK_MISSING",
            "An established generated output is missing its codepoint lock file.",
            source=str(lock_path),
            hint="Restore the committed lock file. Rebuilding without it would reset the icon ABI.",
        )
    sources = discover_svg_sources(
        config.input_path,
        max_bytes=config.max_file_bytes,
        max_total_bytes=config.max_total_input_bytes,
        max_icons=config.max_icons,
        max_entries=config.max_discovery_entries,
    )
    source_ids = {source.source_id for source in sources}
    unknown_overrides = sorted(set(config.icons) - source_ids)
    if unknown_overrides:
        raise IconFontError(
            "ICON_OVERRIDE_NOT_FOUND",
            "Icon override path(s) do not match any discovered SVG: "
            + ", ".join(repr(source) for source in unknown_overrides),
            hint="Override keys are case-sensitive paths relative to the input directory.",
        )
    previous = (
        load_lock(lock_path, expected_start_codepoint=config.start_codepoint)
        if owned_output
        else LockState()
    )
    assigned = assign_glyphs(sources, previous, config)
    compiled, skipped, assigned = _compile_all(sources, assigned, config)
    font = build_font(
        (GlyphInput(lock=item.lock, geometry=item.geometry) for item in compiled),
        config,
    )
    layer_fonts = _build_layer_fonts(compiled, config)
    capacity = _codepoint_capacity(assigned, config)
    artifacts = _artifacts(
        compiled,
        skipped,
        assigned,
        font,
        layer_fonts,
        config,
        capacity,
    )
    if check:
        compare_artifacts(config.output_dir, artifacts)
    else:
        publish_artifacts(config.output_dir, artifacts, adopt=adopt_output)
    issues = tuple(
        sorted(
            (
                *(issue for item in compiled for issue in item.geometry.issues),
                *(issue for item in skipped for issue in item.issues),
            ),
            key=lambda issue: (
                issue.source.encode("utf-8"),
                issue.classification.value,
                issue.code,
                issue.feature,
            ),
        )
    )
    approximated_count = sum(bool(item.geometry.issues) for item in compiled)
    return BuildResult(
        output_dir=config.output_dir,
        font_path=config.output_dir.joinpath(*config.font_file.parts),
        dart_path=config.output_dir.joinpath(*config.dart_file.parts),
        lock_path=lock_path,
        report_path=config.output_dir.joinpath(*config.report_file.parts),
        layer_font_paths=tuple(
            config.output_dir.joinpath(*layer_font.file.parts) for layer_font in layer_fonts
        ),
        glyph_count=len(compiled),
        discovered_icon_count=len(sources),
        lossless_glyph_count=len(compiled) - approximated_count,
        approximated_glyph_count=approximated_count,
        skipped_icon_count=len(skipped),
        issues=issues,
        policy=config.policy,
        font_sha256=font.sha256,
        checked=check,
        codepoints_remaining=capacity.remaining,
        range_utilization=capacity.utilization,
        warnings=capacity.warnings,
    )
