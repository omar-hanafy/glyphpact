"""GlyphPact, a deterministic SVG to Flutter icon font compiler."""

from .builder import BuildResult, build
from .config import (
    BuildConfig,
    ConversionPolicy,
    LossyPolicy,
    TextFont,
    UnrepresentablePolicy,
)
from .identity import PRODUCT_NAME
from .version import __version__

__all__ = [
    "PRODUCT_NAME",
    "BuildConfig",
    "BuildResult",
    "ConversionPolicy",
    "LossyPolicy",
    "TextFont",
    "UnrepresentablePolicy",
    "__version__",
    "build",
]
