"""The reference paper given to the agents, which is not redistributed.

The agents' ``papers/`` folder held one PDF: Jin, F.-F., 1997: An Equatorial Ocean Recharge
Paradigm for ENSO. Part I: Conceptual Model. J. Atmos. Sci., 54(7), 811-829. The article is
under the publisher's copyright and may need a subscription, so the dataset only cites it
(``task/papers/CITATION.md``). ``sciexam fetch-paper --file PATH`` checks that a copy obtained
by the user is byte for byte the file the agents read (sha256 below) and puts it where the task
tree expects it.
"""
import hashlib
import shutil
from pathlib import Path

CITATION = ("Jin, F.-F., 1997: An Equatorial Ocean Recharge Paradigm for ENSO. Part I: "
            "Conceptual Model. J. Atmos. Sci., 54(7), 811-829.")
DOI = "10.1175/1520-0469(1997)054<0811:AEORPF>2.0.CO;2"
DOI_URL = "https://doi.org/10.1175/1520-0469(1997)054%3C0811:AEORPF%3E2.0.CO%3B2"
FILE_NAME = "Jin_1997_Recharge_Oscillator_Part1_ConceptualModel_JAS.pdf"
SHA256 = "1744dc982436ba76217846e813b67aab6143a4d3d029a00aa4ed840b9c243be3"
SIZE = 283092     # bytes
REL_DEST = Path("papers") / FILE_NAME     # inside the task folder


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def instructions(task_dir):
    dest = Path(task_dir) / REL_DEST
    return "\n".join([
        "Reference paper given to the agents (not redistributed, publisher copyright):",
        "",
        "  " + CITATION,
        "  DOI " + DOI,
        "  " + DOI_URL,
        "",
        "Download the PDF from the publisher (a subscription may be needed), then run",
        "",
        "  sciexam fetch-paper --file /path/to/downloaded.pdf [--task-dir %s]" % task_dir,
        "",
        "The file must be the publisher PDF the agents read:",
        "  sha256 %s (%d bytes)" % (SHA256, SIZE),
        "It is copied to %s, the place the task tree expects" % dest,
        "(the agents saw it as papers/%s next to papers/README.md)." % FILE_NAME,
        "A PDF with another sha256 (for example a different download or a reprint) is reported",
        "and not copied unless --accept-different is given.",
    ])


def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def install(src, task_dir, forbidden=(), accept_different=False, log=print):
    """Check ``src`` against the recorded sha256 and copy it to ``task_dir/papers/``.
    Returns 0 on success, 1 when the file differs and is not copied, 2 on a usage error."""
    src = Path(src)
    if not src.is_file():
        log("error: no file at %s" % src)
        return 2
    dest = Path(task_dir) / REL_DEST
    for root in forbidden:
        if root and _inside(dest, root):
            log("error: %s is inside %s. Choose a task folder outside the dataset and the code "
                "(the paper is not redistributed, and an extra file would break the dataset manifest)."
                % (dest, root))
            return 2
    got = sha256(src)
    if got == SHA256:
        log("sha256 matches the PDF the agents read (%s)" % SHA256)
    else:
        log("sha256 of %s is %s (%d bytes)" % (src, got, src.stat().st_size))
        log("expected     %s (%d bytes), the PDF the agents read" % (SHA256, SIZE))
        if not accept_different:
            log("not copied. The content may still be the same article (publishers re-render PDFs). "
                "Pass --accept-different to install it anyway.")
            return 1
        log("installing it anyway (--accept-different)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    log("copied to %s" % dest)
    return 0
