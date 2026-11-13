"""二维单元格缓冲区。

``Screen`` 是纯内存结构，不做任何 I/O —— 所有终端写入都发生在
:mod:`escurses.render` 和 :mod:`escurses.terminal` 里。这样缓冲区可以
脱离终端被单元测试直接断言，也方便做"虚拟终端回放"测试。

坐标约定：**(x, y) = (列, 行)，从 0 开始**。

> 注意与旧 API 的差异：``drawChar(x, y, ch)`` 沿用旧版的 1-based 坐标，
> 而 ``Screen.put(x, y, ch)`` 是 0-based。兼容层负责换算，新代码请用 0-based。
"""

from __future__ import annotations

from typing import Iterable, List, Set, Tuple

from .color import Style
from .exceptions import ScreenBoundsError
from .textutil import clusters, sanitize, text_width

__all__ = ["Screen", "CONT"]

#: 宽字符占用的第二列标记。文本为空串的单元格就是"前半格的后半截"。
CONT: Tuple[str, str] = ("", "0")

Cell = Tuple[str, str]


def sgr_body(style: object) -> str:
    """把 ``Style`` / 原始 SGR 串 / ``None`` 统一成单元格里存的身体串。"""
    if style is None:
        return "0"
    if isinstance(style, Style):
        return style.body()
    if isinstance(style, str):
        return style or "0"
    raise TypeError("样式必须是 Style 或 SGR 字符串，收到 %r" % (style,))


