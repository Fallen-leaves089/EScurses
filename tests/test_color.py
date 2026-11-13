"""颜色与样式测试。"""

from __future__ import annotations

import pytest

from escurses.color import (
    Color,
    ColorSupport,
    Style,
    detect_support,
    get_color_support,
    set_color_support,
)
from escurses.color import _rgb_to_16, _rgb_to_256


@pytest.fixture(autouse=True)
def reset_support():
    yield
    set_color_support(None)


class TestColor:
    def test_named(self):
        assert Color.named("red").to_basic() == 1
        assert Color.named("BRIGHT_WHITE").to_basic() == 15

    def test_named_normalises_separators(self):
        assert Color.named("bright-red") == Color.named("bright_red")

    def test_unknown_name(self):
        with pytest.raises(ValueError) as info:
            Color.named("chartreuse")
        assert "bright_white" in str(info.value)

    def test_index_bounds(self):
        assert Color.index(255).to_index() == 255
        with pytest.raises(ValueError):
            Color.index(256)
        with pytest.raises(ValueError):
            Color.index(-1)

    def test_rgb_bounds(self):
        with pytest.raises(ValueError):
            Color.rgb(256, 0, 0)
        with pytest.raises(ValueError):
            Color.rgb(0, -1, 0)

    @pytest.mark.parametrize(
        "spec,expected",
        [
            ("red", Color.named("red")),
            (196, Color.index(196)),
            ("196", Color.index(196)),
            ("#ff0000", Color.rgb(255, 0, 0)),
            ("#f00", Color.rgb(255, 0, 0)),
            ("ff0000", Color.rgb(255, 0, 0)),
        ],
    )
    def test_parse(self, spec, expected):
        assert Color.parse(spec) == expected

    def test_parse_digits_are_index_not_hex(self):
        # "196" 是颜色索引 196，不是 #119966 —— 无 # 前缀一律按十进制索引
        assert Color.parse("196") == Color.index(196)

    def test_parse_invalid_hex(self):
        with pytest.raises(ValueError):
            Color.parse("#gg0000")

    def test_parse_passthrough(self):
        color = Color.rgb(1, 2, 3)
        assert Color.parse(color) is color

    def test_color_is_immutable(self):
        color = Color.rgb(1, 2, 3)
        with pytest.raises(AttributeError):
            color.value = (4, 5, 6)
        with pytest.raises(AttributeError):
            del color.value

    def test_hashable(self):
        assert len({Color.named("red"), Color.index(1)}) == 1

    def test_default_has_no_sgr(self):
        assert Color.default().sgr(False, ColorSupport.TRUECOLOR) == ""


class TestQuantisation:
    def test_rgb_to_256_pure_red(self):
        assert _rgb_to_256(255, 0, 0) == 196

    def test_rgb_to_256_grey_ramp(self):
        # 灰色走 232-255 的 24 级灰阶，比色立方更精确
        assert _rgb_to_256(128, 128, 128) == 244
        assert _rgb_to_256(0, 0, 0) == 16
        assert _rgb_to_256(255, 255, 255) == 231

    def test_rgb_to_256_grey_never_exceeds_range(self):
        for value in range(256):
            assert 0 <= _rgb_to_256(value, value, value) <= 255

    def test_rgb_to_256_grey_endpoints(self):
        assert _rgb_to_256(7, 7, 7) == 232
        assert _rgb_to_256(238, 238, 238) == 255
        assert _rgb_to_256(247, 247, 247) == 231
        assert _rgb_to_256(248, 248, 248) == 231
        assert Color.rgb(248, 248, 248).to_index() == 231
        assert (
            Color.rgb(248, 248, 248).sgr(False, ColorSupport.EIGHT_BIT)
            == "38;5;231"
        )

    def test_rgb_to_16(self):
        assert _rgb_to_16(255, 0, 0) == 9
        assert _rgb_to_16(0, 0, 0) == 0
        assert _rgb_to_16(250, 250, 250) == 15

    def test_index_to_basic(self):
        assert Color.index(196).to_basic() in range(16)
        assert Color.index(5).to_basic() == 5


