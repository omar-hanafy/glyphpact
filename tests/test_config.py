from __future__ import annotations

import json
from pathlib import PurePosixPath

import pytest

import glyphpact.config as config_module
from glyphpact.config import (
    BuildConfig,
    ConversionPolicy,
    LossyPolicy,
    PartialAlphaConfig,
    PartialAlphaFallback,
    PartialAlphaMode,
    TextFont,
    UnrepresentablePolicy,
    load_config,
    parse_codepoint,
)
from glyphpact.errors import IconFontError


@pytest.mark.parametrize(
    "value",
    ["banana", "0xE000tail", " 0xE000", "0xE000 ", -1, 0xD800, 0x110000],
)
def test_invalid_codepoints_are_rejected(value) -> None:
    with pytest.raises(IconFontError):
        parse_codepoint(value)


@pytest.mark.parametrize("value", ["0xE000", 0xF8FF, "0xF0000", 0x10FFFD])
def test_private_use_codepoints_are_accepted(value) -> None:
    assert parse_codepoint(value) > 0


def test_config_paths_are_relative_to_config_file(tmp_path) -> None:
    config_path = tmp_path / "config" / "icon_font.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "input": "../icons",
                "output": "../generated",
                "fontFamily": "Product Icons",
                "className": "ProductIcons",
                "fontPackage": "product_icons",
                "startCodepoint": "0xE800",
                "icons": {
                    "arrows/back.svg": {
                        "name": "back",
                        "matchTextDirection": True,
                        "license": "MIT",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.input_path == (tmp_path / "icons").resolve()
    assert config.output_dir == (tmp_path / "generated").resolve()
    assert config.font_package == "product_icons"
    assert config.icons["arrows/back.svg"].match_text_direction


def test_conversion_policy_defaults_are_strict(tmp_path) -> None:
    config = BuildConfig(
        input_path=tmp_path / "icons",
        output_dir=tmp_path / "generated",
    ).validated()

    assert config.policy == ConversionPolicy(
        lossy=LossyPolicy.ERROR,
        unrepresentable=UnrepresentablePolicy.ERROR,
    )


def test_config_loads_independent_conversion_policy_axes(tmp_path) -> None:
    config_path = tmp_path / "icon_font.json"
    config_path.write_text(
        json.dumps(
            {
                "input": "icons",
                "output": "generated",
                "policy": {
                    "lossy": "convert",
                    "unrepresentable": "skip",
                },
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.policy.lossy is LossyPolicy.CONVERT
    assert config.policy.unrepresentable is UnrepresentablePolicy.SKIP


def test_config_loads_per_icon_layered_alpha_with_explicit_fallback(tmp_path) -> None:
    config_path = tmp_path / "icon_font.json"
    config_path.write_text(
        json.dumps(
            {
                "input": "icons",
                "output": "generated",
                "icons": {
                    "bulk.svg": {
                        "partialAlpha": {
                            "mode": "layers",
                            "fallback": "opaque-only",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.icons["bulk.svg"].partial_alpha == PartialAlphaConfig(
        mode=PartialAlphaMode.LAYERS,
        fallback=PartialAlphaFallback.OPAQUE_ONLY,
    )


@pytest.mark.parametrize(
    ("partial_alpha", "code"),
    [
        ("layers", "CONFIG_TYPE_INVALID"),
        ({"fallback": "silhouette"}, "CONFIG_TYPE_INVALID"),
        ({"mode": "flatten"}, "PARTIAL_ALPHA_MODE_INVALID"),
        (
            {"mode": "layers", "fallback": "drop-everything"},
            "PARTIAL_ALPHA_FALLBACK_INVALID",
        ),
        ({"mode": "layers", "unknown": "value"}, "CONFIG_KEY_UNKNOWN"),
    ],
)
def test_config_rejects_invalid_per_icon_layered_alpha(tmp_path, partial_alpha, code: str) -> None:
    config_path = tmp_path / "icon_font.json"
    config_path.write_text(
        json.dumps(
            {
                "input": "icons",
                "output": "generated",
                "icons": {"bulk.svg": {"partialAlpha": partial_alpha}},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(IconFontError) as caught:
        load_config(config_path)

    assert caught.value.diagnostic.code == code


@pytest.mark.parametrize(
    ("policy", "code"),
    [
        ({"lossy": "silently-convert"}, "CONVERSION_POLICY_INVALID"),
        ({"unrepresentable": "ignore"}, "CONVERSION_POLICY_INVALID"),
        ({"lossy": True}, "CONFIG_TYPE_INVALID"),
        ({"unknown": "skip"}, "CONFIG_KEY_UNKNOWN"),
    ],
)
def test_config_rejects_invalid_conversion_policies(tmp_path, policy, code: str) -> None:
    config_path = tmp_path / "icon_font.json"
    config_path.write_text(
        json.dumps(
            {
                "input": "icons",
                "output": "generated",
                "policy": policy,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(IconFontError) as caught:
        load_config(config_path)

    assert caught.value.diagnostic.code == code


def test_programmatic_config_rejects_invalid_conversion_policy(tmp_path) -> None:
    with pytest.raises(IconFontError) as caught:
        BuildConfig(
            input_path=tmp_path / "icons",
            output_dir=tmp_path / "generated",
            policy=ConversionPolicy(lossy="silent"),  # type: ignore[arg-type]
        ).validated()

    assert caught.value.diagnostic.code == "CONVERSION_POLICY_INVALID"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("font_family", None),
        ("class_name", 7),
        ("font_package", 7),
        ("copyright", 7),
        ("policy", {"lossy": "error"}),
        ("start_codepoint", "0xE000"),
        ("units_per_em", 1000.0),
        ("precision", 3.0),
        ("jobs", 1.5),
        ("clip_to_viewbox", "false"),
        ("padding", True),
        ("max_file_bytes", float("nan")),
        ("max_total_input_bytes", float("nan")),
        ("max_icons", float("nan")),
        ("max_discovery_entries", float("nan")),
        ("max_elements", float("nan")),
        ("max_elements", True),
        ("max_expanded_elements", float("nan")),
        ("max_expanded_bytes", float("nan")),
        ("max_path_commands", float("nan")),
        ("max_total_path_commands", float("nan")),
    ],
)
def test_programmatic_config_rejects_wrong_scalar_types(
    tmp_path, field: str, value: object
) -> None:
    with pytest.raises(IconFontError) as caught:
        BuildConfig(
            input_path=tmp_path / "icons",
            output_dir=tmp_path / "generated",
            **{field: value},
        ).validated()

    assert caught.value.diagnostic.code == "CONFIG_TYPE_INVALID"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_programmatic_config_rejects_nonfinite_padding(tmp_path, value: float) -> None:
    with pytest.raises(IconFontError) as caught:
        BuildConfig(
            input_path=tmp_path / "icons",
            output_dir=tmp_path / "generated",
            padding=value,
        ).validated()

    assert caught.value.diagnostic.code == "PADDING_INVALID"


def test_empty_programmatic_class_name_is_rejected_instead_of_derived(tmp_path) -> None:
    with pytest.raises(IconFontError) as caught:
        BuildConfig(
            input_path=tmp_path / "icons",
            output_dir=tmp_path / "generated",
            class_name="",
        ).validated()

    assert caught.value.diagnostic.code == "CLASS_NAME_INVALID"


def test_unsafe_output_artifact_path_is_rejected(tmp_path) -> None:
    with pytest.raises(IconFontError, match="OUTPUT_PATH_UNSAFE"):
        BuildConfig(
            input_path=tmp_path,
            output_dir=tmp_path / "out",
            font_file=PurePosixPath("../escape.otf"),
        ).validated()


def test_codepoint_parser_rejects_pathological_decimal_length() -> None:
    with pytest.raises(IconFontError) as caught:
        parse_codepoint("1" * 5_000)
    assert caught.value.diagnostic.code == "CODEPOINT_INVALID"


def test_config_rejects_overlong_filesystem_component_without_internal_error(tmp_path) -> None:
    with pytest.raises(IconFontError) as caught:
        BuildConfig(
            input_path=tmp_path / ("i" * 10_000),
            output_dir=tmp_path / "output",
        ).validated()
    assert caught.value.diagnostic.code == "INPUT_PATH_INVALID"


def test_config_rejects_more_than_64_pinned_text_fonts(
    tmp_path, pinned_text_font: tuple[str, TextFont]
) -> None:
    _, text_font = pinned_text_font

    with pytest.raises(IconFontError) as caught:
        BuildConfig(
            input_path=tmp_path / "icons",
            output_dir=tmp_path / "generated",
            text_fonts={f"Family {index}": text_font for index in range(65)},
        ).validated()

    assert caught.value.diagnostic.code == "TEXT_FONT_LIMIT"


def test_config_enforces_aggregate_pinned_text_font_byte_limit(
    tmp_path, monkeypatch, pinned_text_font: tuple[str, TextFont]
) -> None:
    _, text_font = pinned_text_font
    monkeypatch.setattr(
        config_module,
        "MAX_TOTAL_TEXT_FONT_BYTES",
        text_font.path.stat().st_size,
    )

    with pytest.raises(IconFontError) as caught:
        BuildConfig(
            input_path=tmp_path / "icons",
            output_dir=tmp_path / "generated",
            text_fonts={"First Family": text_font, "Second Family": text_font},
        ).validated()

    assert caught.value.diagnostic.code == "TEXT_FONT_LIMIT"


@pytest.mark.parametrize("font_location", ["equal", "descendant"])
def test_config_rejects_pinned_text_fonts_in_generated_output(
    tmp_path,
    pinned_text_font: tuple[str, TextFont],
    font_location: str,
) -> None:
    family, source_font = pinned_text_font
    if font_location == "equal":
        output = source_font.path
        configured_font = source_font
    else:
        output = tmp_path / "generated"
        output.mkdir()
        font_path = output / "source-font.ttf"
        font_path.write_bytes(source_font.path.read_bytes())
        configured_font = TextFont(path=font_path, sha256=source_font.sha256)

    with pytest.raises(IconFontError) as caught:
        BuildConfig(
            input_path=tmp_path / "icons",
            output_dir=output,
            text_fonts={family: configured_font},
        ).validated()

    assert caught.value.diagnostic.code == "TEXT_FONT_OUTPUT_CONFLICT"