class Screen:
    """一块宽 ``width`` 高 ``height`` 的字符网格。"""

    __slots__ = ("width", "height", "_cells", "_dirty", "_body", "_strict")

    def __init__(
        self,
        width: int,
        height: int,
        default_style: object = None,
        *,
        strict: bool = False,
    ) -> None:
        width = int(width)
        height = int(height)
        if width < 1:
            raise ValueError("宽度必须 >= 1，收到 %r" % (width,))
        if height < 1:
            raise ValueError("高度必须 >= 1，收到 %r" % (height,))
        self.width = width
        self.height = height
        self._body = sgr_body(default_style)
        self._cells: List[Cell] = [((" ", self._body))] * (width * height)
        self._dirty: Set[int] = set(range(height))
        #: 越界时是抛异常还是静默裁剪。游戏里画一个半边出屏的精灵属于正常
        #: 操作，所以默认裁剪；调试时可以打开严格模式揪出算错的坐标。
        self._strict = strict

    # ---- 基础属性 ------------------------------------------------------
    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @property
    def dirty_rows(self) -> Set[int]:
        return self._dirty

    @property
    def blank_cell(self) -> Cell:
        """"空白单元格"的规范值，渲染器用它判断整行是否可以跳过。"""
        return (" ", self._body)

    def __len__(self) -> int:
        return self.height

    def row(self, y: int) -> List[Cell]:
        """返回第 ``y`` 行单元格的副本。"""
        y = self._check_y(y)
        start = y * self.width
        return self._cells[start:start + self.width]

    def rows(self) -> Iterable[List[Cell]]:
        for y in range(self.height):
            yield self.row(y)

    def __repr__(self) -> str:
        return "Screen(%dx%d)" % (self.width, self.height)

    # ---- 边界检查 ------------------------------------------------------
    def _check_y(self, y: int) -> int:
        if not 0 <= y < self.height:
            raise ScreenBoundsError(
                "行坐标 y=%r 超出范围 0..%d" % (y, self.height - 1)
            )
        return y

    def contains(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    # ---- 写 ------------------------------------------------------------
    def mark_dirty(self, y: int) -> None:
        self._dirty.add(y)

    def mark_all_dirty(self) -> None:
        self._dirty = set(range(self.height))

    def clear_dirty(self) -> None:
        self._dirty.clear()

    def _blank(self) -> Cell:
        return (" ", self._body)

    def _repair_wide(self, x: int, y: int) -> None:
        """在覆盖 ``(x, y)`` 之前，拆掉跨在这格上的宽字符。

        宽字符占两格，如果只覆盖了其中一格，剩下的半截在屏幕上会变成
        一个孤立的"半个字"，且后续 diff 会认为那格没变而不去清它。
        """
        base = y * self.width
        cell = self._cells[base + x]
        if cell[0] == "" and x > 0:
            # 自己是后半截 → 前一个格子作废
            self._cells[base + x - 1] = self._blank()
        elif cell[0] != "" and x + 1 < self.width and self._cells[base + x + 1][0] == "":
            # 自己是前半截且后面跟着后半截 → 后半截作废
            self._cells[base + x + 1] = self._blank()

    def put(self, x: int, y: int, text: str, style: object = None) -> int:
        """在 ``(x, y)`` 起画一段文本，返回实际画出的列数。

        超出右边界或下边界的内容会被裁剪（``strict=True`` 时改为抛异常）。
        控制字符会被替换成 ``?``，避免 ANSI 注入。
        """
        if not isinstance(text, str):
            raise TypeError("text 必须是 str，收到 %r" % (type(text).__name__,))
        if not text:
            return 0
        if not isinstance(x, int) or not isinstance(y, int):
            raise TypeError("坐标必须是整数")

        if y < 0 or y >= self.height or x >= self.width:
            if self._strict:
                raise ScreenBoundsError("坐标 (%d, %d) 在屏幕外" % (x, y))
            return 0
        if x < 0:
            # 左侧越界：先按列数裁掉左边多出来的部分
            text = _clip_left(text, -x)
            x = 0
            if not text:
                return 0

        body = sgr_body(style)
        base = y * self.width
        drawn = 0
        cursor = x
        for chunk, width in clusters(sanitize(text)):
            if cursor + width > self.width:
                break
            self._repair_wide(cursor, y)
            if width == 2 and cursor + 1 < self.width:
                self._repair_wide(cursor + 1, y)
                self._cells[base + cursor] = (chunk, body)
                self._cells[base + cursor + 1] = ("", body)
            else:
                self._cells[base + cursor] = (chunk, body)
            cursor += width
            drawn += width
        if drawn:
            self._dirty.add(y)
        return drawn

    def draw_char(self, x: int, y: int, char: str, style: object = None) -> bool:
        """画单个字符，返回是否画上了。"""
        return self.put(x, y, char, style) > 0

    def fill(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        text: str = " ",
        style: object = None,
    ) -> None:
        """用 ``text`` 铺满矩形区域。

        宽字符会自动按两列一格铺。区域右边界放不下完整宽字符时补空格 ——
        绝不能只写前半截，否则缓冲区里会留下一个没有后半截的宽字符，
        渲染时终端要多占一列，整个屏幕就逐行错位了。
        """
        if width <= 0 or height <= 0:
            return
        y0 = max(0, y)
        y1 = min(self.height, y + height)
        x0 = max(0, x)
        limit = min(self.width, x + width)
        if y0 >= y1 or x0 >= limit:
            return

        body = sgr_body(style)
        parts = clusters(sanitize(text)) if text else [(" ", 1)]
        if not parts:
            parts = [(" ", 1)]
        chunk, chunk_width = parts[0]
        chunk_width = max(1, chunk_width)

        for row in range(y0, y1):
            base = row * self.width
            # 区域两端如果跨在已有宽字符上，先把那半个字拆掉
            self._repair_wide(x0, row)
            self._repair_wide(limit - 1, row)

            cursor = x0
            while cursor < limit:
                if chunk_width == 2 and cursor + 1 >= limit:
                    # 只剩一列，塞不下两列宽的字符
                    self._cells[base + cursor] = self._blank()
                    cursor += 1
                    continue
                self._cells[base + cursor] = (chunk, body)
                if chunk_width == 2:
                    self._cells[base + cursor + 1] = ("", body)
                cursor += chunk_width
            self._dirty.add(row)

    def clear(self, style: object = None) -> None:
        """整屏填充空格。"""
        body = self._body if style is None else sgr_body(style)
        self._cells = [((" ", body))] * (self.width * self.height)
        self.mark_all_dirty()

    # ---- 读 ------------------------------------------------------------
    def get(self, x: int, y: int) -> Cell:
        """读取单元格 ``(文本, 样式串)``。"""
        self._check_y(y)
        if not 0 <= x < self.width:
            raise ScreenBoundsError(
                "列坐标 x=%r 超出范围 0..%d" % (x, self.width - 1)
            )
        return self._cells[y * self.width + x]

    def char_at(self, x: int, y: int) -> str:
        """读取单元格上的文本（宽字符后半截返回空串）。"""
        return self.get(x, y)[0]

    def to_text(self) -> str:
        """把缓冲区导出成纯文本，方便测试与调试。"""
        lines = []
        for y in range(self.height):
            lines.append("".join(cell[0] for cell in self.row(y)))
        return "\n".join(lines)

    # ---- 变换 ----------------------------------------------------------
    def copy(self) -> "Screen":
        clone = Screen(self.width, self.height, strict=self._strict)
        clone._body = self._body
        clone._cells = list(self._cells)
        clone._dirty = set(self._dirty)
        return clone

    def resize(self, width: int, height: int, preserve: bool = True) -> "Screen":
        """返回调整尺寸后的新缓冲区，默认保留左上角重叠部分。"""
        new = Screen(width, height, strict=self._strict)
        new._body = self._body
        if preserve:
            copy_w = min(self.width, width)
            copy_h = min(self.height, height)
            for y in range(copy_h):
                src = self._cells[y * self.width: y * self.width + copy_w]
                dst = y * width
                new._cells[dst: dst + copy_w] = list(src)
                last = new._cells[dst + copy_w - 1]
                if width < self.width and last[0] and text_width(last[0]) == 2:
                    # 缩窗时右边界可能只留下宽字符的前半格，后半格已经被裁掉。
                    new._cells[dst + copy_w - 1] = new._blank()
        new.mark_all_dirty()
        return new

    def apply_resize(self, width: int, height: int, preserve: bool = True) -> None:
        """**就地**调整尺寸。

        与 :meth:`resize` 的区别：这个方法保持对象身份不变，所以游戏里
        长期持有的 ``screen = term.screen`` 引用在窗口缩放后依然有效。
        """
        new = self.resize(width, height, preserve)
        self.width = new.width
        self.height = new.height
        self._cells = new._cells
        self._dirty = new._dirty


def _clip_left(text: str, columns: int) -> str:
    """从左边裁掉 ``columns`` 列。"""
    parts = clusters(text)
    used = 0
    for index, (_chunk, width) in enumerate(parts):
        if used >= columns:
            return "".join(chunk for chunk, _w in parts[index:])
        used += width
    return ""
