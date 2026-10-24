#!/bin/sh
# Install SciExam in one folder you choose, then run `sciexam start`.
#
#   sh install.sh                       from a checkout of this repository (uses it in place)
#   curl -fsSL <url>/install.sh | sh    anywhere (clones the repository into the folder)
#
# It finds Python 3.10 or newer, asks where to keep everything (default ~/sciexam), says what it
# will do and waits for your yes. Everything goes into that folder: the Python environment, the
# code (when cloned), and later the dataset, the runs and your credentials. Nothing outside it is
# changed, except a link to the `sciexam` command and one PATH line, each asked for separately.
# To uninstall, delete the folder (and the link, if you made one).
#
# Options: --home DIR (skip the question), --yes (accept every default), --no-link.
# SCIEXAM_REPO and SCIEXAM_BRANCH choose what is cloned.
set -eu

REPO_URL="${SCIEXAM_REPO:-https://github.com/ylzhang2447/SciExam-ENSO-code.git}"
BRANCH="${SCIEXAM_BRANCH:-main}"
DEST=""
YES=0
LINK=1

while [ $# -gt 0 ]; do
    case "$1" in
        --home) DEST="$2"; shift 2 ;;
        --yes|-y) YES=1; shift ;;
        --no-link) LINK=0; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see --help)"; exit 2 ;;
    esac
done

say() { printf '%s\n' "$*"; }
bold() { printf '\033[1m%s\033[0m\n' "$*"; }

# Answers come from the terminal even when the script itself arrives on stdin (curl | sh).
ask() {    # ask QUESTION DEFAULT -> ANSWER
    if [ "$YES" = 1 ]; then printf '%s' "$2"; return; fi
    printf '%s [%s]: ' "$1" "$2" > /dev/tty
    read -r ans < /dev/tty || ans=""
    printf '%s' "${ans:-$2}"
}
yes_no() {  # yes_no QUESTION -> 0 for yes (the default)
    a=$(ask "$1 (Y/n)" "y")
    case "$a" in [Nn]*) return 1 ;; *) return 0 ;; esac
}

bold "SciExam for ENSO: install"

# 1. Python 3.10 or newer
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" > /dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2> /dev/null; then
        PY=$(command -v "$c"); break
    fi
done
if [ -z "$PY" ]; then
    say "SciExam needs Python 3.10 or newer, and none was found."
    case "$(uname -s)" in
        Darwin) say "  The python3 that comes with macOS is 3.9. Install a newer one with Homebrew:"
                say "    brew install python@3.12"
                say "  or from https://www.python.org/downloads/ , then run this installer again." ;;
        *)      say "  For example: sudo apt install python3.12 python3.12-venv"
                say "  then run this installer again." ;;
    esac
    exit 1
fi
PYV=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')

# 2. The code: this checkout, or a clone into the folder
CHECKOUT=""
here=$(cd "$(dirname "$0")" 2> /dev/null && pwd || true)
if [ -n "$here" ] && [ -f "$here/code/pyproject.toml" ]; then CHECKOUT="$here"; fi

# 3. The folder
if [ -z "$DEST" ]; then
    DEST=$(ask "Where should SciExam keep its files?" "$HOME/sciexam")
fi
case "$DEST" in "~"*) DEST="$HOME${DEST#\~}" ;; esac
case "$DEST" in /*) ;; *) DEST="$(pwd)/$DEST" ;; esac
case "$DEST" in *"'"*|*'"'*) say "Please choose a folder whose name has no quote characters."; exit 2 ;; esac
if [ -d "$DEST" ] && [ -n "$(ls -A "$DEST" 2> /dev/null)" ] && [ ! -f "$DEST/.sciexam-home" ]; then
    say "$DEST already holds other files. SciExam would add env/, data/, runs/ and more next to them."
    yes_no "Use it anyway?" || exit 1
fi

# 4. Say what will happen, then wait for a yes
say ""
bold "This will:"
say "  - create $DEST/env, a Python environment (Python $PYV, $PY)"
if [ -n "$CHECKOUT" ]; then
    say "  - use the code in $CHECKOUT (where it is)"
else
    say "  - download the code into $DEST/code ($REPO_URL, $BRANCH)"
fi
say "  - install SciExam and the packages it needs (numpy, scipy, pandas, xarray, netCDF4) from PyPI"
say "  - write $DEST/sciexam, the command that runs SciExam with this folder"
say "Nothing outside $DEST is changed without asking you first."
say ""
yes_no "Go ahead?" || { say "Nothing was installed."; exit 1; }

mkdir -p "$DEST"
: > "$DEST/.sciexam-home"
if [ -n "$CHECKOUT" ]; then
    CODE="$CHECKOUT"
elif [ -d "$DEST/code/.git" ]; then
    CODE="$DEST/code"
    say "updating $CODE"
    git -C "$CODE" pull --ff-only -q
else
    command -v git > /dev/null 2>&1 || { say "git is needed to download the code (macOS: xcode-select --install)."; exit 1; }
    say "downloading the code..."
    git clone -q --depth 1 -b "$BRANCH" "$REPO_URL" "$DEST/code"
    CODE="$DEST/code"
fi
say "creating the Python environment..."
"$PY" -m venv "$DEST/env"
"$DEST/env/bin/python" -m pip install -q --upgrade pip
say "installing SciExam (a minute or two)..."
"$DEST/env/bin/python" -m pip install -q -e "$CODE/code"

cat > "$DEST/sciexam" <<EOF
#!/bin/sh
# SciExam, with everything kept in $DEST (written by install.sh)
SCIEXAM_HOME='$DEST'
export SCIEXAM_HOME
exec '$DEST/env/bin/sciexam' "\$@"
EOF
chmod +x "$DEST/sciexam"
CMD="$DEST/sciexam"

# 5. Optional: the sciexam command in every terminal
if [ "$LINK" = 1 ]; then
    BIN="$HOME/.local/bin"
    say ""
    if yes_no "Make the sciexam command work in every terminal? (adds the link $BIN/sciexam)"; then
        mkdir -p "$BIN"
        ln -sf "$DEST/sciexam" "$BIN/sciexam"
        CMD="sciexam"
        case ":$PATH:" in
            *":$BIN:"*) ;;
            *)  case "${SHELL:-}" in
                    */zsh) RC="$HOME/.zshrc" ;;
                    */bash) if [ "$(uname -s)" = Darwin ]; then RC="$HOME/.bash_profile"; else RC="$HOME/.bashrc"; fi ;;
                    *) RC="$HOME/.profile" ;;
                esac
                LINE='export PATH="$HOME/.local/bin:$PATH"'
                if yes_no "$BIN is not on your PATH yet. Add the line  $LINE  to $RC?"; then
                    printf '\n# added by the SciExam installer\n%s\n' "$LINE" >> "$RC"
                    say "Open a new terminal window for it to take effect."
                else
                    CMD="$DEST/sciexam"
                fi ;;
        esac
    fi
fi

say ""
bold "Installed in $DEST"
say "Next, run:"
say ""
say "  $CMD start"
say ""
say "It checks what a run needs (Docker, the data, the paper, your model account), helps with"
say "whatever is missing, then sets up the run."
