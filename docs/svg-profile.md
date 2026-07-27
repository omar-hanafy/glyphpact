# SVG profile for GlyphPact 1.x

This document defines the bounded source language and fidelity policy for
GlyphPact 1.x. The default target is the opaque monochrome alpha coverage rendered
by a normal icon-font glyph. A per-icon layered target can additionally preserve
ordered solid-alpha coverage through same-codepoint auxiliary font families.
Source RGB values are not part of either target because Flutter supplies the
glyph color at runtime.

Every source has exactly one typed outcome inside this bounded deterministic
profile:

1. A lossless source is normalized and emitted automatically.
2. A deterministically approximable source is emitted only when `lossy` is
   `convert`, with a `lossy` and `converted` issue in CLI and report output.
3. A source without a faithful conversion from its declared inputs through the
   profile is omitted only when `unrepresentable` is `skip`, with an
   `unrepresentable` and `skipped` issue.

`icons[...].partialAlpha.mode=layers` is a scoped exception to item 2. It emits
the exact supported layered representation while reporting its explicitly
selected `silhouette` or `opaque-only` single-glyph fallback as lossy. Global
`lossy=error` remains strict for every other feature and source.

Both policy axes default to `error`. Invalid, unsafe, unknown, over-budget, and
internal-failure states are not policy-addressable and always stop the build.
`unrepresentable` is a statement about this versioned profile and its declared
inputs, not a claim that no future compiler or full browser renderer could ever
flatten the source.

## Canvas and viewports

- The root must be `svg` in the SVG namespace.
- A finite positive numeric `viewBox` is preferred. Finite numeric or absolute
  CSS-unit root `width` and `height` provide the canvas when no viewBox exists.
  Root percentages need an embedding viewport and are unrepresentable. A
  zero-area viewport is an unrepresentable empty icon; a malformed, missing,
  non-finite, or negative viewport is invalid and fails.
- Nonzero viewBox origins, non-square viewBoxes, root transforms, and supported
  `preserveAspectRatio` mappings are materialized before font mapping.
- Nested SVG viewports support finite numeric, absolute CSS-unit, and percentage
  `x`, `y`, `width`, and `height`. Percentages resolve against the corresponding
  parent viewport dimension before supported aspect-ratio mapping. `overflow`
  accepts `hidden` or `visible`.
  Container `clip-path` and `opacity` remain attached to the nested coordinate
  system when its viewport is resolved. Other units or an external length
  environment are unrepresentable.
- The original canvas and whitespace are preserved. The canvas is contained
  and centered in a square em.
- Painted geometry is clipped to the mapped viewBox after integer-grid
  quantization by default. `--no-clip-to-viewbox` disables that final clip.

## Static style and paint

The compiler resolves the author cascade before reuse expansion and computed
style inheritance. It supports presentation attributes, inline declarations,
and bounded local `style` elements with static CSS selectors. Specificity,
source order, inline precedence, and `!important` participate in the cascade.
Inherited presentation values and `currentColor` are then materialized onto
geometry.

Dynamic pseudo-classes, pseudo-elements, environment-conditioned stylesheets,
other at-rules, custom properties, and `var()` need an external style
environment and are unrepresentable. Unconditional `@media all` is flattened;
`@media not all` is removed. `@import`, external URLs, event handlers, and
unknown CSS properties are hard failures.

When a document contains `use` or an inherited gradient or pattern template,
selectors whose matches can change across the corresponding SVG shadow-tree
expansion are also unrepresentable. This includes ancestor or sibling
combinators and structural or inherited-context pseudo-classes such as
`:nth-child()`, `:lang()`, and `:dir()`. Rejecting them before cascade
materialization prevents a pre-expansion match from being silently frozen onto
cloned geometry or inherited paint content.

Only after that global hard pass, the compiler removes provable no-ops and
`display:none` render branches, then computes transitive local-resource
reachability. Unsupported definitions that cannot affect rendered output are
discarded; referenced definitions are classified normally. Malformed syntax,
scripts, external references, bad structural target types, cycles, and work
excess remain fatal even inside unreachable content.

The paint model follows alpha coverage:

- Opaque solid paints are lossless regardless of source color. Multiple opaque
  paints merge into the same monochrome coverage.
- Opaque gradients are lossless when the paint server covers its painted target.
  A constant-alpha gradient participates in the same alpha-coverage proof as a
  solid paint. A degenerate linear gradient uses its final stop exactly, while a
  radial gradient whose start and end circles coincide contributes no paint.
