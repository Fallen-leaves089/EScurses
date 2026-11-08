"""Regression tests for the single-file EScurses library."""

import codecs
import io
import os
import sys
import unittest
from collections import deque
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import escurses


class EscursesTest(unittest.TestCase):
    def setUp(self):
        self.originalStdout = sys.stdout
        self.fakeStdout = io.StringIO()
        sys.stdout = self.fakeStdout

        self.realGetTerminalSize = escurses.getTerminalSize
        self.getTerminalSizePatcher = mock.patch.object(
            escurses, 'getTerminalSize', return_value=(80, 24)
        )
        self.getTerminalSize = self.getTerminalSizePatcher.start()
        self.enableWindowsVTPatcher = mock.patch.object(
            escurses, '_enableWindowsVT'
        )
        self.enableWindowsVT = self.enableWindowsVTPatcher.start()
        self.restoreWindowsVTPatcher = mock.patch.object(
            escurses, '_restoreWindowsVT'
        )
        self.restoreWindowsVT = self.restoreWindowsVTPatcher.start()
        self.setupPosixTerminalPatcher = mock.patch.object(
            escurses, '_setupPosixTerminal'
        )
        self.setupPosixTerminal = self.setupPosixTerminalPatcher.start()
        self.restorePosixTerminalPatcher = mock.patch.object(
            escurses, '_restorePosixTerminal'
        )
        self.restorePosixTerminal = self.restorePosixTerminalPatcher.start()

        escurses._gameInited = False
        escurses._screen = []
        escurses._screenWidth = None
        escurses._screenHeight = None
        escurses._dirtyRowIndexs = set()
        escurses._frameStartTime = None
        escurses._inputBuffer = deque()
        escurses._decoder = None

    def tearDown(self):
        escurses.endGame()
        sys.stdout = self.originalStdout
        self.getTerminalSizePatcher.stop()
        self.enableWindowsVTPatcher.stop()
        self.restoreWindowsVTPatcher.stop()
        self.setupPosixTerminalPatcher.stop()
        self.restorePosixTerminalPatcher.stop()

    def output(self):
        return self.fakeStdout.getvalue()

    def clearOutput(self):
        self.fakeStdout.seek(0)
        self.fakeStdout.truncate(0)

    def testInitGameCreatesTheWholeScreenBuffer(self):
        escurses.initGame()

        self.assertEqual(len(escurses._screen), 24)
        self.assertEqual(len(escurses._screen[0]), 80)
        self.assertEqual(escurses._screen[0][0], (' ', escurses.COLORDEFAULT))

        output = self.output()
        self.assertIn('\033[?1049h', output)
        self.assertIn('\033[?25l', output)
        self.assertIn('\033[?7l', output)
        self.assertNotIn('\033[?1049l', output)

    def testEndGameRestoresTheTerminal(self):
        escurses.initGame()
        self.clearOutput()

        escurses.endGame()

        output = self.output()
        self.assertIn('\033[0m', output)
        self.assertIn('\033[?7h', output)
        self.assertIn('\033[?25h', output)
        self.assertIn('\033[?1049l', output)
        self.assertFalse(escurses._gameInited)

    def testEndGameIsSafeToCallTwice(self):
        escurses.initGame()
        escurses.endGame()
        self.clearOutput()

        escurses.endGame()

        self.assertEqual(self.output(), '')

    def testDrawingBeforeInitRaisesFriendlyError(self):
        with self.assertRaises(RuntimeError):
            escurses.drawChar(1, 1, 'X')
        with self.assertRaises(RuntimeError):
            escurses.clear()
        with self.assertRaises(RuntimeError):
            escurses.refresh()

    def testDrawCharRejectsOutOfBoundsCoordinates(self):
        escurses.initGame()
        escurses.clear()

        self.assertFalse(escurses.drawChar(0, 1, 'X'))
        self.assertFalse(escurses.drawChar(1, 0, 'X'))
        self.assertFalse(escurses.drawChar(81, 1, 'X'))
        self.assertFalse(escurses.drawChar(1, 25, 'X'))
        self.assertTrue(escurses.drawChar(80, 24, 'X'))

        self.assertEqual(escurses._screen[23][79], ('X', escurses.COLORDEFAULT))
        written = sum(
            cell[0] == 'X' for row in escurses._screen for cell in row
        )
        self.assertEqual(written, 1)

    def testDrawCharRejectsControlCharacters(self):
        escurses.initGame()
        escurses.clear()

        self.assertFalse(escurses.drawChar(1, 1, '\n'))
        self.assertFalse(escurses.drawChar(1, 1, '\t'))
        self.assertFalse(escurses.drawChar(1, 1, ''))

    def testRefreshWritesRowsWithColorsAndThenBecomesIdle(self):
        escurses.initGame()
        escurses.clear()
        escurses.drawChar(1, 1, 'A', escurses.COLORRED)
        escurses.drawChar(1, 2, 'B', escurses.COLORRED)
        self.clearOutput()

        escurses.refresh()

        output = self.output()
        self.assertTrue(output.startswith('\033[1;1H\033[31mA\033[K'))
        self.assertIn('\033[2;1HB\033[K', output)
        self.assertIn('\033[24;1H', output)
        self.assertTrue(output.endswith('\033[0m'))

        self.clearOutput()
        escurses.refresh()
        self.assertEqual(self.output(), '')

    def testClearErasesPreviousFrameOnNextRefresh(self):
        escurses.initGame()
        escurses.drawChar(1, 1, 'A')
        escurses.refresh()
        self.clearOutput()

        escurses.clear()
        escurses.refresh()

        output = self.output()
        self.assertNotIn('A', output)
        self.assertIn('\033[1;1H\033[K', output)

    def testResizeRebuildsTheBuffer(self):
        self.getTerminalSize.side_effect = [(80, 24), (100, 30)]
        escurses.initGame()
        self.clearOutput()

        escurses.resize()

        self.assertEqual(len(escurses._screen), 30)
        self.assertEqual(len(escurses._screen[0]), 100)
        self.assertIn('\033[2J\033[H', self.output())

    def testGetTerminalSizePassesASafeFallback(self):
        with mock.patch.object(
            escurses.shutil,
            'get_terminal_size',
            return_value=os.terminal_size((120, 40)),
        ) as getTerminalSize:
            self.assertEqual(self.realGetTerminalSize(), (120, 40))

        getTerminalSize.assert_called_once_with(fallback=(80, 24))

    def testSleepForFrameUsesTheRequestedFrameTime(self):
        escurses._frameStartTime = 100.0
        targetTime = 100.0 + (1.0 / 60.0)

        with mock.patch.object(
            escurses.time,
            'perf_counter',
            side_effect=[100.002, targetTime],
        ), mock.patch.object(escurses.time, 'sleep') as sleep:
            escurses.sleepForFrame(60)

        sleep.assert_called_once()
        expectedSleep = (1.0 / 60.0) - 0.002 - 0.001
        self.assertAlmostEqual(sleep.call_args.args[0], expectedSleep, places=6)

    def testSleepForFrameRejectsInvalidFps(self):
        with self.assertRaises(ValueError):
            escurses.sleepForFrame(0)
        with self.assertRaises(ValueError):
            escurses.sleepForFrame(-1)

    @unittest.skipUnless(os.name == 'posix', 'POSIX input decoder test')
    def testPosixInputDecoderHandlesSplitUtf8Characters(self):
        escurses._fd = 0
        escurses._decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        escurses._inputBuffer = deque()

        with mock.patch.object(
            escurses.os,
            'read',
            side_effect=[b'\xe4', b'\xbd\xa0'],
        ):
            escurses._readPosixInput()
            self.assertEqual(len(escurses._inputBuffer), 0)
            escurses._readPosixInput()

        self.assertEqual(list(escurses._inputBuffer), ['你'])

    def testTheAnswerIsStill42(self):
        self.assertEqual(
            escurses.theLifeAndEverythingAndUniverseUltimateAnswer(),
            42,
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
