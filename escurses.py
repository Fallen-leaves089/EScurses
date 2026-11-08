"""A tiny, dependency-free terminal game library for beginners."""

import atexit
import codecs
import os
import shutil
import sys
import time
from collections import deque

if os.name == 'posix':
    import select
    import termios
    import tty
if os.name == 'nt':
    import ctypes
    import msvcrt


COLORDEFAULT = 0
COLORRED = 31
COLORGREEN = 32
COLORYELLOW = 33
COLORBLUE = 34

_ENTER_ALT_SCREEN = '\033[?1049h'
_EXIT_ALT_SCREEN = '\033[?1049l'
_HIDE_CURSOR = '\033[?25l'
_SHOW_CURSOR = '\033[?25h'
_DISABLE_WRAP = '\033[?7l'
_ENABLE_WRAP = '\033[?7h'
_CLEAR_SCREEN = '\033[2J\033[H'
_ERASE_LINE = '\033[K'
_RESET_COLOR = '\033[0m'

_screen = []
_screenWidth = None
_screenHeight = None

_frameStartTime = None
_dirtyRowIndexs = set()
_gameInited = False
_atexitRegistered = False

_fd = None
_oldSettings = None
_inputBuffer = deque()
_decoder = None

_oldWindowsMode = None
_windowsStdoutHandle = None


def _makeBlankScreen():
    return [
        [(' ', COLORDEFAULT) for _ in range(_screenWidth)]
        for _ in range(_screenHeight)
    ]


def _ensureInited(apiName):
    if not _gameInited:
        raise RuntimeError(
            'Please call initGame() before calling ' + apiName + '().'
        )


def _enableWindowsVT():
    global _oldWindowsMode, _windowsStdoutHandle

    if os.name != 'nt':
        return

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        kernel32.GetConsoleMode.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

        handle = kernel32.GetStdHandle(-11)
        if not handle:
            return
        consoleMode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(consoleMode)):
            return

        if _oldWindowsMode is None:
            _oldWindowsMode = consoleMode.value
            _windowsStdoutHandle = handle

        enableVirtualTerminalProcessing = 0x0004
        if not consoleMode.value & enableVirtualTerminalProcessing:
            kernel32.SetConsoleMode(
                handle,
                consoleMode.value | enableVirtualTerminalProcessing,
            )
    except (AttributeError, OSError, ValueError):
        pass


def _restoreWindowsVT():
    global _oldWindowsMode, _windowsStdoutHandle

    if os.name != 'nt' or _oldWindowsMode is None:
        return

    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel32.SetConsoleMode(_windowsStdoutHandle, _oldWindowsMode)
    except (AttributeError, OSError, ValueError):
        pass
    finally:
        _oldWindowsMode = None
        _windowsStdoutHandle = None


def _setupPosixTerminal():
    global _fd, _oldSettings, _decoder

    if os.name != 'posix':
        return

    encoding = getattr(sys.stdin, 'encoding', None) or 'utf-8'
    _decoder = codecs.getincrementaldecoder(encoding)(errors='replace')
    try:
        _fd = sys.stdin.fileno()
        _oldSettings = termios.tcgetattr(_fd)
        tty.setcbreak(_fd)
    except (AttributeError, OSError, ValueError, termios.error):
        _fd = None
        _oldSettings = None


def _restorePosixTerminal():
    global _fd, _oldSettings

    if os.name != 'posix':
        return

    try:
        if _fd is not None and _oldSettings is not None:
            termios.tcsetattr(_fd, termios.TCSADRAIN, _oldSettings)
    except (OSError, ValueError, termios.error):
        pass
    finally:
        _fd = None
        _oldSettings = None


def frameStart():
    global _frameStartTime
    _frameStartTime = time.perf_counter()


def linuxTerminalCheck():
    try:
        return os.isatty(sys.stdin.fileno())
    except (AttributeError, OSError, ValueError):
        return False


def getTerminalSize():
    terminalSize = shutil.get_terminal_size(fallback=(80, 24))
    return (terminalSize.columns, terminalSize.lines)


def initGame():
    global _screen, _screenWidth, _screenHeight, _dirtyRowIndexs
    global _gameInited, _frameStartTime, _atexitRegistered, _inputBuffer

    if _gameInited:
        endGame()

    _enableWindowsVT()
    _screenWidth, _screenHeight = getTerminalSize()
    _screenWidth = max(1, _screenWidth)
    _screenHeight = max(1, _screenHeight)
    _screen = _makeBlankScreen()
    _dirtyRowIndexs = set()
    _frameStartTime = None
    _inputBuffer = deque()
    _gameInited = True

    if not _atexitRegistered:
        atexit.register(endGame)
        _atexitRegistered = True

    _setupPosixTerminal()
    sys.stdout.write(
        _ENTER_ALT_SCREEN + _CLEAR_SCREEN + _HIDE_CURSOR + _DISABLE_WRAP
    )
    sys.stdout.flush()


