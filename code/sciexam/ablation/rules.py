"""Screen and structural vote of the ablation.

A simplified model is compared with the original model of the same agent, both scored by the
grader under the agent's calendar offset.

Screen. A simplified model qualifies when its composite is at least 95% of the original
composite and each component (statistics, physics, predictivity) is at least 90% of the
original component. An original component of zero is passed by any value that is not lower.

Families. A simplified model keeps one of two structures: linear drift with multiplicative noise
(``linear+multiplicative``) or nonlinear drift with additive noise (``nonlinear+additive``).
Other retained structures (for example linear drift with additive noise) take no part in the vote.

Vote. The vote covers the agents whose final composite is at least ``VOTE_MIN_COMPOSITE``. For
each agent and family the cell holds the reduction of that family released in the dataset
(roles ``vote representative``, ``also qualifies`` and ``competing reduction``). When both cells
qualify, the weaker one must reach 95% of the stronger one, otherwise it is dropped. The agent's
vote goes to the qualifying family with the higher composite.
"""

SCREEN_COMPOSITE = 0.95
SCREEN_COMPONENT = 0.90
SECONDARY_RULE = 0.95
VOTE_MIN_COMPOSITE = 0.33
COMPONENTS = ("statistics", "physics", "predictivity")
FAMILIES = ("linear+multiplicative", "nonlinear+additive")
SHORT = {"linear+multiplicative": "lm", "nonlinear+additive": "na"}
CELL_ROLES = ("vote representative", "also qualifies", "competing reduction")
SHOWN_ROLES = ("vote representative", "also qualifies", "automatic endpoint")


def passes(c, o):
    """True when scores ``c`` pass the screen against the original scores ``o``."""
    if c["composite"] < SCREEN_COMPOSITE * o["composite"]:
        return False
    for k in COMPONENTS:
        if o[k] > 0:
            if c[k] < SCREEN_COMPONENT * o[k]:
                return False
        elif c[k] < o[k] - 1e-12:
            return False
    return True


def relative_change_percent(c, o, k="composite"):
    return None if o[k] == 0 else 100.0 * (c[k] / o[k] - 1.0)


def vote_row(arm, display_name, original, candidates):
    """One row of the vote table. ``candidates`` are dicts with candidate, role, family and scores."""
    row = dict(arm=arm, display_name=display_name, vote=None)
    cells = {}
    for fam in FAMILIES:
        cs = [c for c in candidates if c["family"] == fam and c["role"] in CELL_ROLES]
        if len(cs) > 1:
            raise ValueError("%s has %d %s reductions in the vote" % (arm, len(cs), fam))
        cells[fam] = dict(c=cs[0], ok=passes(cs[0], original)) if cs else None
    both = [f for f in FAMILIES if cells[f] and cells[f]["ok"]]
    if len(both) == 2:
        hi, lo = sorted(both, key=lambda f: cells[f]["c"]["composite"], reverse=True)
        if cells[lo]["c"]["composite"] < SECONDARY_RULE * cells[hi]["c"]["composite"]:
            cells[lo]["ok"] = False
    filled = [f for f in FAMILIES if cells[f] and cells[f]["ok"]]
    if filled:
        row["vote"] = max(filled, key=lambda f: cells[f]["c"]["composite"])
    for fam in FAMILIES:
        k = SHORT[fam]
        cell = cells[fam]
        row[k + "_candidate"] = cell["c"]["candidate"] if cell else None
        row[k + "_qualifies"] = bool(cell and cell["ok"])
        row[k + "_relative_change_percent"] = relative_change_percent(cell["c"], original) if cell else None
    return row


def tally(rows):
    return {f: sum(r["vote"] == f for r in rows) for f in FAMILIES}
