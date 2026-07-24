from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import cssselect2
import tinycss2
from lxml import etree

from .errors import IconFontError, SvgFeatureClass, SvgFeatureError

_DYNAMIC_PSEUDO_CLASSES = frozenset(
    {
        ":active",
        ":any-link",
        ":checked",
        ":disabled",
        ":enabled",
        ":focus",
        ":focus-visible",
        ":focus-within",
        ":hover",
        ":indeterminate",
        ":link",
        ":local-link",
        ":target",
        ":target-within",
        ":user-invalid",
        ":user-valid",
        ":valid",
        ":invalid",
        ":visited",
    }
)

_USE_SHADOW_SENSITIVE_PSEUDO_CLASSES = frozenset(
    {
        "dir",
        "empty",
        "first-child",
        "first-of-type",
        "has",
        "lang",
        "last-child",
        "last-of-type",
        "nth-child",
        "nth-last-child",
        "nth-last-of-type",
        "nth-of-type",
        "only-child",
        "only-of-type",
        "root",
        "scope",
    }
)

_IGNORED_STATIC_PROPERTIES = frozenset(
    {
        "color-rendering",
        "cursor",
        "image-rendering",
        "pointer-events",
        "shape-rendering",
    }
)

_MAX_CSS_NESTING = 32


@dataclass(frozen=True)
class _Declaration:
    name: str
    value: str
    important: bool
    order: int


def _serialized(tokens: Any) -> str:
    return cast(str, tinycss2.serialize(tokens).strip())


def _consider(
    winners: dict[str, tuple[tuple[int, tuple[int, int, int, int], int], str]],
    declaration: _Declaration,
    specificity: tuple[int, int, int, int],
) -> None:
    weight = (int(declaration.important), specificity, declaration.order)
    previous = winners.get(declaration.name)
    if previous is None or weight >= previous[0]:
        winners[declaration.name] = (weight, declaration.value)


def _external_url_in_css(tokens: Any) -> str | None:
    stack = list(tokens)
    while stack:
        token = stack.pop()
        token_type = getattr(token, "type", "")
        if token_type == "url":
            value = str(token.value).strip()
            if not value.startswith("#"):
                return value
        if token_type == "function":
            if token.lower_name == "url":
                value = _serialized(token.arguments).strip(" \t\r\n\"'")
                if not value.startswith("#"):
                    return value
            stack.extend(token.arguments)
        content = getattr(token, "content", None)
        if content:
            stack.extend(content)
    return None


def _local_urls_in_css(tokens: Any) -> tuple[str, ...]:
    result: list[str] = []
    stack = list(tokens)
    while stack:
        token = stack.pop()
        token_type = getattr(token, "type", "")
        if token_type == "url":
            value = str(token.value).strip()
            if value.startswith("#"):
                result.append(value[1:])
        if token_type == "function":
            if token.lower_name == "url":
                value = _serialized(token.arguments).strip(" \t\r\n\"'")
                if value.startswith("#"):
                    result.append(value[1:])
            stack.extend(token.arguments)
        content = getattr(token, "content", None)
        if content:
            stack.extend(content)
    return tuple(result)


def _reject_component_errors(tokens: Any, source_id: str) -> None:
    stack = list(tokens)
    while stack:
        token = stack.pop()
        if getattr(token, "type", "") == "error":
            raise IconFontError(
                "SVG_CSS_INVALID",
                str(getattr(token, "message", "Malformed CSS token.")),
                source=source_id,
            )
        if getattr(token, "type", "") == "function":
            stack.extend(token.arguments)
        content = getattr(token, "content", None)
        if content:
            stack.extend(content)