def resize():
    global _screen, _screenWidth, _screenHeight, _dirtyRowIndexs

    _ensureInited('resize')
    _screenWidth, _screenHeight = getTerminalSize()
    _screenWidth = max(1, _screenWidth)
    _screenHeight = max(1, _screenHeight)
    _screen = _makeBlankScreen()
    _dirtyRowIndexs = set()
    sys.stdout.write(_CLEAR_SCREEN)
    sys.stdout.flush()


def clear():
    global _screen, _dirtyRowIndexs

    _ensureInited('clear')
    _screen = _makeBlankScreen()
    _dirtyRowIndexs = set(range(_screenHeight))


def drawChar(x, y, char, color=COLORDEFAULT):
    if not _gameInited:
        raise RuntimeError('Please call initGame() before calling drawChar().')
    if not isinstance(char, str) or not char:
        return False

    character = char[0]
    if ord(character) < 32 or ord(character) == 127:
        return False
    if not (1 <= x <= _screenWidth and 1 <= y <= _screenHeight):
        return False

    _screen[y - 1][x - 1] = (character, color)
    _dirtyRowIndexs.add(y - 1)
    return True


def drawStr(x, y, string, color=COLORDEFAULT):
    _ensureInited('drawStr')
    for offset, character in enumerate(string):
        drawChar(x + offset, y, character, color)


def _readPosixInput():
    global _inputBuffer

    data = os.read(_fd, 1024)
    if not data:
        raise EOFError('Standard input was closed.')
    _inputBuffer.extend(_decoder.decode(data))


def _getchPosix(nodelay):
    if _fd is None or _decoder is None:
        raise RuntimeError(
            'Keyboard input is unavailable; use linuxTerminalCheck() first.'
        )

    if _inputBuffer:
        return _inputBuffer.popleft()

    if nodelay:
        if not select.select([_fd], [], [], 0)[0]:
            return None
        _readPosixInput()
        if _inputBuffer:
            return _inputBuffer.popleft()
        return None

    while not _inputBuffer:
        _readPosixInput()
    return _inputBuffer.popleft()


def _getchWindows(nodelay):
    if nodelay:
        if not msvcrt.kbhit():
            return None
        return msvcrt.getwch()
    return msvcrt.getwch()


def getch(nodelay=True):
    if os.name == 'nt':
        return _getchWindows(nodelay)
    if os.name == 'posix':
        return _getchPosix(nodelay)
    return None


def refresh():
    _ensureInited('refresh')
    if not _dirtyRowIndexs:
        return

    output = []
    currentColor = None
    for rowIndex in sorted(_dirtyRowIndexs):
        row = list(_screen[rowIndex])
        while row and row[-1][0] == ' ':
            row.pop()

        output.append('\033[{};1H'.format(rowIndex + 1))
        for character, color in row:
            if color != currentColor:
                output.append('\033[{}m'.format(color))
                currentColor = color
            output.append(character)
        output.append(_ERASE_LINE)

    output.append(_RESET_COLOR)
    sys.stdout.write(''.join(output))
    sys.stdout.flush()
    _dirtyRowIndexs.clear()


def cursorEcho(echo=False):
    if echo:
        sys.stdout.write(_SHOW_CURSOR)
    else:
        sys.stdout.write(_HIDE_CURSOR)
    sys.stdout.flush()


def endGame():
    global _screen, _screenWidth, _screenHeight, _dirtyRowIndexs
    global _frameStartTime, _gameInited, _inputBuffer, _decoder

    try:
        if _gameInited:
            sys.stdout.write(
                _RESET_COLOR + _ENABLE_WRAP + _SHOW_CURSOR + _EXIT_ALT_SCREEN
            )
            sys.stdout.flush()
    except (AttributeError, OSError, ValueError):
        pass
    finally:
        _restorePosixTerminal()
        _restoreWindowsVT()
        _screen = []
        _screenWidth = None
        _screenHeight = None
        _dirtyRowIndexs = set()
        _frameStartTime = None
        _inputBuffer = deque()
        _decoder = None
        _gameInited = False


def exitGame():
    endGame()
    sys.exit()


def sleepForFrame(fps):
    global _frameStartTime

    if fps <= 0:
        raise ValueError('fps must be greater than 0.')
    if _frameStartTime is None:
        _frameStartTime = time.perf_counter()

    frameTime = 1.0 / fps
    targetTime = _frameStartTime + frameTime
    remaining = targetTime - time.perf_counter()
    if remaining <= 0:
        return

    spinTime = min(0.001, remaining)
    time.sleep(max(0.0, remaining - spinTime))
    while time.perf_counter() < targetTime:
        pass


def theLifeAndEverythingAndUniverseUltimateAnswer():
    return 42
