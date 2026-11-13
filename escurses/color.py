"""颜色与文本样式，以及 SGR 转义序列的生成与降级。

设计要点
--------

1. **单元格里存的是字符串**（例如 ``"0;1;38;5;196"``）而不是对象。
   字符串可哈希、可比较，行级 diff 时直接 ``==`` 就行，比逐个字段比较快得多。
2. **样式不可变**。想要"在红色基础上再加粗"请用 :meth:`Style.replace`，
   不要就地改 —— 就地改会让已经写进缓冲区的单元格跟着变，语义混乱。
3. **自动降级**。声明成 truecolor 的颜色，在只支持 256 色或 16 色的终端上
   会被量化到最接近的可用颜色，而不是输出一坨鬼画符。

用法::

    from escurses import Style, Color

    red   = Style(fg=Color.named("red"))
    title = Style(fg=Color.rgb(255, 200, 0), bg=Color.index(17), bold=True)
"""

from __future__ import annotations

import os
import sys
from enum import IntEnum
from typing import Dict, Optional, Tuple

__all__ = [
    "ColorSupport",
    "Color",
    "Style",
    "detect_support",
    "get_color_support",
    "set_color_support",
    "RESET",
    "BOLD",
    "DIM",
    "ITALIC",
    "UNDERLINE",
    "REVERSE",
    "STRIKE",
    "BLACK",
    "RED",
    "GREEN",
    "YELLOW",
    "BLUE",
    "MAGENTA",
    "CYAN",
    "WHITE",
    "BRIGHT_BLACK",
    "BRIGHT_RED",
    "BRIGHT_GREEN",
    "BRIGHT_YELLOW",
    "BRIGHT_BLUE",
    "BRIGHT_MAGENTA",
    "BRIGHT_CYAN",
    "BRIGHT_WHITE",
]

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
ITALIC = "\x1b[3m"
UNDERLINE = "\x1b[4m"
REVERSE = "\x1b[7m"
STRIKE = "\x1b[9m"


class ColorSupport(IntEnum):
    """终端色彩能力，值越大越强，可以直接比较大小。"""

    NONE = 0
    BASIC = 1        # 8 / 16 色
    EIGHT_BIT = 2    # 256 色
    TRUECOLOR = 3    # 24 位真彩


_NAMED: Dict[str, int] = {
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
    "bright_black": 8,
    "bright_red": 9,
    "bright_green": 10,
    "bright_yellow": 11,
    "bright_blue": 12,
    "bright_magenta": 13,
    "bright_cyan": 14,
    "bright_white": 15,
}

#: 16 色标准调色板的 RGB 近似值，仅用于把真彩色量化到低色深终端。
_PALETTE_16: Tuple[Tuple[int, int, int], ...] = (
    (0, 0, 0),
    (128, 0, 0),
    (0, 128, 0),
    (128, 128, 0),
    (0, 0, 128),
    (128, 0, 128),
    (0, 128, 128),
    (192, 192, 192),
    (128, 128, 128),
    (255, 0, 0),
    (0, 255, 0),
    (255, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 255),
)