def _declarations(
    content: Any,
    *,
    source_id: str,
    supported_properties: frozenset[str],
    start_order: int,
) -> tuple[tuple[_Declaration, ...], int]:
    result: list[_Declaration] = []
    order = start_order
    for item in tinycss2.parse_declaration_list(content, skip_comments=True, skip_whitespace=True):
        if item.type == "error":
            raise IconFontError(
                "SVG_CSS_INVALID",
                str(item.message),
                source=source_id,
            )
        if item.type != "declaration":
            raise IconFontError(
                "SVG_CSS_INVALID",
                "Only CSS declarations are allowed in a declaration block.",
                source=source_id,
            )
        name = item.lower_name
        _reject_component_errors(item.value, source_id)
        external = _external_url_in_css(item.value)
        if external is not None:
            raise IconFontError(
                "SVG_EXTERNAL_REFERENCE",
                f"External CSS reference {external!r} is forbidden.",
                source=source_id,
            )
        value = _serialized(item.value)
        if not value:
            continue
        if name == "-inkscape-stroke":
            if value.casefold() != "none":
                raise IconFontError(
                    "SVG_CSS_PROPERTY_UNKNOWN",
                    "Only the no-op '-inkscape-stroke:none' editor hint is accepted.",
                    source=source_id,
                )
            # This is an Inkscape-only editor hint, not a legal XML presentation
            # attribute. Consume the inert value here instead of materializing it.
            continue
        if name.startswith("--") or "var(" in value.casefold():
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "css-custom-properties",
                "SVG_CSS_ENVIRONMENT_UNREPRESENTABLE",
                "CSS custom properties require a wider computed-style environment.",
                source=source_id,
            )
        if name in _IGNORED_STATIC_PROPERTIES:
            continue
        if name not in supported_properties:
            raise IconFontError(
                "SVG_CSS_PROPERTY_UNKNOWN",
                f"CSS property {name!r} has unknown rendering semantics.",
                source=source_id,
            )
        result.append(
            _Declaration(
                name=name,
                value=value,
                important=bool(item.important),
                order=order,
            )
        )
        order += 1
    return tuple(result), order


def _hard_validate_declarations(
    content: Any,
    *,
    source_id: str,
    supported_properties: frozenset[str],
    validate_value: Callable[[str, str], None],
) -> None:
    for item in tinycss2.parse_declaration_list(content, skip_comments=True, skip_whitespace=True):
        if item.type == "error":
            raise IconFontError(
                "SVG_CSS_INVALID",
                str(item.message),
                source=source_id,
            )
        if item.type != "declaration":
            raise IconFontError(
                "SVG_CSS_INVALID",
                "Only CSS declarations are allowed in a declaration block.",
                source=source_id,
            )
        external = _external_url_in_css(item.value)
        _reject_component_errors(item.value, source_id)
        if external is not None:
            raise IconFontError(
                "SVG_EXTERNAL_REFERENCE",
                f"External CSS reference {external!r} is forbidden.",
                source=source_id,
            )
        name = item.lower_name
        value = _serialized(item.value)
        if name == "-inkscape-stroke" and value.casefold() != "none":
            raise IconFontError(
                "SVG_CSS_PROPERTY_UNKNOWN",
                "Only the no-op '-inkscape-stroke:none' editor hint is accepted.",
                source=source_id,
            )
        if (
            name not in supported_properties
            and name not in _IGNORED_STATIC_PROPERTIES
            and not name.startswith("--")
        ):
            raise IconFontError(
                "SVG_CSS_PROPERTY_UNKNOWN",
                f"CSS property {name!r} has unknown rendering semantics.",
                source=source_id,
            )
        if name in supported_properties:
            validate_value(name, value)


def _dynamic_selector(tokens: Any) -> bool:
    dynamic_names = {pseudo[1:] for pseudo in _DYNAMIC_PSEUDO_CLASSES}
    sequence = tuple(tokens)
    for index, token in enumerate(sequence):
        if (
            getattr(token, "type", "") == "literal"
            and getattr(token, "value", None) == ":"
            and index + 1 < len(sequence)
            and getattr(sequence[index + 1], "type", "") in {"ident", "function"}
            and str(
                getattr(
                    sequence[index + 1],
                    "value",
                    getattr(sequence[index + 1], "lower_name", ""),
                )
            ).casefold()
            in dynamic_names
        ):
            return True
        token_type = getattr(token, "type", "")
        if token_type == "function" and _dynamic_selector(token.arguments):
            return True
        if token_type in {"() block", "{} block"} and _dynamic_selector(token.content):
            return True
        # Attribute-selector blocks are data. A string such as
        # [data-state=":hover"] must not become a dynamic selector.
    return False


