import sys
import os
import time
if os.name == 'posix':
    import termios, tty, select
if os.name == 'nt':
    import msvcrt

_screen = []
_screenWidth = None
_screenHeight = None

_frameStartTime = None
_dirtyRowIndexs = set()
_previousDirtyRowIndexs = set()
_oldSettings = None
_fd = None

COLORDEFAULT = 0
COLORRED = 31
COLORGREEN = 32
COLORYELLOW = 33
COLORBLUE = 34

def frameStart():
    global _frameStartTime
    _frameStartTime = time.perf_counter()

def linuxTerminalCheck():
    isTTY = os.isatty(sys.stdin.fileno())
    return isTTY

def getTerminalSize():
    scrSize = os.get_terminal_size()
    return (scrSize.columns, scrSize.lines)

def resize():
    scrSize = getTerminalSize()
    global _screenWidth, _screenHeight, _screen
    _screenWidth = scrSize[0]
    _screenHeight = scrSize[1]

def initGame():
    scrSize = getTerminalSize()
    global _screenWidth, _screenHeight, _screen
    _screenWidth = scrSize[0]
    _screenHeight = scrSize[1]
    _screen = []
    for i in range(_screenHeight):        
        _screen.append([(' ', i+1, j+1) for j in range(_screenHeight)])
    sys.stdout.write("\033[?1049l\033[2J")
    global _oldSettings
    if os.name == 'posix':
        global _fd
        _fd = sys.stdin.fileno()
        _oldSettings = termios.tcgetattr(_fd)

def clear():
    sys.stdout.write('\033[1;1H')
    global _screen, _screenWidth, _previousDirtyRowIndexs
    _screen = []
    for i in range(_screenHeight):
            _screen.append([(' ', COLORDEFAULT) for j in range(_screenWidth - 1)])
    for rowIndex in _previousDirtyRowIndexs:
        sys.stdout.write(f'\033[{rowIndex + 1};1H' + ' ' * _screenWidth)
    _previousDirtyRowIndexs.clear()
    

def drawChar(x, y, char, color = COLORDEFAULT):
    global _dirtyRowsIndexs
    if (0 < y <= _screenHeight) and (0 < x < _screenWidth):
        _screen[y-1][x-1] = (char, color)
        _dirtyRowIndexs.add(y-1)

def drawStr(x, y, string, color = COLORDEFAULT):
    for i in range(len(string)):
        drawChar(x + i, y, string[i], color)

def getch(nodelay=True):
    if os.name == 'nt':
        if nodelay:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                return ch
            return None
        elif not nodelay:
            ch = msvcrt.getwch()
            return ch
    elif os.name == 'posix':
        if nodelay:
            tty.setcbreak(fd)
            if select.select([fd], [], [], 0):
                ch = sys.stdin.read(1)
                return ch
            return None
            termios.tcsetattr(_fd, termios.TCSADRAIN, _oldSettings)
        elif not nodelay:
            ch = sys.stdin.read(1)
            return ch
            termios.tcsetattr(_fd, termios.TCSADRAIN, _oldSettings)

def refresh():
    global _previousDirtyRowIndexs
    _previousDirtyRowIndexs = _dirtyRowIndexs.copy()
    for rowIndex in _dirtyRowIndexs:
        row = _screen[rowIndex]
        rowWillOutput = ''
        currentColor = COLORDEFAULT
        for ch in row:
            char = ch[0]
            color = ch[1]
            if currentColor != color:
                rowWillOutput += f'\033[{color}m'
                currentColor = color 
            rowWillOutput += char
        rowWillOutput += '\033[0m'
        sys.stdout.write(f'\033[{rowIndex+1};1H' + rowWillOutput)
    _dirtyRowIndexs.clear()
    sys.stdout.flush()

def cursorEcho(echo=False):
    if echo:
        sys.stdout.write('\033[?25h')
    if not echo:
        sys.stdout.write('\033[?25l')

def exitGame():
    sys.stdout.write('\033[?25h')
    sys.stdout.write('\033[?1049h')
    sys.stdout.write('\033[2J')
    sys.stdout.flush()
    if os.name == 'posix':
        termios.tcsetattr(_fd, termios.TCSADRAIN, _oldSettings)
    sys.exit()

def sleepForFrame(fps):
    frameTime = 1 / fps
    elapsedTime = time.perf_counter() - _frameStartTime
    time.sleep(max(0, (frameTime - elapsedTime) - 0.01))
    while time.perf_counter() - _frameStartTime < 0.01:
        pass

def theLifeAndEverythingAndUniverseUltimateAnswer():
    return 42