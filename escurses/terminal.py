"""Terminal：把后端、缓冲区、渲染器、输入解析串成一个会话。

新代码推荐用法::

    from escurses import Terminal, Style

    with Terminal() as term:
        while True:
            for event in term.poll():
                if event.char == "q":
                    raise SystemExit
            term.screen.put(2, 1, "Hello, 世界", Style(bold=True))
            term.present()

``with`` 退出时一定会恢复光标、自动换行、备用屏幕和终端模式 ——
即使循环里抛了异常也一样。旧版没有这层保护，程序一崩终端就废了，
得 ``reset`` 才能救回来。
"""

from __future__ import annotations

import atexit
import sys
import time
from collections import deque
from typing import Callable, Deque, List, Optional, Tuple

from . import color as _color
from .backends import Backend, MemoryBackend, create_backend
from .exceptions import EscursesError, TerminalNotSupportedError, TerminalStateError
from .input import KeyEvent, KeyParser
from .render import render
from .screen import Screen
from .textutil import sanitize

__all__ = ["Terminal", "ANSI"]

#: 各种终端控制序列
class ANSI:
    ALT_SCREEN_ON = "\x1b[?1049h"
    ALT_SCREEN_OFF = "\x1b[?1049l"
    CURSOR_HIDE = "\x1b[?25l"
    CURSOR_SHOW = "\x1b[?25h"
    AUTOWRAP_OFF = "\x1b[?7l"
    AUTOWRAP_ON = "\x1b[?7h"
    CLEAR = "\x1b[2J\x1b[H"
    HOME = "\x1b[H"
    RESET = "\x1b[0m"
    BELL = "\x07"
    CURSOR_SAVE = "\x1b7"
    CURSOR_RESTORE = "\x1b8"

    @staticmethod
    def title(text: str) -> str:
        return "\x1b]0;%s\x07" % (text,)