def _css_token_work(tokens: Any) -> int:
    work = 0
    stack = list(tokens)
    while stack:
        token = stack.pop()
        work += 1
        if getattr(token, "type", "") == "function":
            stack.extend(token.arguments)
        content = getattr(token, "content", None)
        if content:
            stack.extend(content)
    return work


def _validate_css_nesting(text: str, source_id: str) -> None:
    stack: list[str] = []
    closing = {"(": ")", "[": "]", "{": "}"}
    index = 0
    quote: str | None = None
    while index < len(text):
        character = text[index]
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                return
            index = end + 2
            continue
        if character in {"'", '"'}:
            quote = character
        elif character in closing:
            stack.append(character)
            if len(stack) > _MAX_CSS_NESTING:
                raise IconFontError(
                    "SVG_CSS_WORK_LIMIT",
                    f"CSS nesting exceeds the bounded depth of {_MAX_CSS_NESTING}.",
                    source=source_id,
                )
        elif character in closing.values() and stack and closing[stack[-1]] == character:
            stack.pop()
        index += 1


def _use_shadow_sensitive_selector(tokens: Any) -> bool:
    sequence = tuple(tokens)
    for index, token in enumerate(sequence):
        token_type = getattr(token, "type", "")
        if token_type == "literal" and getattr(token, "value", None) in {">", "+", "~"}:
            return True
        if token_type == "whitespace":
            previous = next(
                (
                    candidate
                    for candidate in reversed(sequence[:index])
                    if getattr(candidate, "type", "") != "whitespace"
                ),
                None,
            )
            following = next(
                (
                    candidate
                    for candidate in sequence[index + 1 :]
                    if getattr(candidate, "type", "") != "whitespace"
                ),
                None,
            )
            if (
                previous is not None
                and following is not None
                and getattr(previous, "value", None) != ","
                and getattr(following, "value", None) != ","
            ):
                return True
        if (
            token_type == "literal"
            and getattr(token, "value", None) == ":"
            and index + 1 < len(sequence)
            and getattr(sequence[index + 1], "type", "") in {"ident", "function"}
            and str(
                getattr(
                    sequence[index + 1],
                    "value",
                    getattr(sequence[index + 1], "lower_name", ""),
                )
            ).casefold()
            in _USE_SHADOW_SENSITIVE_PSEUDO_CLASSES
        ):
            return True
        if token_type == "function" and _use_shadow_sensitive_selector(token.arguments):
            return True
        if token_type in {"() block", "{} block"} and _use_shadow_sensitive_selector(token.content):
            return True
    return False


def _selector_has_pseudo_class(tokens: Any, names: frozenset[str]) -> bool:
    sequence = tuple(tokens)
    for index, token in enumerate(sequence):
        token_type = getattr(token, "type", "")
        if (
            token_type == "literal"
            and getattr(token, "value", None) == ":"
            and index + 1 < len(sequence)
            and getattr(sequence[index + 1], "type", "") in {"ident", "function"}
            and str(
                getattr(
                    sequence[index + 1],
                    "value",
                    getattr(sequence[index + 1], "lower_name", ""),
                )
            ).casefold()
            in names
        ):
            return True
        if token_type == "function" and _selector_has_pseudo_class(token.arguments, names):
            return True
        if token_type in {"() block", "{} block"} and _selector_has_pseudo_class(
            token.content, names
        ):
            return True
    return False