- A radial gradient that does not cover its complete painted shape creates a
  deferred affected region. If that region survives, `lossy=convert` uses the
  painted-shape silhouette and records `SVG_GRADIENT_COVERAGE_APPROXIMATED`.
- A missing or wrong-type local paint-server URL uses its explicit fallback
  paint, or `none` when no fallback is present, matching SVG paint semantics.
  Malformed paint URLs and external references remain hard failures.
- Named colors, hexadecimal colors including alpha forms, and CSS Color 4 RGB,
  HSL, HWB, Lab, LCH, Oklab, Oklch, and `color()` forms are normalized. RGB
  gamut is irrelevant to the monochrome target, but alpha is always part of
  the fidelity proof.
- Zero-alpha paint contributes no coverage.
- A partial-alpha region is lossless when later opaque paint completely covers
  it. If fractional coverage survives, `lossy=convert` maps every positive
  alpha to opaque coverage and records `SVG_PARTIAL_ALPHA_APPROXIMATED`.
- An icon configured with `partialAlpha.mode=layers` may instead retain up to
  eight source-order solid-alpha outlines. Exact alpha values are not rounded by
  geometry precision. Each paint-order slot is emitted in a separate font
  family at the icon's unchanged codepoint, and generated Dart stacks those
  layers. The legacy fallback is either the positive-alpha `silhouette` or
  `opaque-only` detail. It records
  `SVG_PARTIAL_ALPHA_APPROXIMATED` or `SVG_PARTIAL_ALPHA_DROPPED` respectively,
  with scoped fallback details and `losslessLayeredOutput=true`.
- Layered mode rejects spatially varying alpha, vector patterns, and group
  compositing that cannot be reduced to ordered solid-alpha outlines. It also
  rejects more than eight required paint layers and an `opaque-only` fallback
  with no fully opaque geometry.
- Spatially varying gradient alpha and declared vector-pattern paint create
  deferred affected regions. If a gradient region survives, `lossy=convert`
  substitutes the painted target shape's opaque silhouette. If a declared
  pattern region survives, it substitutes the target silhouette without
  preserving tile gaps or clipped or empty tile content. The feature-specific
  issue names the exact approximation. Complete later opaque coverage removes
  the affected region, so the conversion remains lossless and issue-free.
- Fractional opacity on a group with multiple painted descendants also creates
  a deferred affected region because normal monochrome glyph outlines cannot
  retain group compositing alpha. It requires `lossy=convert` only where that
  region survives later opaque paint.
- Literal or computed `filter:none` and `mask:none` are exact no-ops. Live
  nontrivial filters and masks remain unrepresentable.

White paint is filled coverage, not an inferred hole. Holes come from path
geometry, winding, clipping, or paint-order coverage. The compiler never guesses
that a source color means subtraction.

The alpha proof tracks opaque coverage and potentially lossy regions with their
feature provenance in source paint order. Every later opaque shape is
subtracted from all pending regions. Permission and typed issues are evaluated
only after this proof, and only for provenance whose region remains.

## Geometry

Losslessly normalized geometry includes:

- paths, rectangles, circles, ellipses, lines, polygons, and polylines
- numeric, absolute CSS-unit, and viewport-resolved percentage geometry and
  stroke lengths; relative-font and runtime-environment expressions remain
  outside the bounded profile
- nested and root transforms, including absolute units, viewport-resolved
  percentage translations, angle units, and constant absolute-length `calc()`
  translations
- nonzero and even-odd fill rules
- filled and stroked outlines, including computed CSS-wide caps, joins, fill
  rules, clips, vector effects, and miter limits; SVG 2 `arcs` and `miter-clip`
  joins are typed profile extensions rather than downstream failures
- finite numeric, `px`, and percentage dash arrays and offsets, including
  inherited dashes and odd dash-list duplication; percentages resolve against
  the normalized diagonal of the current viewport
- local `use` references to supported shapes and groups
- `symbol` instances with numeric or absolute-unit placement and dimensions
  supplied by the use or, when omitted there, by the symbol; viewport mapping,
  local-ID rewriting, bounded expansion, and numeric, percentage, or alignment
  keyword `refX`/`refY` are supported
- inert anchor containers, nonrendering `view` elements, and `switch` elements
  with an unconditional first child