class Terminal:
    """一个前台游戏会话。"""

    def __init__(
        self,
        backend: Optional[object] = None,
        *,
        alt_screen: bool = True,
        hide_cursor: bool = True,
        clear_on_start: bool = True,
        wrap: bool = False,
        title: Optional[str] = None,
        colors: Optional[str] = None,
        fallback_to_memory: bool = True,
        on_resize: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self._backend: Backend = None  # type: ignore[assignment]
        self._explicit_backend = backend is not None
        self._fallback_to_memory = fallback_to_memory
        self._degraded = False

        self._alt_screen = bool(alt_screen)
        self._hide_cursor = bool(hide_cursor)
        self._cursor_visible = not self._hide_cursor
        self._clear_on_start = bool(clear_on_start)
        self._wrap = bool(wrap)
        self._title = title
        self._on_resize = on_resize

        self._screen: Optional[Screen] = None
        self._front: Optional[List[List[Tuple[str, str]]]] = None
        self._parser = KeyParser()
        self._pending: Deque[KeyEvent] = deque()
        self._started = False
        self._closed = False
        self._last_resize: Optional[Tuple[int, int]] = None
        #: 终端内容是否确定是空白（刚清过屏），用于跳过整行空白的高效首帧
        self._terminal_blank = False

        if colors is not None:
            _color.set_color_support(colors)

        self._backend = self._make_backend(backend)

    # ------------------------------------------------------------------
    def _make_backend(self, backend: Optional[object]) -> Backend:
        try:
            return create_backend(backend)
        except TerminalNotSupportedError as exc:
            if not self._fallback_to_memory:
                raise
            self._degraded = True
            _warn("终端不可用（%s），已降级为内存后端，屏幕输出将被丢弃。" % (exc,))
            return MemoryBackend()

    # ---- 属性 ----------------------------------------------------------
    @property
    def backend(self) -> Backend:
        return self._backend

    @property
    def is_degraded(self) -> bool:
        """是否降级成了不显示任何东西的内存后端。"""
        return self._degraded

    @property
    def is_tty(self) -> bool:
        return bool(getattr(self._backend, "is_tty", False))

    @property
    def started(self) -> bool:
        return self._started

    @property
    def screen(self) -> Screen:
        if self._screen is None:
            raise TerminalStateError("Terminal 尚未 start()，请先调用 start() 或使用 with")
        return self._screen

    @property
    def width(self) -> int:
        return self.screen.width

    @property
    def height(self) -> int:
        return self.screen.height

    @property
    def size(self) -> Tuple[int, int]:
        return self.screen.size

    @property
    def supports_color(self) -> bool:
        return _color.get_color_support() != _color.ColorSupport.NONE

    # ---- 生命周期 ------------------------------------------------------
    def start(self) -> "Terminal":
        """进入游戏模式。可重复调用。"""
        if self._started:
            return self
        if self._closed:
            raise TerminalStateError("Terminal 已关闭，无法重新启动，请新建一个实例")

        try:
            self._backend.open()
        except TerminalNotSupportedError as exc:
            if not self._fallback_to_memory or self._explicit_backend:
                raise
            self._degraded = True
            _warn("无法启用终端（%s），已降级为内存后端，屏幕输出将被丢弃。" % (exc,))
            self._backend = MemoryBackend()
            self._backend.open()
        width, height = self._safe_size()
        self._screen = Screen(width, height)
        self._front = None

        setup = []
        if self._alt_screen:
            setup.append(ANSI.ALT_SCREEN_ON)
        if self._hide_cursor:
            setup.append(ANSI.CURSOR_HIDE)
        if not self._wrap:
            setup.append(ANSI.AUTOWRAP_OFF)
        if self._clear_on_start:
            setup.append(ANSI.CLEAR)
        if self._title:
            setup.append(ANSI.title(sanitize(self._title, "")))
        if setup:
            self._write("".join(setup))
        if self._hide_cursor:
            self._cursor_visible = False
        self._terminal_blank = self._clear_on_start

        self._started = True
        self._closed = False
        atexit.register(self.close)
        return self

    def close(self) -> None:
        """恢复终端状态。可重复调用，不会抛异常。"""
        if self._closed:
            return
        if not self._started:
            return
        self._closed = True
        self._started = False
        try:
            restore = [ANSI.RESET]
            if not self._cursor_visible:
                restore.append(ANSI.CURSOR_SHOW)
                self._cursor_visible = True
            if not self._wrap:
                restore.append(ANSI.AUTOWRAP_ON)
            if self._alt_screen:
                restore.append(ANSI.ALT_SCREEN_OFF)
            if self._backend is not None:
                self._write("".join(restore))
                self._backend.flush()
        except (OSError, ValueError):  # pragma: no cover - 终端已断
            pass
        finally:
            try:
                self._backend.close()
            except Exception:  # pragma: no cover - 关闭阶段的异常不再上抛
                pass
            try:
                atexit.unregister(self.close)
            except (ValueError, TypeError):  # pragma: no cover
                pass

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> "Terminal":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    # ---- 渲染 ----------------------------------------------------------
    def present(self) -> int:
        """把缓冲区差异刷到终端，返回本次写出的字符数。"""
        if not self._started:
            raise TerminalStateError("present() 之前必须调用 start()")
        self._handle_resize()
        data = render(
            self._front, self._screen, assume_blank=self._terminal_blank
        )
        self._terminal_blank = False
        if data:
            self._write(data)
        self._sync_front()
        self._backend.flush()
        return len(data)

    def clear(self) -> None:
        """清空缓冲区（下次 present 时生效）。"""
        self.screen.clear()

    def force_redraw(self) -> None:
        """丢弃上一帧快照，强制整屏重绘。"""
        self._front = None
        self.screen.mark_all_dirty()

    def screenshot(self) -> str:
        """把当前缓冲区导出成纯文本（调试 / 测试用）。"""
        return self.screen.to_text()

    # ---- 输入 ----------------------------------------------------------
    def poll(self, timeout: float = 0.0) -> List[KeyEvent]:
        """取走当前所有可用按键事件，没有就返回空列表。"""
        if not self._started:
            raise TerminalStateError("poll() 之前必须调用 start()")
        data = self._backend.read(timeout)
        events: List[KeyEvent] = []
        if data:
            events.extend(self._parser.feed(data))
        events.extend(self._parser.flush())
        return events

    def read_key(self, timeout: Optional[float] = None) -> Optional[KeyEvent]:
        """读一个按键。

        :param timeout: ``None`` 表示一直等，``0`` 表示不等待，其余为秒数。
        :returns: 超时返回 ``None``
        """
        if self._pending:
            return self._pending.popleft()
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        while True:
            if deadline is None:
                slice_timeout = 0.02
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    for event in self.poll(0.0):
                        self._pending.append(event)
                    return self._pending.popleft() if self._pending else None
                slice_timeout = min(0.02, remaining)

            for event in self.poll(slice_timeout):
                self._pending.append(event)
            if self._pending:
                return self._pending.popleft()
            if self._closed:  # pragma: no cover
                return None
            # 内存/管道后端不会真的阻塞，这里让出一点 CPU，避免空转
            time.sleep(0.001)

    # ---- 尺寸 ----------------------------------------------------------
    def _safe_size(self) -> Tuple[int, int]:
        try:
            width, height = self._backend.size()
        except (OSError, ValueError):  # pragma: no cover
            # 注意不能顺手 catch AttributeError：后端实现写错时应该炸出来，
            # 而不是被静默吞成 80x24
            width, height = 80, 24
        return (max(1, int(width)), max(1, int(height)))

    def _handle_resize(self) -> bool:
        """检测窗口尺寸变化，返回是否发生了变化。"""
        size = self._safe_size()
        if self._last_resize is None:
            self._last_resize = size
        if self._screen is None or size == self._screen.size:
            return False
        self._screen.apply_resize(*size)
        self._front = None
        self._last_resize = size
        # 先整屏清掉：缩小窗口时终端里会残留旧内容，diff 擦不到它们
        self._write(ANSI.CLEAR)
        self._terminal_blank = True
        if self._on_resize is not None:
            try:
                self._on_resize(*size)
            except Exception:  # pragma: no cover - 用户回调不应打断主循环
                pass
        return True

    def resize(self, width: int, height: int) -> None:
        """在内存后端上模拟一次窗口缩放（测试用）。"""
        setter = getattr(self._backend, "set_size", None)
        if setter is None:
            raise EscursesError("当前后端不支持手动设置尺寸")
        setter(width, height)

    # ---- 杂项 ----------------------------------------------------------
    def set_title(self, text: str) -> None:
        """设置窗口标题。"""
        self._require_started("set_title")
        self._write(ANSI.title(sanitize(text, "")))

    def bell(self) -> None:
        """响一下终端提示音。"""
        self._require_started("bell")
        self._write(ANSI.BELL)

    def show_cursor(self, show: bool = True) -> None:
        """显示 / 隐藏光标。"""
        self._require_started("show_cursor")
        self._write(ANSI.CURSOR_SHOW if show else ANSI.CURSOR_HIDE)
        self._cursor_visible = bool(show)

    def _require_started(self, name: str) -> None:
        if not self._started:
            raise TerminalStateError("%s() 之前必须调用 start()" % name)

    def _write(self, text: str) -> None:
        if text:
            self._backend.write(text)

    def _sync_front(self) -> None:
        screen = self.screen
        if self._front is None or len(self._front) != screen.height:
            self._front = [screen.row(y) for y in range(screen.height)]
        else:
            for y in screen.dirty_rows:
                if 0 <= y < screen.height:
                    self._front[y] = screen.row(y)
        screen.clear_dirty()

    def __repr__(self) -> str:  # pragma: no cover
        return "Terminal(%s, %s, started=%s)" % (
            self._backend.name,
            self._screen.size if self._screen else "unstarted",
            self._started,
        )


def _warn(message: str) -> None:
    """把警告写到 stderr，不打断游戏。"""
    try:
        sys.stderr.write("[escurses] %s\n" % message)
        sys.stderr.flush()
    except (OSError, ValueError):  # pragma: no cover
        pass