def _selector_tokens_for_hard_validation(tokens: Any, source_id: str) -> Any:
    """Replace valid unsupported pseudos only while checking the remaining grammar."""

    cloned = copy.deepcopy(tokens)

    def rewrite(sequence: Any) -> None:
        items = tuple(sequence)
        for index, token in enumerate(items):
            token_type = getattr(token, "type", "")
            if (
                token_type == "literal"
                and getattr(token, "value", None) == ":"
                and index + 1 < len(items)
                and getattr(items[index + 1], "type", "") == "function"
                and str(getattr(items[index + 1], "lower_name", "")).casefold() == "dir"
            ):
                function = items[index + 1]
                arguments = tuple(
                    argument
                    for argument in function.arguments
                    if getattr(argument, "type", "") not in {"comment", "whitespace"}
                )
                if (
                    len(arguments) != 1
                    or getattr(arguments[0], "type", "") != "ident"
                    or str(getattr(arguments[0], "value", "")).casefold() not in {"ltr", "rtl"}
                ):
                    raise IconFontError(
                        "SVG_CSS_SELECTOR_INVALID",
                        ":dir() requires exactly one ltr or rtl keyword.",
                        source=source_id,
                    )
                # cssselect2 does not implement the valid :dir() pseudo-class.
                # Substitute its equally shaped supported :lang() form in the
                # cloned token tree so every other selector component still gets
                # full parser/compiler validation before policy classification.
                function.name = "lang"
                function.lower_name = "lang"
            if token_type == "function":
                rewrite(token.arguments)
            elif token_type in {"() block", "{} block"}:
                rewrite(token.content)

    rewrite(cloned)
    return cloned


def _token_type_count(tokens: Any, wanted: str) -> int:
    count = 0
    stack = list(tokens)
    while stack:
        token = stack.pop()
        if getattr(token, "type", "") == wanted:
            count += 1
        if getattr(token, "type", "") == "function":
            stack.extend(token.arguments)
        content = getattr(token, "content", None)
        if content:
            stack.extend(content)
    return count