- user-space and `objectBoundingBox` clips, nested clips, visibility inside
  clips, local reuse in clips, and inherited `clip-rule`
- `vector-effect="non-scaling-stroke"`, including target clips materialized
  against the original author geometry before stroke expansion
- start, middle, and end markers on line, quadratic, cubic, arc, and close
  segments; arcs are expanded to cubics with exact endpoint tangents for marker
  orientation; marker viewBoxes, `strokeWidth` and `userSpaceOnUse` units,
  numeric, absolute-unit, percentage, and alignment-keyword reference
  coordinates, degree, gradian, radian, and turn orientation, `auto`,
  `auto-start-reverse`, viewport clipping, and `context-fill`/`context-stroke`
  are supported
- `display:none`, static non-`none` display modes that preserve SVG geometry,
  and `visibility` values `visible`, `hidden`, and `collapse`
- inert RGB/rasterization, pointer, cursor, focus-order, and shape-rendering
  hints under the mathematical vector-alpha fidelity target

Dashed strokes are expanded only after viewport-relative lengths have been
resolved and a conservative pre-stroke work estimate passes. The percentage
basis is `sqrt(width^2 + height^2) / sqrt(2)` for the normalized current
viewport, including nested SVG and marker viewports. `pathLength`-calibrated
painted dashes and relative or environment-dependent units are
unrepresentable. Invalid dash values and an expansion estimate beyond
`maxPathCommands` are hard failures.

Recursively marked marker content, unsupported marker overflow/orientation
environments, and marker/vector-effect combinations outside the bounded profile
are unrepresentable. Invalid marker references, dimensions, or units are hard
failures.

Canonical paths are eventually transformed and rounded to whole font units.
Final union and canvas clipping happen after that step, so sub-font-unit slivers
cannot destabilize PathOps or the emitted outline.

## Bounded text outlining

SVG `text` is lossless only inside an explicitly pinned single-run profile.
Each permitted family is configured by file path and exact SHA-256:

```json
{
  "textFonts": {
    "Project Sans": {
      "file": "fonts/ProjectSans-Regular.ttf",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  }
}
```

Relative file paths resolve from the config file. Validation rejects links,
reparse points, and paths inside the generated output tree. At most 64 faces
may be pinned; each must be a regular file no larger than 64 MiB, and their
aggregate size cannot exceed 256 MiB. Every face is parsed before source
compilation, and its hash is verified during configuration and before worker
use. The family is an explicit build input, not a platform-font lookup. Users
are responsible for the font's outlining and embedding license.

The supported text subset is one horizontal LTR or RTL run in one pinned,
non-color face. `font-style`, `font-stretch`, and `font-variant` must be
`normal`, while `font-weight` may be `normal` or `400`. The subset also supports
language metadata; `text-anchor`; one finite numeric or absolute CSS-unit value
for each of `font-size`, `x`, `y`, `dx`, and `dy`; deterministic selection of
the first configured family in a CSS fallback list; and normal or preserved XML
whitespace. HarfBuzz shapes the run and FontTools supplies the glyph outlines.

Fallback lists with no configured match, implicit platform fonts, missing
glyphs, color-font glyphs, mixed-script or mixed-bidi paragraphs, bidi
embedding/override including `plaintext`, vertical text, alternate face
selection, nested text structures, `textPath`, `tspan`, `textLength`, and
per-character position or rotation lists are unrepresentable. Invisible text
and zero-size runs are removed before font selection. Invalid numeric values,
invalid font binaries, and a pinned font that changes after hash verification
are hard failures. Text shaping, generated glyph paths, bytes, and commands are
charged against the same compiler work limits as other expansion stages.

## Unrepresentable feature handling

`unrepresentable=skip` permits the compiler to omit an icon only after the full
hard-safety preflight has passed. Common examples are:

- live images, audio, video, foreign content, nontrivial filters and masks, and
  animation
- text outside the pinned subset
- environment-conditioned or runtime-dependent CSS
- context-sensitive CSS whose matches can change across a `use` or inherited
  paint-template shadow tree
- conditioned `switch` child selection
- relative length units or runtime viewport dependencies outside the numeric,
  absolute-unit, and bounded percentage profile
- zero-area viewports and silhouettes that intentionally render no glyph
- unsupported combinations of clips, markers, dashes, and vector effects

