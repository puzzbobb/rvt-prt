"""What a print is doing, on stderr: each stage as it starts, the model and links read, the caches
built, and a bar while the sheets are drawn. Off unless `enable`d (the CLI's print turns it on; the
library stays quiet). On a terminal the bar redraws in place; otherwise a line per sheet."""
import os
import shutil
import sys
import time

ON = False
_t0 = time.perf_counter()
_bar = ""  # the bar's text as last drawn, redrawn under any message


def enable(on=True):
    global ON, _t0
    ON, _t0 = on, time.perf_counter()


def _tty():
    return sys.stderr.isatty()


def say(msg):
    """A message on a line of its own, above the bar: printed whether or not progress is on."""
    if ON and _bar and _tty():
        sys.stderr.write("\r\033[K")
    print(msg, file=sys.stderr, flush=True)
    if ON and _bar and _tty():
        sys.stderr.write(_bar)
        sys.stderr.flush()


def _rss():
    """This process's resident memory, GB (Linux), else None."""
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e9
    except (OSError, IndexError, ValueError):
        return None


def step(msg):
    """A stage starting, with the time since the print began and the memory this process holds."""
    if ON:
        rss = _rss()
        say(f"[{time.perf_counter() - _t0:6.1f} s" + (f" {rss:4.1f} GB" if rss is not None else "") + f"] {msg}")


class Bar:
    """Sheets drawn of `total`: update(done, running, note) redraws it."""

    def __init__(self, total, label="Drawing sheets"):
        self.total, self.label, self.t0, self.done = total, label, time.perf_counter(), 0

    def update(self, done, running=(), note="", free=None):
        global _bar
        if not ON:
            return
        finished, self.done = done > self.done, done
        elapsed = time.perf_counter() - self.t0
        if not _tty():
            if finished:
                print(f"[{time.perf_counter() - _t0:6.1f} s] {note} ({done}/{self.total})", file=sys.stderr, flush=True)
            return
        width = 24
        fill = int(width * done / max(self.total, 1))
        eta = f", ~{elapsed / done * (self.total - done):.0f} s left" if 0 < done < self.total else ""
        text = (f"{self.label} [{'#' * fill}{'.' * (width - fill)}] {done}/{self.total}  {elapsed:.0f} s{eta}"
                + (f"  drawing {', '.join(running)}" if running else "")
                + (f"  {free / 1e9:.1f} GB free" if free is not None else ""))
        _bar = "\r\033[K" + text[:shutil.get_terminal_size((100, 20)).columns - 1]
        sys.stderr.write(_bar)
        sys.stderr.flush()

    def close(self):
        global _bar
        if ON and _bar and _tty():
            sys.stderr.write("\n")
            sys.stderr.flush()
        _bar = ""