def materialize_css(
    root: etree._Element,
    *,
    source_id: str,
    supported_properties: frozenset[str],
    max_rules: int,
    max_work: int,
    hard_validate_value: Callable[[str, str], None],
) -> None:
    """Materialize a bounded, static author cascade as presentation attributes."""

    matcher = cssselect2.Matcher()
    order = 0
    selector_count = 0
    style_elements = tuple(
        element
        for element in root.iter()
        if isinstance(element.tag, str) and etree.QName(element).localname == "style"
    )
    has_use = any(
        isinstance(element.tag, str) and etree.QName(element).localname == "use"
        for element in root.iter()
    )
    has_paint_template = any(
        isinstance(element.tag, str)
        and etree.QName(element).localname in {"linearGradient", "pattern", "radialGradient"}
        and any(
            etree.QName(name).localname.casefold() == "href" and value.startswith("#")
            for name, value in element.attrib.items()
        )
        for element in root.iter()
    )
    parsed_styles: list[tuple[etree._Element, tuple[Any, ...]]] = []
    local_references: set[str] = set()
    hard_selector_count = 0
    selector_complexity = 0
    relational_complexity = 0
    sibling_scan_complexity = 0
    attribute_selector_count = 0

    def hard_scan_qualified(rule: Any) -> None:
        nonlocal hard_selector_count
        nonlocal selector_complexity
        nonlocal relational_complexity
        nonlocal sibling_scan_complexity
        nonlocal attribute_selector_count

        selector_increment = 1 + sum(
            getattr(token, "type", "") == "literal" and getattr(token, "value", None) == ","
            for token in rule.prelude
        )
        hard_selector_count += selector_increment
        if hard_selector_count > max_rules:
            raise IconFontError(
                "SVG_CSS_WORK_LIMIT",
                "Stylesheet selector count exceeds the configured expansion limit.",
                source=source_id,
            )
        rule_complexity = _css_token_work(rule.prelude)
        selector_complexity += rule_complexity
        selector_text = _serialized(rule.prelude).casefold()
        if "\\" in selector_text:
            raise IconFontError(
                "SVG_CSS_SELECTOR_INVALID",
                "CSS selector escapes are outside the bounded static profile.",
                source=source_id,
            )
        if ":has(" in selector_text:
            relational_complexity += rule_complexity
        if "~" in selector_text or any(
            pseudo in selector_text
            for pseudo in (
                ":first-child",
                ":first-of-type",
                ":last-child",
                ":last-of-type",
                ":nth-child",
                ":nth-last-child",
                ":nth-last-of-type",
                ":nth-of-type",
                ":only-child",
                ":only-of-type",
            )
        ):
            sibling_scan_complexity += rule_complexity
        attribute_selector_count += _token_type_count(rule.prelude, "[] block")
        if selector_complexity > max_work:
            raise IconFontError(
                "SVG_CSS_WORK_LIMIT",
                "Stylesheet selector syntax exceeds the configured CSS work limit.",
                source=source_id,
            )
        try:
            cssselect2.compile_selector_list(
                _selector_tokens_for_hard_validation(rule.prelude, source_id)
            )
        except (RecursionError, SyntaxError) as error:
            raise IconFontError(
                "SVG_CSS_WORK_LIMIT",
                "CSS selector compilation exceeds the bounded static profile.",
                source=source_id,
            ) from error
        except cssselect2.SelectorError as error:
            raise IconFontError(
                "SVG_CSS_SELECTOR_INVALID",
                str(error),
                source=source_id,
            ) from error
        _hard_validate_declarations(
            rule.content,
            source_id=source_id,
            supported_properties=supported_properties,
            validate_value=hard_validate_value,
        )

    def hard_scan_nested(rules: tuple[Any, ...]) -> None:
        pending = list(reversed(rules))
        while pending:
            nested_rule = pending.pop()
            if nested_rule.type == "error":
                raise IconFontError(
                    "SVG_CSS_INVALID",
                    str(nested_rule.message),
                    source=source_id,
                )
            prelude = getattr(nested_rule, "prelude", None) or ()
            content = getattr(nested_rule, "content", None) or ()
            _reject_component_errors((*prelude, *content), source_id)
            local_references.update(_local_urls_in_css((*prelude, *content)))
            external = _external_url_in_css((*prelude, *content))
            if external is not None or (
                nested_rule.type == "at-rule" and nested_rule.lower_at_keyword == "import"
            ):
                raise IconFontError(
                    "SVG_EXTERNAL_REFERENCE",
                    (
                        f"External CSS reference {external!r} is forbidden."
                        if external is not None
                        else "CSS @import is forbidden."
                    ),
                    source=source_id,
                )
            if nested_rule.type == "qualified-rule":
                hard_scan_qualified(nested_rule)
            elif (
                nested_rule.type == "at-rule"
                and nested_rule.content is not None
                and nested_rule.lower_at_keyword
                in {"container", "document", "layer", "media", "scope", "supports"}
            ):
                descendants = tuple(
                    tinycss2.parse_rule_list(
                        nested_rule.content,
                        skip_comments=True,
                        skip_whitespace=True,
                    )
                )
                pending.extend(reversed(descendants))

    for style in style_elements:
        content_type = style.get("type", "text/css").strip().casefold()
        if content_type not in {"", "text/css"}:
            continue
        style_text = style.text or ""
        _validate_css_nesting(style_text, source_id)
        try:
            stylesheet = tuple(
                tinycss2.parse_stylesheet(style_text, skip_comments=True, skip_whitespace=True)
            )
        except RecursionError as error:
            raise IconFontError(
                "SVG_CSS_WORK_LIMIT",
                "CSS parsing exceeds the bounded static profile.",
                source=source_id,
            ) from error
        parsed_styles.append((style, stylesheet))
        for rule in stylesheet:
            if rule.type == "error":
                raise IconFontError(
                    "SVG_CSS_INVALID",
                    str(rule.message),
                    source=source_id,
                )
            prelude = getattr(rule, "prelude", None) or ()
            content = getattr(rule, "content", None) or ()
            _reject_component_errors((*prelude, *content), source_id)
            local_references.update(_local_urls_in_css((*prelude, *content)))
            external = _external_url_in_css((*prelude, *content))
            if external is not None or (
                rule.type == "at-rule" and rule.lower_at_keyword == "import"
            ):
                raise IconFontError(
                    "SVG_EXTERNAL_REFERENCE",
                    (
                        f"External CSS reference {external!r} is forbidden."
                        if external is not None
                        else "CSS @import is forbidden."
                    ),
                    source=source_id,
                )
            if rule.type == "qualified-rule":
                hard_scan_qualified(rule)
            elif (
                rule.type == "at-rule"
                and rule.content is not None
                and rule.lower_at_keyword
                in {"container", "document", "layer", "media", "scope", "supports"}
            ):
                hard_scan_nested(
                    tuple(
                        tinycss2.parse_rule_list(
                            rule.content,
                            skip_comments=True,
                            skip_whitespace=True,
                        )
                    )
                )

    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        inline = element.attrib.get("style")
        if inline is not None:
            _validate_css_nesting(inline, source_id)
            try:
                inline_tokens = tinycss2.parse_component_value_list(inline)
            except RecursionError as error:
                raise IconFontError(
                    "SVG_CSS_WORK_LIMIT",
                    "Inline CSS parsing exceeds the bounded static profile.",
                    source=source_id,
                ) from error
            local_references.update(_local_urls_in_css(inline_tokens))
            _hard_validate_declarations(
                inline,
                source_id=source_id,
                supported_properties=supported_properties,
                validate_value=hard_validate_value,
            )

    identifiers = {
        identifier
        for element in root.iter()
        if isinstance(element.tag, str)
        if (identifier := element.get("id")) is not None
    }
    missing = sorted(local_references - identifiers)
    if missing:
        raise IconFontError(
            "SVG_REFERENCE_NOT_FOUND",
            "Local CSS reference target(s) do not exist: "
            + ", ".join(repr(item) for item in missing)
            + ".",
            source=source_id,
        )

    element_count = sum(1 for element in root.iter() if isinstance(element.tag, str))
    hard_match_work = element_count * max(1, selector_complexity)
    hard_match_work += relational_complexity * element_count * element_count
    hard_match_work += sibling_scan_complexity * element_count * element_count
    attribute_bytes = sum(
        len(name.encode("utf-8")) + len(value.encode("utf-8"))
        for element in root.iter()
        if isinstance(element.tag, str)
        for name, value in element.attrib.items()
    )
    hard_match_work += attribute_selector_count * attribute_bytes
    if hard_match_work > max_work:
        raise IconFontError(
            "SVG_CSS_WORK_LIMIT",
            "Stylesheet matching exceeds the configured CSS work limit.",
            source=source_id,
        )

    def static_qualified_rules(stylesheet: tuple[Any, ...]) -> tuple[Any, ...]:
        result: list[Any] = []
        pending = list(reversed(stylesheet))
        while pending:
            rule = pending.pop()
            if rule.type != "at-rule":
                result.append(rule)
                continue
            if rule.lower_at_keyword == "import":
                raise IconFontError(
                    "SVG_EXTERNAL_REFERENCE",
                    "CSS @import is forbidden.",
                    source=source_id,
                )
            condition = _serialized(rule.prelude).casefold()
            if rule.lower_at_keyword == "media" and condition in {"", "all"}:
                nested = tuple(
                    tinycss2.parse_rule_list(
                        rule.content or (),
                        skip_comments=True,
                        skip_whitespace=True,
                    )
                )
                pending.extend(reversed(nested))
                continue
            if rule.lower_at_keyword == "media" and condition == "not all":
                continue
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "conditional-css",
                "SVG_CSS_ENVIRONMENT_UNREPRESENTABLE",
                (
                    f"CSS @{rule.lower_at_keyword} {condition!r} is outside the static "
                    "cascade profile."
                ),
                source=source_id,
            )
        return tuple(result)

    for style, stylesheet in parsed_styles:
        media = style.get("media", "all").strip().casefold()
        if media == "not all":
            continue
        if media not in {"", "all"}:
            raise SvgFeatureError(
                SvgFeatureClass.UNREPRESENTABLE,
                "conditional-css",
                "SVG_CSS_ENVIRONMENT_UNREPRESENTABLE",
                f"Stylesheet media condition {media!r} requires an external environment.",
                source=source_id,
            )
        for rule in static_qualified_rules(stylesheet):
            if rule.type == "error":
                continue
            prelude = getattr(rule, "prelude", None) or ()
            content = getattr(rule, "content", None) or ()
            external = _external_url_in_css((*prelude, *content))
            if external is not None:
                raise IconFontError(
                    "SVG_EXTERNAL_REFERENCE",
                    f"External CSS reference {external!r} is forbidden.",
                    source=source_id,
                )
            selector_text = _serialized(rule.prelude)
            if _dynamic_selector(rule.prelude):
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "dynamic-css-selector",
                    "SVG_CSS_ENVIRONMENT_UNREPRESENTABLE",
                    f"Selector {selector_text!r} depends on runtime interaction state.",
                    source=source_id,
                )
            if has_use and _use_shadow_sensitive_selector(rule.prelude):
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "use-shadow-css",
                    "SVG_CSS_USE_SHADOW_UNREPRESENTABLE",
                    (
                        f"Selector {selector_text!r} can match differently after local use "
                        "shadow-tree expansion."
                    ),
                    source=source_id,
                )
            if has_paint_template and _use_shadow_sensitive_selector(rule.prelude):
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "paint-shadow-css",
                    "SVG_CSS_PAINT_SHADOW_UNREPRESENTABLE",
                    (
                        f"Selector {selector_text!r} can match differently inside a "
                        "gradient or pattern template shadow tree."
                    ),
                    source=source_id,
                )
            if _selector_has_pseudo_class(rule.prelude, frozenset({"dir"})):
                raise SvgFeatureError(
                    SvgFeatureClass.UNREPRESENTABLE,
                    "css-selector-environment",
                    "SVG_CSS_ENVIRONMENT_UNREPRESENTABLE",
                    f"Selector {selector_text!r} depends on computed text direction.",
                    source=source_id,
                )
            try:
                selectors = cssselect2.compile_selector_list(rule.prelude)
            except (RecursionError, SyntaxError) as error:
                raise IconFontError(
                    "SVG_CSS_WORK_LIMIT",
                    "CSS selector compilation exceeds the bounded static profile.",
                    source=source_id,
                ) from error
            except cssselect2.SelectorError as error:
                raise IconFontError(
                    "SVG_CSS_SELECTOR_INVALID",
                    str(error),
                    source=source_id,
                ) from error
            declarations, order = _declarations(
                rule.content,
                source_id=source_id,
                supported_properties=supported_properties,
                start_order=order,
            )
            for selector in selectors:
                if selector.pseudo_element is not None or selector.never_matches:
                    raise SvgFeatureError(
                        SvgFeatureClass.UNREPRESENTABLE,
                        "css-selector-environment",
                        "SVG_CSS_ENVIRONMENT_UNREPRESENTABLE",
                        f"Selector {selector_text!r} is outside the static element profile.",
                        source=source_id,
                    )
                matcher.add_selector(selector, declarations)
                selector_count += 1
                if selector_count > max_rules:
                    raise IconFontError(
                        "SVG_CSS_WORK_LIMIT",
                        "Stylesheet selector count exceeds the configured expansion limit.",
                        source=source_id,
                    )

    wrapper_root = cssselect2.ElementWrapper.from_xml_root(root)
    wrappers = tuple(wrapper_root.iter_subtree())
    if len(wrappers) * max(1, selector_count) > max_work:
        raise IconFontError(
            "SVG_CSS_WORK_LIMIT",
            "Stylesheet matching exceeds the configured CSS work limit.",
            source=source_id,
        )

    for wrapper in wrappers:
        element = wrapper.etree_element
        winners: dict[str, tuple[tuple[int, tuple[int, int, int, int], int], str]] = {}

        for name in supported_properties:
            if name in element.attrib:
                _consider(
                    winners,
                    _Declaration(name, element.attrib[name], False, -1),
                    (0, 0, 0, 0),
                )

        for specificity, _selector_order, pseudo, declarations in matcher.match(wrapper):
            if pseudo is not None:
                continue
            for declaration in declarations:
                _consider(winners, declaration, (0, *specificity))

        inline = element.attrib.get("style")
        if inline is not None:
            declarations, order = _declarations(
                inline,
                source_id=source_id,
                supported_properties=supported_properties,
                start_order=order,
            )
            for declaration in declarations:
                _consider(winners, declaration, (1, 0, 0, 0))

        for name in supported_properties:
            element.attrib.pop(name, None)
        element.attrib.pop("style", None)
        element.attrib.pop("class", None)
        for name, (_, value) in sorted(winners.items()):
            element.set(name, value)

    for style in style_elements:
        parent = style.getparent()
        if parent is not None:
            parent.remove(style)
