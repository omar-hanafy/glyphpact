# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | Yes |
| Earlier | No public release |

Security fixes are applied to the latest 1.x release.

## Reporting a vulnerability

Use
[GitHub private vulnerability reporting](https://github.com/omar-hanafy/glyphpact/security/advisories/new).
Do not open a public issue for an undisclosed vulnerability.

Include:

- the affected GlyphPact version and platform
- a minimal input or reproduction
- the diagnostic output and exit code
- whether source data or an output directory changed

Do not attach proprietary artwork unless you have permission to share it.

XML entity expansion, external resource access, path traversal, output
ownership bypass, lockfile ABI corruption, font parser failures, and resource
exhaustion are treated as security-sensitive.