This classification does not authorize referenced content. A file, network, or
`data:` URL on an otherwise unrepresentable media element is rejected by the
hard external-reference preflight before skip policy is considered.

Every skipped source retains its allocated source ID, Dart name, codepoint,
source digest, direction metadata, and attribution metadata as a retired lock
tombstone. Its geometry digest is omitted. If that source later becomes
representable, it returns to the active set with the same codepoint and name.
Skipped icons are absent from the font and generated Dart provider. A build in
which every source would be skipped fails and publishes nothing.

## Hard safety and resource policy

The following always fail, even with `unrepresentable=skip`:

- DTD and ENTITY declarations
- script elements, event attributes, external URLs, non-fragment hrefs, and
  CSS imports
- malformed XML, geometry, paint, numeric values, or viewports
- unknown elements, attributes, CSS properties, or rendering semantics
- duplicate IDs, missing structural local references, and reference or
  paint-server cycles
- malformed structural reference targets or href ownership, even when another
  feature would otherwise make the icon skippable; local fill and stroke paint
  URLs use the fallback semantics defined above
- invalid config, lock, paths, names, output ownership, font output, or
  publication state
- any configured resource or work limit

Symbolic links, junctions, reparse points, and nested mounts are not followed
for SVG discovery. Configured paths and source IDs are capped at 4096 UTF-8
bytes total and 255 UTF-8 bytes per component. JSON Schema's `maxLength` is only
a code-point precheck; the compiler enforces byte and component limits.

Default limits are 100,000 discovered filesystem entries, 4 MiB per source,
64 MiB per batch, 65,534 icons, 10,000 raw XML elements, 128 nesting levels,
2,048 statically expanded elements, 4 MiB of statically expanded
element/attribute/text work, 100,000 canonical path commands per icon, and
1,000,000 canonical path commands per batch. Pinned fonts add separate
64-face, 64-MiB-per-face, and 256-MiB aggregate limits. CSS matching, including
sibling scans and candidate attribute bytes, local reuse, symbols, text,
markers, clip materialization, and dash expansion are charged against bounded
work before expensive downstream conversion.

Fixed control-plane ceilings also apply: config JSON is capped at 4 MiB, the
lock at 64 MiB, and scanning an established owned output tree at 100,000
entries. Ownership and transaction marker files are capped at 4,096 bytes when
read. The selected private-use range is a separate lifetime allocation limit:
the default U+E000 through U+F8FF range has 6,400 slots shared by active glyphs
and retired tombstones, while each complete supplementary range has 65,534.
Starting later in a range leaves fewer slots.

Raw path token work is capped before PicoSVG runs. Rejected or skipped inputs
retain the full per-icon command ceiling against aggregate path work instead of
refunding potentially expensive failed normalization. Worker count is bounded
from 1 through 61, with automatic selection capped at 8.

## Diagnostics and reports

Every denied feature and hard error has a stable code and normalized source ID.
Config, CLI, batch-budget, and filesystem errors use the relevant config path,
input root, or output path when a narrower SVG source does not exist. Batch
compilation collects diagnostics in deterministic source order within its
resource budget.

Successful JSON CLI payloads use schema version 2 and deterministic build
reports use schema version 3. They include the selected policy, overall
quality, lossless, approximated, and skipped counts, plus typed issue records.
Report v3 also records `codepointsRemaining` and `rangeUtilization` for the
configured allocation window. At or above 80% utilization, build and check
emit `CODEPOINT_RANGE_NEAR_EXHAUSTION` without changing the successful exit
status. This operational warning is separate from fidelity issues.

Reports include one aggregate issue list, attach lossy issues to the emitted
glyph, attach unrepresentable issues to `skippedIcons`, and record every
configured text font by family and SHA-256 without embedding machine-local
font paths. Layered builds also record each auxiliary font and every per-glyph
layer's paint order, exact opacity, family, file, unchanged codepoint, and font
bounds. Report quality is:

- `lossless` when every emitted glyph is lossless and nothing is skipped
- `approximated` when one or more emitted glyphs used an authorized lossy rule
- `partial` when one or more icons were explicitly skipped

The schemas reject directly expressible contradictions among quality, selected
policy, per-glyph conversion, and issues. Relationships that JSON Schema cannot
express by comparing sibling values, such as count fields equaling their
corresponding array lengths, are locked by serializer contract tests.

The lock remains schema version 1 and policy-free. It records ABI allocation,
not the policy used for a particular build.
