"""Terminal 会话层测试。"""

from __future__ import annotations

import pytest

from escurses import MemoryBackend, Style, Terminal, set_color_support
from escurses.exceptions import TerminalNotSupportedError, TerminalStateError
from escurses.input import Key, Modifiers
from vt import VirtualTerminal


class BrokenBackend:
    """模拟老系统：一打开就报不支持。"""

    name = "broken"
    supports_ansi = True
    is_tty = True

    def open(self):
        raise TerminalNotSupportedError("假装是老控制台")

    def close(self):
        pass

    def write(self, text):
        pass

    def flush(self):
        pass

    def read(self, timeout=0.0):
        return b""

    def size(self):
        return (80, 24)


@pytest.fixture(autouse=True)
def truecolor():
    set_color_support("truecolor")
    yield
    set_color_support(None)


class TestLifecycle:
    def test_start_emits_setup_sequences(self):
        backend = MemoryBackend(20, 5)
        terminal = Terminal(backend)
        terminal.start()
        output = backend.take_output()
        terminal.close()
        assert "\x1b[?1049h" in output  # 备用屏幕
        assert "\x1b[?25l" in output  # 隐藏光标
        assert "\x1b[?7l" in output  # 关自动换行
        assert "\x1b[2J" in output

    def test_close_restores_state(self):
        backend = MemoryBackend(20, 5)
        terminal = Terminal(backend)
        terminal.start()
        backend.take_output()
        terminal.close()
        output = backend.take_output()
        assert "\x1b[?25h" in output
        assert "\x1b[?7h" in output
        assert "\x1b[?1049l" in output

    def test_close_is_idempotent(self):
        terminal = Terminal(MemoryBackend(10, 3))
        terminal.start()
        terminal.close()
        terminal.close()
        assert terminal.closed

    def test_close_before_start_is_noop(self):
        backend = MemoryBackend(10, 3)
        terminal = Terminal(backend)
        terminal.close()
        assert not terminal.closed
        assert backend.output == ""
        terminal.start()
        assert terminal.started
        terminal.close()

    def test_context_manager(self):
        backend = MemoryBackend(10, 3)
        with Terminal(backend) as terminal:
            assert terminal.started
        assert not terminal.started

    def test_context_manager_restores_on_exception(self):
        backend = MemoryBackend(10, 3)
        with pytest.raises(ValueError):
            with Terminal(backend):
                raise ValueError("boom")
        assert "\x1b[?1049l" in backend.output

    def test_cannot_restart_after_close(self):
        terminal = Terminal(MemoryBackend(10, 3))
        terminal.start()
        terminal.close()
        with pytest.raises(TerminalStateError):
            terminal.start()

    def test_no_alt_screen(self):
        backend = MemoryBackend(10, 3)
        terminal = Terminal(backend, alt_screen=False, hide_cursor=False,
                            clear_on_start=False, wrap=True)
        terminal.start()
        output = backend.take_output()
        terminal.close()
        assert "\x1b[?1049h" not in output
        assert "\x1b[?25l" not in output
        assert "\x1b[?7l" not in output
        assert output == ""

    def test_title_set(self):
        backend = MemoryBackend(10, 3)
        terminal = Terminal(backend, title="Snake")
        terminal.start()
        output = backend.take_output()
        terminal.close()
        assert "Snake" in output


class TestStateGuards:
    def test_screen_before_start(self):
        terminal = Terminal(MemoryBackend(10, 3))
        with pytest.raises(TerminalStateError):
            terminal.screen

    def test_present_before_start(self):
        terminal = Terminal(MemoryBackend(10, 3))
        with pytest.raises(TerminalStateError):
            terminal.present()

    def test_poll_before_start(self):
        terminal = Terminal(MemoryBackend(10, 3))
        with pytest.raises(TerminalStateError):
            terminal.poll()


class TestRendering:
    def test_output_matches_buffer(self, session):
        terminal, vt = session
        terminal.screen.put(1, 0, "Hello 世界", Style(fg="red", bold=True))
        terminal.present()
        vt.feed(terminal.backend.take_output())
        assert vt.mismatches(terminal.screen) == []

    def test_incremental_output_is_small(self, session):
        terminal, _vt = session
        terminal.screen.put(0, 0, "x" * 20)
        terminal.present()
        terminal.backend.take_output()
        terminal.screen.put(0, 0, "y")
        terminal.present()
        delta = terminal.backend.take_output()
        # 只应该有一条定位序列 + 一个字符
        assert len(delta) < 20
        assert "y" in delta

    def test_second_present_without_change_writes_nothing(self, session):
        terminal, _vt = session
        terminal.screen.put(0, 0, "abc")
        terminal.present()
        terminal.backend.take_output()
        terminal.present()
        assert terminal.backend.take_output() == ""

    def test_force_redraw(self, session):
        terminal, _vt = session
        terminal.present()
        terminal.backend.take_output()
        terminal.force_redraw()
        terminal.present()
        assert terminal.backend.take_output() != ""

    def test_clear(self, session):
        terminal, vt = session
        terminal.screen.put(0, 0, "abcdef")
        terminal.present()
        vt.feed(terminal.backend.take_output())
        terminal.clear()
        terminal.present()
        vt.feed(terminal.backend.take_output())
        assert vt.mismatches(terminal.screen) == []

    def test_full_width_is_usable(self, session):
        """最后一列必须能画 —— 旧版少了这一列。"""
        terminal, vt = session
        width = terminal.width
        terminal.screen.put(width - 1, 0, "X")
        terminal.present()
        vt.feed(terminal.backend.take_output())
        assert vt.char_at(width - 1, 0) == "X"

    def test_bottom_right_corner(self, session):
        terminal, vt = session
        terminal.screen.put(terminal.width - 1, terminal.height - 1, "X")
        terminal.present()
        vt.feed(terminal.backend.take_output())
        assert vt.char_at(terminal.width - 1, terminal.height - 1) == "X"
        assert vt.cy < vt.height  # 没有把屏幕滚上去

    def test_screenshot(self, session):
        terminal, _vt = session
        terminal.screen.put(0, 0, "hi")
        assert terminal.screenshot().startswith("hi")


