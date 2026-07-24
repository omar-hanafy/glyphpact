# Benchmarking GlyphPact

SVG file count alone is not a useful performance measure. Paths, CSS, clips,
markers, text, and expanded geometry can make two equally sized packs require
very different work.

GlyphPact therefore ships a local runner instead of publishing a number from a
private corpus.

## Run a benchmark

From a source checkout:

```bash
python examples/benchmark.py assets/icons \
  --command "uv run glyphpact" \
  --jobs 1 8 \
  --runs 3
```

Against an installed command:

```bash
python examples/benchmark.py assets/icons --jobs 1 8 --runs 3
```

The runner creates a fresh temporary output for every measurement. It reports
each duration, the median for each worker count, the number of input SVGs, total
input bytes, and a digest of the complete generated artifact tree. Matching
digests prove that the measured worker counts produced the same bytes.

The runner does not report peak memory. Use an operating-system profiler when
memory is part of the question, and name that tool in published results.

## Report enough context

Include these fields with any shared result:

- exact GlyphPact version or commit
- operating system, architecture, CPU, and available memory
- Python version
- whether the storage was local or network-backed
- SVG count and total input bytes
- strict or permissive policy
- worker counts and run count
- whether runs were cold, warm, or mixed
- emitted, approximated, and skipped counts from the build report
- artifact digest agreement across worker counts

Do not compare results when the source pack, lockfile, compiler version, config,
or hardware changed.

## Interpret the ceiling

GlyphPact supports up to 65,534 icons in one build, subject to configured input
and work limits. The same 65,534 value is the practical OpenType glyph ceiling
for one font. For catalogs larger than one font, benchmark and version each
partition independently.