class Color:
    """一个不可变的颜色值。

    用三个工厂方法创建，不要直接调 ``__init__``：

    * :meth:`Color.named` —— 16 个标准色名，跨平台最稳；
    * :meth:`Color.index` —— 256 色索引；
    * :meth:`Color.rgb`   —— 24 位真彩。
    """

    __slots__ = ("kind", "value", "_frozen")

    def __init__(self, kind: str, value: object) -> None:
        object.__setattr__(self, "_frozen", False)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("Color 不可变；请创建新的 Color 实例")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("Color 不可变；请创建新的 Color 实例")
        object.__delattr__(self, name)

    # ---- 工厂 ----------------------------------------------------------
    @classmethod
    def default(cls) -> "Color":
        """使用终端默认色。"""
        return cls("default", None)

    @classmethod
    def named(cls, name: str) -> "Color":
        """按名字取色，例如 ``"red"`` / ``"bright_cyan"``。

        名字写错会抛 :class:`ValueError` 并列出所有合法名字 —— 一个拼写
        错误不该让人对着黑屏猜半小时。
        """
        key = name.strip().lower().replace(" ", "_").replace("-", "_")
        if key not in _NAMED:
            raise ValueError(
                "未知颜色名 %r，可用：%s" % (name, ", ".join(sorted(_NAMED)))
            )
        return cls("index", _NAMED[key])

    @classmethod
    def index(cls, value: int) -> "Color":
        """按 256 色索引取色（0-255）。"""
        value = int(value)
        if not 0 <= value <= 255:
            raise ValueError("颜色索引必须在 0-255 之间，收到 %r" % (value,))
        return cls("index", value)

    @classmethod
    def rgb(cls, r: int, g: int, b: int) -> "Color":
        """按 24 位真彩取色。"""
        channels = []
        for name, raw in (("r", r), ("g", g), ("b", b)):
            value = int(raw)
            if not 0 <= value <= 255:
                raise ValueError("颜色分量 %s 必须在 0-255 之间，收到 %r" % (name, raw))
            channels.append(value)
        return cls("rgb", tuple(channels))

    @classmethod
    def parse(cls, spec: object) -> "Color":
        """宽松解析：接受 ``Color``、``"red"``、``"#ff8800"``、``196``、``(255, 136, 0)``。"""
        if isinstance(spec, Color):
            return spec
        if isinstance(spec, bool):
            raise TypeError("bool 不是颜色")
        if isinstance(spec, int):
            return cls.index(spec)
        if isinstance(spec, (tuple, list)):
            if len(spec) != 3:
                raise ValueError("RGB 元组必须是 3 个分量，收到 %r" % (spec,))
            return cls.rgb(*spec)  # type: ignore[misc]
        if isinstance(spec, str):
            text = spec.strip()
            if text.startswith("#"):
                # 明确带 # 前缀才算十六进制，避免 "196" 被当成 #119966
                digits = text[1:]
                if len(digits) in (3, 6) and all(c in "0123456789abcdefABCDEF" for c in digits):
                    if len(digits) == 3:
                        digits = "".join(c * 2 for c in digits)
                    return cls.rgb(
                        int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)
                    )
                raise ValueError("无法解析颜色：%r" % (spec,))
            if text.isdigit():
                return cls.index(int(text))
            if len(text) == 6 and all(c in "0123456789abcdefABCDEF" for c in text):
                return cls.rgb(int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
            return cls.named(text)
        raise TypeError("无法解析颜色：%r" % (spec,))

    # ---- 协议 ----------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Color):
            return NotImplemented
        return self.kind == other.kind and self.value == other.value

    def __hash__(self) -> int:
        return hash((self.kind, self.value))

    def __repr__(self) -> str:
        if self.kind == "rgb":
            return "Color.rgb%r" % (tuple(self.value),)  # type: ignore[arg-type]
        if self.kind == "index":
            return "Color.index(%r)" % (self.value,)
        return "Color.default()"

    # ---- 量化 ----------------------------------------------------------
    def _rgb_tuple(self) -> Optional[Tuple[int, int, int]]:
        if self.kind == "rgb":
            return self.value  # type: ignore[return-value]
        if self.kind == "index":
            return _index_to_rgb(int(self.value))  # type: ignore[arg-type]
        return None

    def to_index(self) -> Optional[int]:
        """把颜色折叠成 256 色索引，无法表示时返回 ``None``。"""
        if self.kind == "default":
            return None
        if self.kind == "index":
            return int(self.value)  # type: ignore[arg-type]
        r, g, b = self._rgb_tuple()  # type: ignore[misc]
        return _rgb_to_256(r, g, b)

    def to_basic(self) -> Optional[int]:
        """把颜色折叠成 0-15 的 ANSI 索引。"""
        if self.kind == "default":
            return None
        if self.kind == "index":
            value = int(self.value)  # type: ignore[arg-type]
            if value < 16:
                return value
            rgb = _index_to_rgb(value)
            return _rgb_to_16(*rgb)
        r, g, b = self._rgb_tuple()  # type: ignore[misc]
        return _rgb_to_16(r, g, b)

    # ---- SGR -----------------------------------------------------------
    def sgr(self, is_background: bool = False, support: "ColorSupport" = None) -> str:  # type: ignore[assignment]
        """生成 SGR 参数片段，例如 ``"31"`` 或 ``"38;2;255;0;0"``。"""
        support = get_color_support() if support is None else support
        if self.kind == "default" or support == ColorSupport.NONE:
            return ""

        if support == ColorSupport.TRUECOLOR and self.kind == "rgb":
            r, g, b = self._rgb_tuple()  # type: ignore[misc]
            return "%d;2;%d;%d;%d" % (48 if is_background else 38, r, g, b)

        if support >= ColorSupport.EIGHT_BIT:
            index = self.to_index()
            if index is not None:
                if index < 8:
                    return str((40 if is_background else 30) + index)
                if index < 16:
                    return str((100 if is_background else 90) + index - 8)
                return "%d;5;%d" % (48 if is_background else 38, index)

        index = self.to_basic()
        if index is None:
            return ""
        if index < 8:
            return str((40 if is_background else 30) + index)
        return str((100 if is_background else 90) + index - 8)


def _rgb_to_256(r: int, g: int, b: int) -> int:
    # 灰阶（r == g == b）走 232-255 的 24 级灰阶，比 6x6x6 色立方更准
    if r == g == b:
        # 同时考虑黑色（16）和白色（231）；灰阶索引本身只到 255。
        best_index = 16
        best_distance = r
        for step in range(24):
            level = 8 + step * 10
            distance = abs(r - level)
            if distance < best_distance:
                best_index = 232 + step
                best_distance = distance
        if 255 - r < best_distance:
            return 231
        return best_index
    steps = (0, 95, 135, 175, 215, 255)
    ri = min(range(6), key=lambda i: abs(steps[i] - r))
    gi = min(range(6), key=lambda i: abs(steps[i] - g))
    bi = min(range(6), key=lambda i: abs(steps[i] - b))
    return 16 + 36 * ri + 6 * gi + bi


def _index_to_rgb(index: int) -> Tuple[int, int, int]:
    if index < 16:
        return _PALETTE_16[index]
    if index < 232:
        index -= 16
        steps = (0, 95, 135, 175, 215, 255)
        return (steps[index // 36], steps[(index % 36) // 6], steps[index % 6])
    level = 8 + (index - 232) * 10
    return (level, level, level)


def _rgb_to_16(r: int, g: int, b: int) -> int:
    best = 0
    best_distance = None
    for i, (pr, pg, pb) in enumerate(_PALETTE_16):
        distance = (pr - r) ** 2 + (pg - g) ** 2 + (pb - b) ** 2
        if best_distance is None or distance < best_distance:
            best = i
            best_distance = distance
    return best


class Style:
    """不可变的文本样式。

    所有字段都有默认值，``Style()`` 就是"终端默认样式"。
    """

    __slots__ = (
        "fg",
        "bg",
        "bold",
        "dim",
        "italic",
        "underline",
        "blink",
        "reverse",
        "strike",
        "_cache",
        "_frozen",
    )

    def __init__(
        self,
        fg: Optional[object] = None,
        bg: Optional[object] = None,
        *,
        bold: bool = False,
        dim: bool = False,
        italic: bool = False,
        underline: bool = False,
        blink: bool = False,
        reverse: bool = False,
        strike: bool = False,
    ) -> None:
        object.__setattr__(self, "_frozen", False)
        self.fg = Color.parse(fg) if fg is not None else Color.default()
        self.bg = Color.parse(bg) if bg is not None else Color.default()
        self.bold = bold
        self.dim = dim
        self.italic = italic
        self.underline = underline
        self.blink = blink
        self.reverse = reverse
        self.strike = strike
        self._cache: Dict[int, str] = {}
        object.__setattr__(self, "_frozen", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("Style 不可变；请使用 replace() 创建新样式")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if getattr(self, "_frozen", False):
            raise AttributeError("Style 不可变；请使用 replace() 创建新样式")
        object.__delattr__(self, name)

    # ---- 工厂 ----------------------------------------------------------
    @classmethod
    def sgr(cls, spec: object) -> "Style":
        """把字符串原样当作 SGR 参数包成样式，例如 ``Style.sgr("1;31")``。

        给想直接手写转义序列的高级用户留的口子。
        """
        style = cls()
        style._cache.update({0: str(spec), 1: str(spec), 2: str(spec), 3: str(spec)})
        return style

    def replace(self, **changes: object) -> "Style":
        """返回修改了部分字段的新样式。"""
        fields = {
            "fg": self.fg,
            "bg": self.bg,
            "bold": self.bold,
            "dim": self.dim,
            "italic": self.italic,
            "underline": self.underline,
            "blink": self.blink,
            "reverse": self.reverse,
            "strike": self.strike,
        }
        unknown = set(changes) - set(fields)
        if unknown:
            raise TypeError("未知样式字段：%s" % ", ".join(sorted(unknown)))
        fields.update(changes)
        fg = fields.pop("fg")
        bg = fields.pop("bg")
        return Style(fg=fg, bg=bg, **fields)  # type: ignore[arg-type]

    # ---- SGR -----------------------------------------------------------
    def body(self, support: "ColorSupport" = None) -> str:  # type: ignore[assignment]
        """返回 SGR 参数串（不含 ``ESC [`` 与 ``m``）。

        默认样式返回 ``"0"``，用来把终端恢复成初始状态。
        """
        support = get_color_support() if support is None else support
        cached = self._cache.get(int(support))
        if cached is not None:
            return cached

        parts = ["0"]
        if self.bold:
            parts.append("1")
        if self.dim:
            parts.append("2")
        if self.italic:
            parts.append("3")
        if self.underline:
            parts.append("4")
        if self.blink:
            parts.append("5")
        if self.reverse:
            parts.append("7")
        if self.strike:
            parts.append("9")

        fg = self.fg.sgr(False, support)
        if fg:
            parts.append(fg)
        bg = self.bg.sgr(True, support)
        if bg:
            parts.append(bg)

        body = ";".join(parts)
        self._cache[int(support)] = body
        return body

    def sequence(self, support: "ColorSupport" = None) -> str:  # type: ignore[assignment]
        """完整的转义序列，例如 ``"\\x1b[0;1;31m"``。"""
        return "\x1b[" + self.body(support) + "m"

    def is_default(self) -> bool:
        """是否等价于终端默认样式。"""
        return self.body(ColorSupport.TRUECOLOR) == "0"

    # ---- 协议 ----------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Style):
            return NotImplemented
        return self.body(ColorSupport.TRUECOLOR) == other.body(ColorSupport.TRUECOLOR)

    def __hash__(self) -> int:
        return hash(self.body(ColorSupport.TRUECOLOR))

    def __repr__(self) -> str:
        fields = []
        if self.fg.kind != "default":
            fields.append("fg=%r" % (self.fg,))
        if self.bg.kind != "default":
            fields.append("bg=%r" % (self.bg,))
        for name in ("bold", "dim", "italic", "underline", "blink", "reverse", "strike"):
            if getattr(self, name):
                fields.append("%s=True" % name)
        return "Style(%s)" % ", ".join(fields)


# ---------------------------------------------------------------------------
# 能力探测
# ---------------------------------------------------------------------------

_support: Optional[ColorSupport] = None


def _env_support() -> Optional[ColorSupport]:
    if "NO_COLOR" in os.environ:
        return ColorSupport.NONE
    force = os.environ.get("FORCE_COLOR")
    if force is not None:
        return {
            "0": ColorSupport.NONE,
            "1": ColorSupport.BASIC,
            "2": ColorSupport.EIGHT_BIT,
            "3": ColorSupport.TRUECOLOR,
        }.get(force.strip(), ColorSupport.TRUECOLOR)
    return None


def detect_support(stream: object = None) -> ColorSupport:
    """探测某个输出流支持多少色。

    优先级：``NO_COLOR`` > ``FORCE_COLOR`` > isatty 检查 > ``COLORTERM`` >
    ``TERM``。非 TTY（被重定向到文件/管道）一律返回 ``NONE``，否则日志里
    会混入大量转义序列。
    """
    override = _env_support()
    if override is not None:
        return override

    stream = sys.stdout if stream is None else stream
    isatty = getattr(stream, "isatty", None)
    try:
        if not (callable(isatty) and isatty()):
            return ColorSupport.NONE
    except (ValueError, OSError):
        return ColorSupport.NONE

    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return ColorSupport.TRUECOLOR

    term = os.environ.get("TERM", "")
    if term == "dumb":
        return ColorSupport.NONE
    if "256color" in term:
        return ColorSupport.EIGHT_BIT

    if sys.platform == "win32":
        # Windows 10 1703+ 的 conhost 与 Windows Terminal 都支持真彩；
        # 更老的系统会在后端层被降级（见 backends/windows.py）。
        return ColorSupport.TRUECOLOR

    if term:
        return ColorSupport.BASIC
    return ColorSupport.NONE


def get_color_support() -> ColorSupport:
    """返回当前生效的色彩能力（首次调用时自动探测）。"""
    global _support
    if _support is None:
        _support = detect_support()
    return _support


def set_color_support(support: object) -> ColorSupport:
    """强制指定色彩能力，传 ``None`` 恢复自动探测。"""
    global _support
    if support is None:
        _support = None
    else:
        if isinstance(support, str):
            mapping = {
                "none": ColorSupport.NONE,
                "basic": ColorSupport.BASIC,
                "16": ColorSupport.BASIC,
                "256": ColorSupport.EIGHT_BIT,
                "eight_bit": ColorSupport.EIGHT_BIT,
                "truecolor": ColorSupport.TRUECOLOR,
                "24bit": ColorSupport.TRUECOLOR,
            }
            key = support.strip().lower()
            if key not in mapping:
                raise ValueError("未知的色彩能力：%r" % (support,))
            _support = mapping[key]
        else:
            _support = ColorSupport(int(support))  # type: ignore[arg-type]
    return get_color_support()


# ---------------------------------------------------------------------------
# 常用预设样式
# ---------------------------------------------------------------------------

BLACK = Style(fg=Color.named("black"))
RED = Style(fg=Color.named("red"))
GREEN = Style(fg=Color.named("green"))
YELLOW = Style(fg=Color.named("yellow"))
BLUE = Style(fg=Color.named("blue"))
MAGENTA = Style(fg=Color.named("magenta"))
CYAN = Style(fg=Color.named("cyan"))
WHITE = Style(fg=Color.named("white"))
BRIGHT_BLACK = Style(fg=Color.named("bright_black"))
BRIGHT_RED = Style(fg=Color.named("bright_red"))
BRIGHT_GREEN = Style(fg=Color.named("bright_green"))
BRIGHT_YELLOW = Style(fg=Color.named("bright_yellow"))
BRIGHT_BLUE = Style(fg=Color.named("bright_blue"))
BRIGHT_MAGENTA = Style(fg=Color.named("bright_magenta"))
BRIGHT_CYAN = Style(fg=Color.named("bright_cyan"))
BRIGHT_WHITE = Style(fg=Color.named("bright_white"))
