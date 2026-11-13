"""缓冲区测试。"""

from __future__ import annotations

import pytest

from escurses import Style
from escurses.exceptions import ScreenBoundsError
from escurses.screen import CONT, Screen, sgr_body


@pytest.fixture
def screen():
    return Screen(10, 4)


class TestConstruction:
    def test_size(self, screen):
        assert screen.size == (10, 4)
        assert screen.width == 10
        assert screen.height == 4

    @pytest.mark.parametrize("width,height", [(0, 4), (4, 0), (-1, 4)])
    def test_invalid_size(self, width, height):
        with pytest.raises(ValueError):
            Screen(width, height)

    def test_blank(self, screen):
        assert screen.to_text() == "\n".join([" " * 10] * 4)

    def test_default_style_applied(self):
        screen = Screen(3, 1, Style(fg="red"))
        assert screen.get(0, 0)[1] == Style(fg="red").body()


class TestPut:
    def test_simple(self, screen):
        assert screen.put(0, 0, "abc") == 3
        assert screen.to_text().split("\n")[0] == "abc       "

    def test_offset(self, screen):
        screen.put(3, 1, "xy")
        assert screen.to_text().split("\n")[1] == "   xy     "

    def test_returns_columns(self, screen):
        assert screen.put(0, 0, "中文") == 4

    def test_clip_right(self, screen):
        assert screen.put(8, 0, "abcdef") == 2
        assert screen.to_text().split("\n")[0] == " " * 8 + "ab"

    def test_wide_char_clipped_at_edge(self, screen):
        # 第 9 列（0-based）只剩一格，放不下两列宽的汉字
        assert screen.put(9, 0, "中") == 0
        assert screen.to_text().split("\n")[0] == " " * 10

    def test_clip_left(self, screen):
        assert screen.put(-1, 0, "abc") == 2
        assert screen.to_text().split("\n")[0].startswith("bc")

    def test_out_of_screen_is_silent(self, screen):
        assert screen.put(0, 99, "x") == 0
        assert screen.put(99, 0, "x") == 0

    def test_strict_mode_raises(self):
        screen = Screen(5, 2, strict=True)
        with pytest.raises(ScreenBoundsError):
            screen.put(0, 5, "x")

    def test_type_errors(self, screen):
        with pytest.raises(TypeError):
            screen.put(0, 0, 123)
        with pytest.raises(TypeError):
            screen.put("a", 0, "x")

    def test_control_chars_are_neutralised(self, screen):
        screen.put(0, 0, "\x1b[2J")
        assert screen.to_text().split("\n")[0].startswith("?[2J")


class TestWideChars:
    def test_placeholder_cell(self, screen):
        screen.put(0, 0, "中")
        assert screen.get(0, 0)[0] == "中"
        assert screen.get(1, 0)[0] == ""

    def test_overwrite_second_half_clears_first(self, screen):
        screen.put(0, 0, "中")
        screen.put(1, 0, "x")
        assert screen.get(0, 0)[0] == " "
        assert screen.get(1, 0)[0] == "x"

    def test_overwrite_first_half_clears_second(self, screen):
        screen.put(0, 0, "中")
        screen.put(0, 0, "y")
        assert screen.get(0, 0)[0] == "y"
        assert screen.get(1, 0)[0] == " "

    def test_mixed_text_alignment(self, screen):
        screen.put(0, 0, "a中b")
        assert screen.to_text().split("\n")[0] == "a中b      "

    def test_continuation_marker(self, screen):
        screen.put(0, 0, "中")
        assert screen.get(1, 0) == CONT


class TestFill:
    def test_fill_rect(self, screen):
        screen.fill(2, 1, 3, 2, "#")
        assert screen.to_text() == "\n".join(
            [" " * 10, "  ###     ", "  ###     ", " " * 10]
        )

    def test_fill_clips(self, screen):
        screen.fill(8, 3, 10, 10, "#")
        assert screen.to_text().split("\n")[3] == " " * 8 + "##"

    def test_fill_negative_size_is_noop(self, screen):
        before = screen.to_text()
        screen.fill(0, 0, -1, 5, "#")
        assert screen.to_text() == before

    def test_fill_wide_char(self, screen):
        screen.fill(0, 0, 4, 1, "中")
        assert screen.to_text().split("\n")[0] == "中中      "


class TestClear:
    def test_clear(self, screen):
        screen.put(0, 0, "abc")
        screen.clear()
        assert screen.to_text() == "\n".join([" " * 10] * 4)

    def test_clear_marks_everything_dirty(self, screen):
        screen.clear_dirty()
        screen.clear()
        assert screen.dirty_rows == set(range(4))


class TestRead:
    def test_get_out_of_bounds(self, screen):
        with pytest.raises(ScreenBoundsError):
            screen.get(10, 0)
        with pytest.raises(ScreenBoundsError):
            screen.get(0, 4)

    def test_bounds_error_is_index_error(self, screen):
        # 旧版抛的就是 IndexError，不能破坏 except IndexError
        with pytest.raises(IndexError):
            screen.get(99, 0)

    def test_contains(self, screen):
        assert screen.contains(0, 0)
        assert screen.contains(9, 3)
        assert not screen.contains(10, 0)


class TestTransform:
    def test_copy_is_independent(self, screen):
        screen.put(0, 0, "a")
        clone = screen.copy()
        clone.put(0, 0, "b")
        assert screen.get(0, 0)[0] == "a"
        assert clone.get(0, 0)[0] == "b"

    def test_resize_preserves(self, screen):
        screen.put(0, 0, "abc")
        bigger = screen.resize(20, 8)
        assert bigger.size == (20, 8)
        assert bigger.get(0, 0)[0] == "a"

    def test_resize_shrinks(self, screen):
        screen.put(9, 3, "x")
        smaller = screen.resize(5, 2)
        assert smaller.size == (5, 2)
        assert smaller.to_text() == "     \n     "

    def test_resize_drops_truncated_wide_char(self):
        screen = Screen(5, 1)
        screen.put(3, 0, "界")
        smaller = screen.resize(4, 1)
        assert smaller.get(3, 0)[0] == " "
        assert smaller.to_text() == "    "

    def test_resize_keeps_complete_wide_char(self):
        screen = Screen(5, 1)
        screen.put(2, 0, "界")
        smaller = screen.resize(4, 1)
        assert smaller.get(2, 0)[0] == "界"
        assert smaller.get(3, 0)[0] == ""

    def test_apply_resize_keeps_identity(self, screen):
        screen.put(0, 0, "abc")
        original_id = id(screen)
        screen.apply_resize(20, 8)
        assert id(screen) == original_id
        assert screen.size == (20, 8)
        assert screen.get(0, 0)[0] == "a"

    def test_resize_marks_all_dirty(self, screen):
        screen.clear_dirty()
        screen.apply_resize(20, 8)
        assert screen.dirty_rows == set(range(8))


class TestDirtyTracking:
    def test_new_screen_is_dirty(self, screen):
        assert screen.dirty_rows == set(range(4))

    def test_put_marks_row(self, screen):
        screen.clear_dirty()
        screen.put(0, 2, "x")
        assert screen.dirty_rows == {2}

    def test_clear_dirty(self, screen):
        screen.clear_dirty()
        assert screen.dirty_rows == set()


def test_sgr_body_helper():
    assert sgr_body(None) == "0"
    assert sgr_body("") == "0"
    assert sgr_body("1;31") == "1;31"
    assert sgr_body(Style(bold=True)) == "0;1"
    with pytest.raises(TypeError):
        sgr_body(42)
