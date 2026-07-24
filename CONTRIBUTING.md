# Contributing

## Setup

Install [uv](https://docs.astral.sh/uv/), then create the locked development
environment:

```bash
uv sync --locked --all-groups
```

## Required gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

Set `RUN_FLUTTER_TESTS=1` when a Flutter SDK is available. That gate loads and
rasterizes app and package fonts, analyzes generated Dart, and checks release
web subsetting.

## SVG semantics

Classify a feature before implementing it:

- A lossless normalizer needs equivalence coverage and the nearest malformed or
  resource-exhausting rejection case.
- A lossy normalizer must fail under the default policy, succeed only with
  explicit `lossy=convert`, and emit a typed `lossy` and `converted` issue.
- An unrepresentable feature must fail under the default policy, skip only with
  explicit `unrepresentable=skip`, and emit a typed `unrepresentable` and
  `skipped` issue.
- Scripts, external references, event handlers, malformed or unknown semantics,
  work-limit failures, and internal failures must stay fatal under all policy
  combinations.

Never add a silent approximation, warning-only fidelity loss, or generic
catch-and-skip path.

## Allocation and publication

Changes must prove that:

- prior lock state survives failure
- tombstones reserve and later reactivate their codepoints
- an all-skipped batch publishes nothing
- worker counts produce byte-identical artifacts
- foreign output is never adopted without explicit permission

## Fixtures

New portable fixtures must be original work or carry a compatible license.
Include a short provenance note when the source is not authored for this
repository. Never submit proprietary artwork.

## Pull requests

Keep changes focused, describe the public behavior being changed, and list the
validation you ran. A changelog entry should describe the net user-visible
difference from the latest public release, not intermediate implementation
steps.
