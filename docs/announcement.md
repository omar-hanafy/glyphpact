# Announcing GlyphPact 1.0.0

Released July 25, 2026.

I built GlyphPact because generating a Flutter icon font should not depend on
uploading artwork to a website or hoping that unsupported SVG features were
ignored safely.

**GlyphPact is the deterministic SVG-to-Flutter icon compiler.**

It recursively compiles SVG packs into validated OpenType/CFF fonts and const,
tree-shakeable Dart `IconData` providers. A checked-in lock keeps codepoints
stable as the pack changes. Every build also produces a machine-readable report
and an attribution file.

The important part is the failure model. GlyphPact converts losslessly by
default. A known deterministic approximation requires explicit permission, and
skipping an icon requires a separate permission. Malformed input, external
references, unsafe content, unknown semantics, and exhausted work limits still
fail the build. The last valid generated output stays intact.

It handles nested icon packs, common SVG geometry, transforms, strokes, clips,
markers, static CSS, gradients, local reuse, symbols, and bounded text through
explicitly pinned fonts. Solid partial-alpha artwork can use generated
paint-order layer fonts instead of silently flattening alpha.

GlyphPact also makes the scale boundary explicit. One OpenType font has a
practical ceiling of 65,534 glyphs. Large catalogs can use a supplementary
private use range or be split into multiple independently versioned fonts.

For agent-assisted work, the same repository is a Claude Code and Codex
marketplace. Its optional plugin bundles the exact 1.0.0 wheel, exposes local
MCP tools for auditing, building, checking, and paging reports, and includes a
skill for safe Flutter integration and rendered verification. No separate MCP
configuration is needed.

Install it with uv:

```bash
uv tool install git+https://github.com/omar-hanafy/glyphpact.git@v1.0.0
```

Then compile:

```bash
glyphpact assets/icons \
  --output lib/generated/app_icons \
  --name AppIcons
```

Or install the agent plugin:

```bash
claude plugin marketplace add omar-hanafy/glyphpact
claude plugin install glyphpact@glyphpact

codex plugin marketplace add omar-hanafy/glyphpact
codex plugin add glyphpact@glyphpact
```

The project is MIT licensed:
[github.com/omar-hanafy/glyphpact](https://github.com/omar-hanafy/glyphpact)
