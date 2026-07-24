# Fidelity and failure policy

GlyphPact separates SVG outcomes so scale never turns visual decisions into
silent guesses.

## Lossless

Accept deterministic normalization when final geometry and alpha coverage are
equivalent. Exporter noise, path normalization, and smaller font data are not
visual losses.

Ordered solid-alpha artwork can remain lossless through per-icon layer fonts.
Compare the generated layered widget to the source. Treat the normal IconData
constant as the separately reported compatibility fallback.

## Approximated

Keep `lossy="error"` until the user accepts the exact difference. Before
setting `lossy="convert"`:

1. name every affected source
2. quote or summarize its typed diagnostic
3. explain what visual information survives and what changes
4. limit the opt-in to the requested build
5. verify the rendered approximation after compilation

Do not infer approval from a request to "make it work."

## Unrepresentable

A monochrome IconData font cannot preserve every SVG effect. Keep
`unrepresentable="error"` unless the user accepts omission. When skipping is
approved, list every omitted source and preserve its lock reservation.

Offer runtime SVG rendering when the product requires unsupported color,
animation, linked images, or effects that should not be flattened.

## Hard failures

Malformed XML, unsafe references, unsupported unknown constructs, collisions,
and resource-limit violations remain fatal. Neither conversion nor skipping
suppresses them.

Repair without asking only when intent is objective:

- correct project font-family or asset registration
- correct provider imports or `fontPackage`
- infer a missing view box from valid numeric width and height
- remove exporter metadata that cannot affect rendering
- fix a compiler defect for valid artwork inside the documented profile

Do not invent geometry, redraw malformed paths, guess an external image,
substitute an unknown text font, or flatten a visual effect without permission.

## Duplicate and naming policy

Report exact duplicate digests but retain them by default. Separate public names
may intentionally share one shape.

Resolve case-insensitive path collisions and Dart identifier collisions before
publication. Keep rename evidence and the existing lock so content-verified
renames preserve codepoints.

## Visual comparison

Compare:

- outer silhouette and internal holes
- winding and fill rules
- stroke widths, caps, joins, and miter behavior
- transforms, reuse, clipping, and nested viewports
- alignment, view-box padding, baseline, and optical scale
- RTL direction and `matchTextDirection`
- opacity and paint order for layered output

Inspect a realistic icon size and a large diagnostic size. Allow normal
antialiasing differences only at contour edges.
