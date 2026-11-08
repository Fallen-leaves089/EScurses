# Escurses
A Python library that lets you make terminal games

[Go to homepage](./README.md)

## Why should you choose Escurses?
  - **Cross-platform support**
    It works on Windows and on Linux
    So you don't need to worry about this library being incompatible with your system, unless you're using macOS
  - **Easy to use**
    You just need to download it and drop it into your code directory, and then you can use it!
  - **Maintained**
    You probably don't know about pycurses—that's a very, very old library that hasn't been maintained for a long time
    EScurses is much newer than it, which means you can rest assured it won't suddenly stop being updated
    But the author also has to go to school QAQ (I'm just a fifth grader)

> I don't have a MacBook because it's not a common thing—it's too expensive, at least for me
> So... if you have a MacBook, please help me test whether this library works on macOS
> I need help :)

## Documentation
First, if you're a Linux user, I have to teach you a function
  - **`linuxTerminalCheck()`**
      This function is used to check whether you are in a tty environment. Whether you want blocking input or non-blocking input, you need to use this function to check the environment
      When it returns `True`, it means you really are in a tty environment, but if it returns `False`, that means you may not be in a pure tty environment, which could cause blocking to malfunction

Then there are the following functions
  - **`getTerminalSize()`**
    This function returns a tuple whose first element is the terminal width (columns) and whose second element is the terminal height (rows)
  - **`initGame()`**
    It enters the alternate screen, hides the cursor, and creates the internal screen buffer. On Windows it also enables ANSI escape support; on Linux/macOS it enables cbreak keyboard input
  - **`clear()`**
    It clears the internal screen buffer and marks every row for redraw; the next `refresh()` erases the previous frame. The usual pattern is `clear()` → draw → `refresh()`
  - **`getch(nodelay=True)`**
    One of the hardest things to implement, because it includes both Windows input and Linux input, and both systems' input have separate blocking and non-blocking versions, controlled by the `nodelay` parameter, which defaults to `True`
    If you enable non-blocking input, then when you haven't pressed any key, it will return `None`
    On Linux/macOS it is only guaranteed to work inside a pure tty. Input is decoded as UTF-8, so multi-byte characters are not split
  - **`drawChar(x, y, char, color)`**
    It draws the character you pass in at the specified `x` and `y`. Out-of-bounds coordinates return `False` and draw nothing, so negative coordinates or an off-screen position cannot crash the game
    As for how it works... well, I can explain
    Actually, we also have an internal variable `_screen`, which is an array that stores the character corresponding to each position. When you call this function, it combines the character you pass in with the coordinates you pass in into a tuple and puts it into the corresponding position in this array. However, the coordinates of the top-left corner of the screen are actually (1,1), not (0,0)
    We thoughtfully swapped `x` and `y` for you, because during actual drawing it's `y` first and `x` second, but we don't want you to suffer, so we swapped `x` and `y` in this function
    Also, when you pass the corresponding parameter to `color`, you can change the character's color. The color constants are already built into the library, such as `COLORRED`. The default value of this parameter is `COLORDEFAULT`
  - **`drawStr(x, y, string, color)`**
    Internally it calls `drawChar` repeatedly. `x` and `y` are the starting coordinates of the string, printed from left to right. The parameters are similar to those of `drawChar`
  - **`refresh()`**
    This redraws rows that changed. It positions each row once, emits color codes only when the color changes, and erases the rest of the row, which keeps output small
  - **`cursorEcho(echo=False)`**
    When you pass `False` to `echo`, this hides your cursor
    If you pass `True`, the cursor will be shown again
    Also, the default value of `echo` is `False`
  - **`endGame()`**
    Restores the cursor, automatic wrapping, alternate screen, and terminal input settings without exiting Python. It is safe to put in a `finally` block
  - **`exitGame()`**
    Restores the terminal and exits the game; it calls `endGame()` first
  - **`frameStart()`**
    If you want to control the frame rate, you can try this. Call it at the beginning of each main loop—be sure it's at the very, very, very beginning, with no other code before it. Then use it together with `sleepForFrame()` to control the frame rate
  - **`sleepForFrame`**
    It uses the start time recorded by `frameStart()` and waits until `1 / fps` seconds have elapsed since the beginning of the frame
  - **`theLifeAndEverythingAndUniverseUltimateAnswer()`**
    I admit its function name is really long. This is an easter egg function—no matter how you call it, it will return 42

That's basically all the content. I wish you all can make good games! (Although this library is basically useless)

## Running the tests

```bash
python -m unittest discover -s tests -v
```

***Translated By DeepSeek***