class TestSGR:
    def test_default_style(self):
        assert Style().body(ColorSupport.TRUECOLOR) == "0"
        assert Style().is_default()

    def test_bold(self):
        assert Style(bold=True).body(ColorSupport.BASIC) == "0;1"

    def test_all_attributes(self):
        style = Style(bold=True, dim=True, italic=True, underline=True, blink=True,
                      reverse=True, strike=True)
        assert style.body(ColorSupport.BASIC) == "0;1;2;3;4;5;7;9"

    def test_basic_foreground(self):
        assert Style(fg="red").body(ColorSupport.BASIC) == "0;31"

    def test_basic_bright_foreground(self):
        assert Style(fg="bright_red").body(ColorSupport.BASIC) == "0;91"

    def test_basic_background(self):
        assert Style(bg="blue").body(ColorSupport.BASIC) == "0;44"

    def test_256_foreground(self):
        assert Style(fg=Color.index(196)).body(ColorSupport.EIGHT_BIT) == "0;38;5;196"

    def test_truecolor(self):
        assert Style(fg=Color.rgb(255, 0, 0)).body(ColorSupport.TRUECOLOR) == "0;38;2;255;0;0"

    def test_truecolor_background(self):
        assert Style(bg=Color.rgb(0, 0, 255)).body(ColorSupport.TRUECOLOR) == "0;48;2;0;0;255"

    def test_truecolor_downgraded_to_256(self):
        body = Style(fg=Color.rgb(255, 0, 0)).body(ColorSupport.EIGHT_BIT)
        assert body == "0;38;5;196"

    def test_truecolor_downgraded_to_basic(self):
        body = Style(fg=Color.rgb(255, 0, 0)).body(ColorSupport.BASIC)
        assert body == "0;91"

    def test_no_color_support_drops_colors_but_keeps_attributes(self):
        body = Style(fg="red", bold=True).body(ColorSupport.NONE)
        assert body == "0;1"

    def test_sequence(self):
        assert Style(fg="red").sequence(ColorSupport.BASIC) == "\x1b[0;31m"

    def test_equality(self):
        assert Style(fg="red") == Style(fg="red")
        assert Style(fg="red") != Style(fg="blue")

    def test_replace(self):
        style = Style(fg="red")
        changed = style.replace(bold=True)
        assert changed.bold is True
        assert style.bold is False

    def test_style_is_immutable(self):
        style = Style(fg="red")
        with pytest.raises(AttributeError):
            style.fg = Color.default()
        with pytest.raises(AttributeError):
            del style.bold
        assert style.body(ColorSupport.TRUECOLOR) == "0;31"

    def test_replace_unknown_field(self):
        with pytest.raises(TypeError):
            Style().replace(blinken=True)

    def test_sgr_passthrough(self):
        assert Style.sgr("1;31").body() == "1;31"

    def test_caching_returns_same_string(self):
        style = Style(fg="red")
        first = style.body(ColorSupport.BASIC)
        second = style.body(ColorSupport.BASIC)
        assert first is second


class TestDetection:
    def test_no_color_env(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert detect_support() == ColorSupport.NONE

    def test_force_color(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("FORCE_COLOR", "3")
        assert detect_support() == ColorSupport.TRUECOLOR

    def test_non_tty_is_none(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)

        class Fake:
            def isatty(self):
                return False

        assert detect_support(Fake()) == ColorSupport.NONE

    def test_256color_term(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)
        monkeypatch.delenv("COLORTERM", raising=False)
        monkeypatch.setenv("TERM", "xterm-256color")

        class Fake:
            def isatty(self):
                return True

        assert detect_support(Fake()) == ColorSupport.EIGHT_BIT

    def test_set_support_by_name(self):
        assert set_color_support("256") == ColorSupport.EIGHT_BIT
        assert get_color_support() == ColorSupport.EIGHT_BIT

    def test_set_support_invalid(self):
        with pytest.raises(ValueError):
            set_color_support("rainbow")
