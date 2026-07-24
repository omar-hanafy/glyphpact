"""Stable product identity shared by generated artifacts and public interfaces."""

PRODUCT_NAME = "GlyphPact"
PACKAGE_NAME = "glyphpact"
CLI_NAME = "glyphpact"
GENERATOR_ID = "glyphpact"
REPOSITORY_URL = "https://github.com/omar-hanafy/glyphpact"

OUTPUT_MARKER = ".glyphpact.json"
TRANSACTION_MARKER = ".glyphpact-transaction.json"
OUTPUT_LOCK_SUFFIX = ".glyphpact.lock"
DEBUG_ENVIRONMENT_VARIABLE = "GLYPHPACT_DEBUG"

# GlyphPact was developed privately under this identifier. Accept it only when
# reading existing state so pre-release users can migrate without losing their
# codepoint ABI. Every newly generated artifact uses GENERATOR_ID.
LEGACY_IDENTITIES = (
    (
        "svg-to-flutter-icon",
        ".svg-to-flutter-icon.json",
        ".svg-to-flutter-icon-transaction.json",
    ),
)
LEGACY_GENERATOR_IDS = frozenset(identity[0] for identity in LEGACY_IDENTITIES)
ACCEPTED_GENERATOR_IDS = frozenset({GENERATOR_ID, *LEGACY_GENERATOR_IDS})
LEGACY_OUTPUT_MARKERS = tuple(identity[1] for identity in LEGACY_IDENTITIES)
LEGACY_TRANSACTION_MARKERS = tuple(identity[2] for identity in LEGACY_IDENTITIES)
OUTPUT_MARKER_IDENTITIES = (
    (OUTPUT_MARKER, GENERATOR_ID),
    *((identity[1], identity[0]) for identity in LEGACY_IDENTITIES),
)
TRANSACTION_MARKER_IDENTITIES = (
    (TRANSACTION_MARKER, GENERATOR_ID),
    *((identity[2], identity[0]) for identity in LEGACY_IDENTITIES),
)
