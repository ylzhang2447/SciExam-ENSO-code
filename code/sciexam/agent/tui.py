"""Terminal prompts for the interactive setup: arrow-key menus with colour, standard library only.

Two backends share one interface (heading, note, select, multiselect, text, confirm):

    Keys    arrow keys, Space and Enter in raw terminal mode, with ANSI colour. Used on a POSIX
            terminal that is not TERM=dumb.
    Plain   numbered choices read with input(). Used when stdin is not a terminal, on Windows,
            with NO_COLOR or SCIEXAM_PLAIN set, and by the tests.
"""
import os
import re
import shutil
import sys

ORANGE = "\033[38;5;208m"
GREEN = "\033[38;5;71m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K"
HIDE, SHOW = "\033[?25l", "\033[?25h"
_ANSI = re.compile(r"(\033\[[0-9;?]*[A-Za-z])")


def clip(line, width):
    """``line`` cut to ``width`` visible characters (colour codes kept, not counted), ending in an
    ellipsis when it was cut. A menu line must never wrap: the redraw moves up one row per line."""
    out, n, cut = [], 0, False
    for tok in _ANSI.split(line):
        if _ANSI.fullmatch(tok):
            out.append(tok)
        elif not cut:
            if n + len(tok) > width:
                tok, cut = tok[:max(0, width - n - 1)] + "\u2026", True
            out.append(tok)
            n += len(tok)
    return "".join(out) + (RESET if cut else "")


def label_width(options):
    """The width of a menu's label column: its longest label, at least 10."""
    return max([10] + [len(label) for label, _ in options])


def bar(done, total, width=30):
    """A text progress bar: [████████······]  57%  103 of 180 MB."""
    frac = min(1.0, done / total) if total else 0.0
    n = int(round(frac * width))
    return "[%s%s] %3d%%  %.0f of %.0f MB" % ("\u2588" * n, "\u00b7" * (width - n), frac * 100,
                                            done / 1e6, total / 1e6)


