"""Custom network settings of a rerun (`sciexam run-agent --network`, `--allow-host`).

The formal runs gave the agent container the model endpoint of its route and PyPI, through the
allowlist proxy. A rerun may tighten that (``no-pypi``: the model endpoint only) or add hosts to
the allowlist. Either change is recorded under ``custom`` and makes the run not comparable with
the paper. The web conditions use the research proxy instead and take neither option.
"""
import copy
import re

NETWORKS = ("paper", "no-pypi")
HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)+$")


class CustomError(ValueError):
    pass


def hosts_from(values):
    out = []
    for v in values or []:
        for h in [x.strip().lower() for x in v.split(",") if x.strip()]:
            if not HOST.match(h):
                raise CustomError("%r is not a host name (example: data.example.org)" % h)
            if h not in out:
                out.append(h)
    return out


def apply(arm, network=None, allow_hosts=None):
    network = network or "paper"
    if network not in NETWORKS:
        raise CustomError("--network must be one of %s" % ", ".join(NETWORKS))
    hosts = hosts_from(allow_hosts)
    if network == "paper" and not hosts:
        return arm
    if (arm.get("condition") or {}).get("network") == "research":
        raise CustomError("%s uses the research proxy, which takes no --network or --allow-host"
                          % arm["arm"])
    out = copy.deepcopy(arm)
    custom = out.setdefault("custom", {})
    if network == "no-pypi":
        out["network"]["pypi"] = False
        custom["network"] = "no-pypi: model endpoint only"
    if hosts:
        out["network"]["agent_allow_hosts"] = list(out["network"]["agent_allow_hosts"]) + [
            h for h in hosts if h not in out["network"]["agent_allow_hosts"]]
        custom["extra_allowed_hosts"] = hosts
    custom["comparable_with_paper"] = False
    return out