class TestInput:
    def test_poll_reads_keys(self, session):
        terminal, _vt = session
        terminal.backend.feed(b"ab")
        events = terminal.poll()
        assert [e.char for e in events] == ["a", "b"]

    def test_poll_no_keys(self, session):
        terminal, _vt = session
        assert terminal.poll() == []

    def test_arrow_key(self, session):
        terminal, _vt = session
        terminal.backend.feed(b"\x1b[A")
        assert terminal.poll()[0].key is Key.UP

    def test_read_key_timeout(self, session):
        terminal, _vt = session
        assert terminal.read_key(timeout=0) is None

    def test_read_key_returns_pending(self, session):
        terminal, _vt = session
        terminal.backend.feed(b"z")
        assert terminal.read_key(timeout=0.2).char == "z"

    def test_ctrl_modifier(self, session):
        terminal, _vt = session
        terminal.backend.feed(b"\x1b[1;5C")
        event = terminal.poll()[0]
        assert event.key is Key.RIGHT
        assert event.modifiers == Modifiers.CTRL


class TestResize:
    def test_resize_keeps_object_identity(self, session):
        terminal, _vt = session
        screen = terminal.screen
        terminal.resize(24, 8)
        terminal.present()
        assert terminal.size == (24, 8)
        assert terminal.screen is screen

    def test_resize_preserves_content(self, session):
        terminal, _vt = session
        terminal.screen.put(0, 0, "keep")
        terminal.present()
        terminal.resize(30, 10)
        terminal.present()
        assert terminal.screen.to_text().startswith("keep")

    def test_resize_triggers_full_redraw(self, session):
        terminal, _vt = session
        terminal.screen.put(0, 0, "keep me")
        terminal.present()
        terminal.backend.take_output()
        terminal.resize(30, 10)
        terminal.present()
        output = terminal.backend.take_output()
        assert "\x1b[2J" in output
        assert "keep me" in output

    def test_resize_callback(self):
        seen = []
        terminal = Terminal(MemoryBackend(20, 5), on_resize=lambda w, h: seen.append((w, h)))
        terminal.start()
        terminal.resize(30, 8)
        terminal.present()
        terminal.close()
        assert seen == [(30, 8)]

    def test_resize_after_shrink_replays_correctly(self, session):
        terminal, _vt = session
        terminal.screen.fill(0, 0, terminal.width, terminal.height, "#")
        terminal.present()
        terminal.backend.take_output()  # 缩放前的输出属于旧尺寸，丢掉

        terminal.resize(12, 4)
        terminal.present()
        # 缩放时会先整屏清空再全量重绘，所以这段输出是自包含的
        vt = VirtualTerminal(*terminal.size)
        vt.feed(terminal.backend.take_output())
        assert vt.mismatches(terminal.screen) == []


class TestDegrade:
    def test_falls_back_to_memory(self, monkeypatch, capsys):
        # 自动选后端时失败 → 降级；用户显式传入的后端则不允许静默替换
        monkeypatch.setattr(
            "escurses.terminal.create_backend", lambda prefer=None: BrokenBackend()
        )
        terminal = Terminal()
        terminal.start()
        assert terminal.is_degraded
        terminal.screen.put(0, 0, "x")
        terminal.present()
        terminal.close()
        assert "降级" in capsys.readouterr().err

    def test_explicit_backend_does_not_fall_back(self):
        with pytest.raises(TerminalNotSupportedError):
            Terminal(BrokenBackend(), fallback_to_memory=False).start()

    def test_explicit_backend_failure_is_loud(self):
        with pytest.raises(TerminalNotSupportedError):
            Terminal(BrokenBackend()).start()


class TestMisc:
    def test_set_title_and_bell(self, session):
        terminal, vt = session
        terminal.set_title("Snake")
        terminal.bell()
        vt.feed(terminal.backend.take_output())
        assert vt.titles[-1] == "Snake"
        assert vt.bell_count == 1

    def test_show_cursor(self, session):
        terminal, vt = session
        terminal.show_cursor(True)
        vt.feed(terminal.backend.take_output())
        assert vt.cursor_visible is True

    def test_manual_cursor_hide_is_restored(self):
        backend = MemoryBackend(10, 3)
        terminal = Terminal(backend, hide_cursor=False)
        terminal.start()
        backend.take_output()
        terminal.show_cursor(False)
        terminal.close()
        assert "\x1b[?25h" in backend.output

    def test_supports_color(self, session):
        terminal, _vt = session
        assert terminal.supports_color is True

    def test_colors_argument(self):
        terminal = Terminal(MemoryBackend(10, 3), colors="basic")
        terminal.start()
        assert not terminal.is_degraded
        terminal.close()

    def test_is_tty(self, session):
        terminal, _vt = session
        assert terminal.is_tty is True
