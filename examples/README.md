# Examples

Every SVG in this directory was authored for GlyphPact and is available under
the repository's MIT license.

Run the strict opaque example:

```bash
glyphpact --config examples/icon_font.json
```

It compiles two SVGs into `examples/generated/app_icons`.

Run the solid partial-alpha example:

```bash
glyphpact --config examples/layered_icon_font.json
```

It emits a normal single-glyph fallback plus auxiliary paint-order fonts into
`examples/generated/layered_icons`.

The generated directories are disposable. Application projects should commit
their generated output because the lockfile is part of the icon API.
