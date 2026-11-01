#!/usr/bin/env python3
"""Keep a test run from taking the foreground off whoever is using the PC.

A test browser opens far off the desktop, but it still comes to the
front: the active window moves to it and the person's typing goes into a
window nobody can see. Two quieter fixes were measured and do not work,
which is why this one is a lock.

  * Starting the browser with SW_SHOWNOACTIVATE or minimised (what a
    launcher can ask Windows for) changes the first ShowWindow only.
    Chromium shows its first window a second time right after, and a
    window that is already visible is simply activated, so it still
    takes the foreground.
  * Windows here has ForegroundLockTimeout 0, so it will let any program
    take the foreground, not just the one being used.

LockSetForegroundWindow turns SetForegroundWindow off for every program
until it is undone. Windows undoes it by itself when the person presses
Alt or clicks another window, and when the process that took it exits,
so hold() keeps asking while a test runs, and a crashed test cannot leave
the screen locked. The browser still opens, paints, can be driven over
WebDriver and photographed with PrintWindow. It just is not brought to
the front.

Set BORING_WINDOW_POSITION to watch a test on screen on purpose: nothing
is locked then, as that variable already means "put the browser where I
can see it".

  from focus_lock import hold
  with hold():
      ...start browsers, run the test...
"""

import ctypes
import os
import threading

LSFW_LOCK = 1
LSFW_UNLOCK = 2

# How often the lock is asked for again. Windows drops it when the person
# clicks another window; this is how long a browser could then take the
# front before it is shut again.
REASSERT_SECONDS = 0.25

_guard = threading.Lock()
_holders = 0
_stop = None
_thread = None


def _lock(code):
    """One call to LockSetForegroundWindow. False if Windows said no."""
    if os.name != "nt":
        return False
    return bool(ctypes.windll.user32.LockSetForegroundWindow(code))


def _keep(stop):
    while not stop.wait(REASSERT_SECONDS):
        _lock(LSFW_LOCK)


def _acquire():
    global _holders, _stop, _thread
    with _guard:
        _holders += 1
        if _holders > 1:
            return
        # Locked before the caller starts a browser, then kept locked.
        _lock(LSFW_LOCK)
        _stop = threading.Event()
        _thread = threading.Thread(target=_keep, args=(_stop,), daemon=True)
        _thread.start()


def _release():
    global _holders
    with _guard:
        _holders -= 1
        if _holders > 0:
            return
        _stop.set()
        _thread.join(2)
        _lock(LSFW_UNLOCK)


class Hold:
    """The foreground is kept where it is until release(), or the with ends."""

    def __init__(self):
        # Watching a test on purpose: leave the browser free to come forward.
        self._live = not os.environ.get("BORING_WINDOW_POSITION")
        if self._live:
            _acquire()

    def release(self):
        if self._live:
            self._live = False
            _release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def hold():
    return Hold()
