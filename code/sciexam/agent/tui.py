"""Terminal prompts for the interactive setup: arrow-key menus with colour, standard library only.

Two backends share one interface (heading, note, select, multiselect, text, confirm):

    Keys    arrow keys, Space and Enter in raw terminal mode, with ANSI colour. Used on a POSIX
            terminal that is not TERM=dumb.
    Plain   numbered choices read with input(). Used when stdin is not a terminal, on Windows,
            with NO_COLOR or SCIEXAM_PLAIN set, and by the tests.
"""
import os
import sys

ORANGE = "\033[38;5;208m"
GREEN = "\033[38;5;71m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K"
HIDE, SHOW = "\033[?25l", "\033[?25h"

# The AI Science Exam logo in line characters: the icon (a slanted stroke fused to a stem, the
# dot above it) and the wordmark, with A drawn as a lambda and E as three bars, as in the logo.
GLYPHS = {
    "A": ["  ╱╲  ", " ╱  ╲ ", "╱    ╲"],
    "I": ["│", "│", "│"],
    "S": ["╭───╴", "╰───╮", "╶───╯"],
    "C": ["╭────", "│    ", "╰────"],
    "E": ["────", "────", "────"],
    "N": ["│╲   │", "│ ╲  │", "│  ╲ │"],
    "X": ["╲   ╱", "  ╳  ", "╱   ╲"],
    "M": ["│╲  ╱│", "│ ╲╱ │", "│    │"],
}
ICON = ["      ●", "     ╱┃", "    ╱ ┃", "   ╱  ┃", "  ╱   ┃"]


def _word(text):
    rows = ["", "", ""]
    for ch in text:
        for r in range(3):
            rows[r] += GLYPHS[ch][r] + " "
    return rows


def logo_lines(color=True):
    """The logo, five rows, SCIENCE and the dot in orange when ``color``."""
    o, b, r = (ORANGE, BOLD, RESET) if color else ("", "", "")
    ai, sci, exam = _word("AI"), _word("SCIENCE"), _word("EXAM")
    out = []
    for k, ic in enumerate(ICON):
        ic = ic.replace("●", o + "●" + r + b) if "●" in ic else ic
        line = "  " + b + ic + r + "    "
        if k >= 2:
            line += b + ai[k - 2] + r + "   " + o + b + sci[k - 2] + r + "   " + b + exam[k - 2] + r
        out.append(line)
    return out


LOGO_WIDTH = 2 + len(ICON[0]) + 4 + sum(len(_word(w)[0]) for w in ("AI", "SCIENCE", "EXAM")) + 6



class Abort(Exception):
    pass


class Back(Exception):
    """Go back to the previous question."""


class Plain:
    """Numbered prompts read with input(). ``ask`` and ``out`` can be replaced for tests."""
    color = False

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
        for i, (label, desc) in enumerate(options, 1):
            self.out("  %d) %-10s %s" % (i, label, desc))
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

    def _draw(self, lines, first):
        if not first:
            self.w.write("\033[%dA" % len(lines))
        for ln in lines:
            self.w.write("\r" + CLEAR_LINE + ln + "\n")
        self.w.flush()

    # ---- the interface ----------------------------------------------------------------------
    def banner(self, subtitle):
        import shutil
        self.w.write("\n")
        if shutil.get_terminal_size((100, 24)).columns >= LOGO_WIDTH:
            for ln in logo_lines():
                self.w.write(ln + "\n")
        else:
            self.w.write("  " + BOLD + ORANGE + "●" + RESET + BOLD + " ΛI " + ORANGE + "SCIENCE" + RESET + BOLD + " ΞXΛM" + RESET + "\n")
        self.w.write("\n  " + BOLD + "SciExam for ENSO" + RESET + DIM + "   Can AI agents build climate models?" + RESET + "\n")
        self.w.write("  " + DIM + subtitle + RESET + "\n")
        self.w.write("  " + DIM + "Arrow keys to move, Enter to choose, left or b to go back, q to quit." + RESET + "\n")
        self.w.flush()

    def heading(self, text):
        self.w.write("\n" + ORANGE + BOLD + text + RESET + "\n")

    def note(self, text):
        self.w.write("  " + DIM + text + RESET + "\n")

    def select(self, question, options, default=0):
        i = default
        self.w.write(BOLD + question + RESET + DIM + "  (up/down, Enter, left to go back)" + RESET + "\n" + HIDE)
        first = True
        try:
            while True:
                lines = []
                for k, (label, desc) in enumerate(options):
                    if k == i:
                        lines.append("  " + ORANGE + BOLD + "> " + label.ljust(10) + RESET + " " + desc)
                    else:
                        lines.append("    " + label.ljust(10) + " " + DIM + desc + RESET)
                self._draw(lines, first)
                first = False
                key = self._key()
                if key == "up":
                    i = (i - 1) % len(options)
                elif key == "down":
                    i = (i + 1) % len(options)
                elif key == "enter":
                    return i
                elif key in ("left", "b", "esc"):
                    raise Back()
                elif key == "q":
                    raise Abort("cancelled")
        finally:
            self.w.write(SHOW)
            self.w.flush()

    def multiselect(self, question, options, default=(0,), names=None):
        on = set(default)
        i = 0
        self.w.write(BOLD + question + RESET + DIM + "  (up/down, Space to tick, a for all, Enter, left to go back)"
                     + RESET + "\n" + HIDE)
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
                lines.append(DIM + "  %d selected" % len(on) + RESET)
                self._draw(lines, first)
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
                elif key in ("left", "b", "esc"):
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