def window(lines, focus, rows):
    """At most ``rows`` of ``lines``: all of them when they fit, else a slice around ``focus``
    between two lines that count what is above and below. Always ``rows`` long once it scrolls,
    so every redraw covers the same rows."""
    if len(lines) <= rows:
        return lines
    n = max(1, rows - 2)
    start = min(max(0, focus - n // 2), len(lines) - n)
    above, below = start, len(lines) - start - n
    return ([DIM + ("  \u2191 %d more" % above if above else "") + RESET] + lines[start:start + n]
            + [DIM + ("  \u2193 %d more" % below if below else "") + RESET])

LOGO = [r"   ____       _ _____",
        r"  / ___|  ___(_) ____|_  ____ _ _ __ ___",
        r"  \___ \ / __| |  _| \ \/ / _` | '_ ` _ \ ",
        r"   ___) | (__| | |___ >  < (_| | | | | | |",
        r"  |____/ \___|_|_____/_/\_\__,_|_| |_| |_|"]
# The AI Science Exam icon in the same lettering: a slanted stroke fused to a stem, the dot above.
ICON = [r"        (_)",
        r"       / /|",
        r"      / / |",
        r"     / /| |",
        r"    /_/ |_|"]


def logo_lines(color=True):
    """The icon beside the SciExam lettering, five rows. With ``color`` the stroke is bold and
    the dot and the lettering are orange."""
    o, b, r = (ORANGE, BOLD, RESET) if color else ("", "", "")
    out = []
    for ic, lt in zip(ICON, LOGO):
        ic = ic.replace("(_)", o + b + "(_)" + r) if "(_)" in ic else b + ic + r
        out.append(ic + " " * (12 - len(ICON[0])) + "  " + o + b + lt + r)
    return out


LOGO_WIDTH = 14 + max(len(x) for x in LOGO)



class Abort(Exception):
    pass


class Back(Exception):
    """Go back to the previous question."""


class Plain:
    """Numbered prompts read with input(). ``ask`` and ``out`` can be replaced for tests."""
    color = False
    at_start = False      # the first question: there is nothing to go back to, so back is ignored

    def __init__(self, ask=input, out=print):
        self.ask_fn, self.out = ask, out

    def _ask(self, question, default=""):
        hint = " [%s]" % default if default != "" else ""
        try:
            ans = self.ask_fn("%s%s: " % (question, hint)).strip()
        except EOFError:
            raise Abort("input closed")
        if ans.lower() in ("q", "quit", "exit"):
            raise Abort("cancelled")
        if ans.lower() in ("b", "back"):
            if self.at_start:
                self.out("  this is the first question")
                return self._ask(question, default)
            raise Back()
        return ans or default

    def banner(self, subtitle):
        self.out(subtitle)
        self.out("Enter accepts the value in brackets, b goes back, q quits.")

    def heading(self, text):
        self.out("\n" + text + "\n" + "-" * len(text))

    def note(self, text):
        self.out("  " + text)

    def select(self, question, options, default=0):
        """options: list of (label, description). Returns the chosen index."""
        w = label_width(options)
        for i, (label, desc) in enumerate(options, 1):
            self.out("  %d) %s %s" % (i, label.ljust(w), desc))
        while True:
            ans = self._ask(question, str(default + 1))
            if ans.isdigit() and 1 <= int(ans) <= len(options):
                return int(ans) - 1
            self.out("  please enter a number from 1 to %d" % len(options))

    def multiselect(self, question, options, default=(0,), names=None):
        """options: list of (label, description). Returns the chosen indices, in list order.
        Accepts numbers or, when ``names`` is given, those names, separated by commas."""
        for i, (label, desc) in enumerate(options, 1):
            self.out("  %2d) %-32s %s" % (i, label, desc))
        names = names or []
        while True:
            ans = self._ask(question, ",".join(str(i + 1) for i in default))
            picked, bad = [], None
            for item in [x.strip() for x in ans.split(",") if x.strip()]:
                if item.isdigit() and 1 <= int(item) <= len(options):
                    picked.append(int(item) - 1)
                elif item in names:
                    picked.append(names.index(item))
                else:
                    bad = item
            if bad is not None:
                self.out("  unknown choice %r" % bad)
            elif not picked:
                self.out("  choose at least one")
            else:
                return sorted(set(picked), key=picked.index)

    def text(self, question, default="", check=None):
        while True:
            ans = self._ask(question, default)
            err = check(ans) if check else None
            if not err:
                return ans
            self.out("  " + err)

    def page(self):
        """Start a new page: numbered prompts just go on below."""
        self.out("")

    def progress(self, done, total):
        """Progress of a download: numbered prompts print a line at every tenth."""
        step = int(10 * done / total) if total else 0
        if step != getattr(self, "_step_shown", -1) or done >= total:
            self._step_shown = step
            self.out("  " + bar(done, total))
        if done >= total:
            self._step_shown = -1

    def secret(self, question):
        """A value that must not be echoed (an API key): read with getpass on a terminal."""
        if self.ask_fn is input:
            import getpass
            return getpass.getpass(question + ": ")
        return self.ask_fn(question + ": ")

    def confirm(self, question, default=False):
        while True:
            ans = self._ask(question + " (y/n)", "y" if default else "n").lower()
            if ans in ("y", "yes"):
                return True
            if ans in ("n", "no"):
                return False
            self.out("  please answer y or n")


class Keys(Plain):
    """Arrow-key menus in raw terminal mode."""
    color = True

    def __init__(self):
        super().__init__()
        self.w = sys.stdout
        self._drawn = 0
        self._size = None
        self._subtitle = None     # the banner, and the current step's heading and notes, are kept
        self._step = []           # so that a resize can draw the whole page again

    # ---- terminal plumbing ------------------------------------------------------------------
    def _key(self):
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 1)
            if ch == b"\x1b":
                seq = os.read(fd, 2)
                return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left"}.get(seq, "esc")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch == b" ":
            return "space"
        if ch in (b"\x03", b"\x04"):
            raise KeyboardInterrupt
        return ch.decode(errors="ignore").lower()

    def _draw(self, lines, first, focus=0, footer=None, header=None):
        """Draw a menu, or redraw it over the last one: clipped to the width and scrolled to fit
        the height, so it takes exactly one row per line however narrow the terminal is. After
        the terminal was resized the rows drawn before may have wrapped, so the screen is cleared
        and the menu drawn again from the top instead of over them."""
        size = tuple(shutil.get_terminal_size((100, 24)))
        cols, rows = size
        if not first and size != self._size:
            self.w.write("\033[H\033[2J")
            if self._subtitle is not None:
                self._banner()
            for ln in self._step:
                self.w.write(ln + "\n")
            first = True
        self._size = size
        top = [header] if header else []
        shown = window(lines, focus, max(3, rows - 3 - len(top) - (1 if footer else 0)))
        shown = [clip(ln, max(10, cols - 1)) for ln in top + shown + ([footer] if footer else [])]
        if not first and self._drawn:
            self.w.write("\033[%dA" % self._drawn)
        for ln in shown:
            self.w.write("\r" + CLEAR_LINE + ln + "\n")
        extra = self._drawn - len(shown) if not first else 0
        for _ in range(max(0, extra)):                # a shorter menu after a resize
            self.w.write("\r" + CLEAR_LINE + "\n")
        if extra > 0:
            self.w.write("\033[%dA" % extra)
        self._drawn = len(shown)
        self.w.flush()

    # ---- the interface ----------------------------------------------------------------------
    def banner(self, subtitle):
        self._subtitle = subtitle
        self._banner()
        self.w.flush()

    def _banner(self):
        subtitle = self._subtitle
        self.w.write("\n")
        if shutil.get_terminal_size((100, 24)).columns >= LOGO_WIDTH:
            for ln in logo_lines():
                self.w.write(ln + "\n")
        else:
            self.w.write("  " + ORANGE + BOLD + "SciExam" + RESET + "\n")
        self.w.write("\n  " + BOLD + "SciExam for ENSO" + RESET + DIM + "   Can AI agents build climate models?" + RESET + "\n")
        self.w.write("  " + DIM + subtitle + RESET + "\n")
        self.w.write("  " + DIM + "Arrow keys to move, Enter to choose, left or b to go back, q to quit." + RESET + "\n")

    def page(self):
        """Start a new page: clear the screen and draw the banner again, so that a checklist shown
        after each step replaces the last one instead of piling up below it."""
        self.w.write("\033[H\033[2J")
        if self._subtitle is not None:
            self._banner()
        self._step = []
        self.w.flush()

    def progress(self, done, total):
        """One bar redrawn in place on its line, ended with a newline once complete."""
        cols = shutil.get_terminal_size((100, 24)).columns
        width = max(10, min(40, cols - 30))
        self.w.write("\r" + CLEAR_LINE + "  " + GREEN + bar(done, total, width) + RESET)
        if total and done >= total:
            self.w.write("\n")
        self.w.flush()

    def heading(self, text):
        self._step = ["", ORANGE + BOLD + text + RESET]
        self.w.write("\n" + ORANGE + BOLD + text + RESET + "\n")

    def note(self, text):
        self._step.append("  " + DIM + text + RESET)
        self.w.write("  " + DIM + text + RESET + "\n")

    def select(self, question, options, default=0):
        i = default
        w = label_width(options)
        header = BOLD + question + RESET + DIM + "  (up/down, Enter, left to go back)" + RESET
        self.w.write(HIDE)
        first = True
        try:
            while True:
                lines = []
                for k, (label, desc) in enumerate(options):
                    if k == i:
                        lines.append("  " + ORANGE + BOLD + "> " + label.ljust(w) + RESET + " " + desc)
                    else:
                        lines.append("    " + label.ljust(w) + " " + DIM + desc + RESET)
                self._draw(lines, first, focus=i, header=header)
                first = False
                key = self._key()
                if key == "up":
                    i = (i - 1) % len(options)
                elif key == "down":
                    i = (i + 1) % len(options)
                elif key == "enter":
                    return i
                elif key in ("left", "b", "esc") and not self.at_start:
                    raise Back()
                elif key == "q":
                    raise Abort("cancelled")
        finally:
            self.w.write(SHOW)
            self.w.flush()

    def multiselect(self, question, options, default=(0,), names=None):
        on = set(default)
        i = 0
        header = (BOLD + question + RESET + DIM + "  (up/down, Space to tick, a for all, Enter, "
                  "left to go back)" + RESET)
        self.w.write(HIDE)
        first = True
        try:
            while True:
                lines = []
                for k, (label, desc) in enumerate(options):
                    mark = GREEN + "(*)" + RESET if k in on else DIM + "( )" + RESET
                    if k == i:
                        lines.append("  " + ORANGE + BOLD + ">" + RESET + " " + mark + " "
                                     + ORANGE + BOLD + label.ljust(32) + RESET + " " + desc)
                    else:
                        style = "" if k in on else DIM
                        lines.append("    " + mark + " " + style + label.ljust(32) + " " + desc + RESET)
                self._draw(lines, first, focus=i, footer=DIM + "  %d selected" % len(on) + RESET,
                           header=header)
                first = False
                key = self._key()
                if key == "up":
                    i = (i - 1) % len(options)
                elif key == "down":
                    i = (i + 1) % len(options)
                elif key == "space":
                    on.symmetric_difference_update({i})
                elif key == "a":
                    on = set() if len(on) == len(options) else set(range(len(options)))
                elif key == "enter" and on:
                    return sorted(on)
                elif key in ("left", "b", "esc") and not self.at_start:
                    raise Back()
                elif key == "q":
                    raise Abort("cancelled")
        finally:
            self.w.write(SHOW)
            self.w.flush()

    def text(self, question, default="", check=None):
        while True:
            hint = DIM + " [%s]" % default + RESET if default != "" else ""
            try:
                ans = input(BOLD + question + RESET + hint + DIM + " (b back)" + RESET + ": ").strip()
            except EOFError:
                raise Abort("input closed")
            if ans.lower() in ("q", "quit"):
                raise Abort("cancelled")
            if ans.lower() in ("b", "back"):
                raise Back()
            ans = ans or default
            err = check(ans) if check else None
            if not err:
                return ans
            self.w.write("  " + ORANGE + err + RESET + "\n")

    def confirm(self, question, default=False):
        k = self.select(question, [("Yes", ""), ("No", "")], 0 if default else 1)
        return k == 0


def backend():
    """Keys on a POSIX terminal, Plain otherwise."""
    if (os.name == "posix" and sys.stdin.isatty() and sys.stdout.isatty()
            and os.environ.get("TERM", "") not in ("", "dumb")
            and not os.environ.get("NO_COLOR") and not os.environ.get("SCIEXAM_PLAIN")):
        return Keys()
    return Plain()
