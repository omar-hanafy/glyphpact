# GlyphPact architecture

## Invariants

The compiler has eight non-negotiable invariants:

1. One emitted SVG produces exactly one non-empty font glyph and one Dart
   constant.
2. A lossless conversion is automatic, a lossy conversion requires explicit
   approval, and an unrepresentable source is skipped only with explicit
   approval.
3. Invalid, unsafe, unknown, over-budget, and internal-failure states always
   prevent publication. They can never become skips.
4. Codepoints are allocated from the lock, never inferred again from directory
   order.
5. A skipped source becomes a retired tombstone. Its codepoint and name remain
   reserved, and its geometry digest is absent.
6. Final glyph union and canvas clipping happen after mapping to the integer
   font grid.
7. The emitted font is reopened and checked against the Dart API before any
   output path changes.
8. The CFF vertical `FontBBox` covers the declared ascent and descent while the
   OpenType `head` bounds remain tight to real outlines, so Flutter preserves
   SVG viewBox placement independently of which icons happen to share a font.

## Data flow

```text
filesystem discovery
  -> normalized source IDs and SHA-256
  -> pinned-font descriptor validation and parser preflight
  -> prior-lock loading and stable codepoint allocation
  -> raw XML security, limits, and external-reference preflight
  -> bounded static CSS cascade materialization
  -> hard semantic/reference validation, no-op pruning, and resource reachability
  -> local reuse, symbol, clip, marker, dash, viewport, paint, and text normalization
  -> PicoSVG semantic normalization
  -> typed outcome: lossless, approximated, unrepresentable, or hard failure
  -> canonical path list and viewBox for emitted sources
  -> active-glyph and skipped-tombstone finalization
  -> em-square transform and integer quantization
  -> Skia PathOps union and viewBox clipping
  -> Type 2 charstrings
  -> FontTools OpenType/CFF builder
  -> stable CFF vertical metric envelope
  -> cmap, metric, bound, checksum, and table validation
  -> Dart, lock, report, and font staging
  -> locked, flushed, recoverable transaction-wrapped directory swap
```

PicoSVG is deliberately behind a policy layer. It is excellent at geometry,
but its compact SVG target allows some visual declarations to disappear. The
preflight classifies semantics before they can be erased, and custom bounded
normalizers materialize the supported static subset before PicoSVG produces
canonical paths.

Policy is represented by data types, not warning strings. A compiled worker
outcome can carry only `lossy` and `converted` issues. A skipped worker outcome
must carry one or more `unrepresentable` and `skipped` issues. A hard-failure
outcome carries diagnostics and aborts publication under all policies. This
prevents a later caller from accidentally treating an approximation or omission
as an ordinary success.

`Unrepresentable` is scoped to the versioned deterministic source profile and
the inputs declared for a build. It includes semantics that need an external
rendering environment and profile extensions that this compiler cannot yet
flatten faithfully. It is not a claim that no future normalizer or browser could
process the source. This distinction keeps unsupported-but-valid SVG separate
from malformed, unsafe, unknown, or over-budget input, which always remains a
hard failure.

Lossy policy is checked after region-aware alpha proof, not when a potentially
lossy declaration is first encountered. Fractional alpha, spatial gradient
alpha, noncovering radial-gradient paint, patterns, and multi-child group opacity
carry provenance through paint order. Later opaque coverage subtracts from those
pending regions. A feature requires permission and produces an issue only when
part of its affected region survives. Source RGB is canonicalized before
internal provenance is encoded, so no valid source color can forge an internal
fidelity state.

Hard validation is deliberately global and precedes pruning. CSS declarations,
structural reference target types, paint fallback syntax, resource-template
cycles, transforms, paint-server attributes, fonts, and work bounds are checked
before an unrepresentable feature can become a skip. The compiler then removes
exact no-ops and computes transitive reachability, allowing unused unsupported
definitions to disappear without turning unreachable content into a safety
bypass.

FontTools is also behind a small adapter. `FontBuilder` documents itself as an
experimental convenience API, so call order, tables, timestamps, and reopen
validation are locked by regression tests. FontTools first calculates tight
outline and horizontal metrics normally. A second no-recalculation pass widens
only the CFF vertical `FontBBox` to the declared metric interval. This preserves
accurate `head` bounds while preventing Flutter text backends from deriving a
glyph-pack-dependent baseline from a positive CFF y-minimum.

The lock spans recovery, prior-lock loading, allocation, compilation, and
publication. This prevents two compiler processes from deriving divergent ABI
updates from the same prior lock. The sibling coordination file persists so
removing and recreating a lock inode cannot let a third process bypass an
already-held lock.

When adopting a foreign directory, the previous tree is moved under a distinct
owned transaction wrapper. Recovery can restore that payload after interruption
without accepting its contents as a generated ownership marker. Renames that
cross the wrapper boundary flush both affected directories before cleanup.

## Why OpenType/CFF

SVG paths are naturally cubic. A TrueType `glyf` backend would require
cubic-to-quadratic approximation before every build. CFF keeps cubic curves,
produces compact fonts, and is supported by Flutter. The backend can be
replaced later without changing the lock or Dart API.

## Publication boundary

The canonical glyph boundary has typed fidelity states, and the lock is the
only codepoint authority. No artifact is published until every source is either
emitted or explicitly skipped, all hard checks pass, and the final font
validates. An all-skipped batch cannot publish an empty font.

Successful result and report payloads use schema version 2. The lock remains
schema version 1 because it records ABI allocation rather than the policy used
for a particular build.
