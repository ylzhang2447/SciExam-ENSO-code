"""The five-variable ENSO model identified by Zhang, Chen, Vialard and Fang (2024, J. Climate
37(23), arXiv:2402.04585), Appendix section 8.2, "the interannual intraseasonal model with
advection" (Ia Is M A), with the coefficients of Table 4.

This is the output of that paper's auto-learning (model identification) framework, not the
hand-written model that generated its training data. It has exactly the five
state variables the benchmark asks for and NO hidden index I.

    du/dt   = L11 u + L12 tau + L13                                     + su  dWu
    dhW/dt  = L21 hW + L22 TC + L23 TE + L24 tau + L25                  + sh  dWh
    dTC/dt  = L31 u + L32 hW + L33(t) TC + L34 TE + L35 tau
              + L36(t) TC^2 + L37(t) TC^3 + L38                         + sC  dWC
    dTE/dt  = L41 hW + L42 TC + L43(t) TE + L44 tau + L45               + sE  dWE
    dtau/dt = L51 tau + L52                                  + stau(TC, t) dWtau

    L33(t) = L33 + L33s1 s1        L36(t) = L36 + L36s1 s1
    L37(t) = L37 + L37s1 s1        L43(t) = L43 + L43s2 s2 + L43s3 s3
    s1 = sin(2 pi t / 6)      s2 = sin(2 pi t / 6 + 2 pi / 6)      s3 = sin(2 pi t / 3 + 2 pi / 6)
    stau(TC, t) = 0.8999 [tanh(4.5 TC) + 1] [1 + 0.25 cos(2 pi t / 6)]

Time is the paper's model time: one year is 6 units, so one month is 0.5 units.
State is nondimensional; the wrapper converts with the paper scales
[T] = 7.5 K, [h] = 150 m, [u] = 1.5 m/s, [tau] = 5, which are also the scales of the grader.

The DEFAULTS below agree with every printed digit of Table 4 (28 of 28 coefficients).
Editing any of them is a deliberate departure from the published model.
"""
import json
from pathlib import Path

import numpy as np
from numba import njit

SCALES = np.array([7.5, 7.5, 150.0, 1.5, 5.0])   # [TC, TE, hW, u, tau] nondim -> physical
MONTH = 0.5                                       # model-time units per month
DT_MAX = 0.001                                    # native integration step, model time

# Table 4 of arXiv:2402.04585
DEFAULTS = dict(
    t_shift=0.0,
    # du/dt
    L11=-0.13998544912, L12=-0.0427857411805, L13=4.98431422787e-05,
    # dhW/dt
    L21=-0.148061996968, L22=-0.0500779194423, L23=-0.0456040749808, L24=-0.0792842368412, L25=3.82303282352e-05,
    # dTC/dt
    L31=0.218314249808, L32=0.42216948661, L33=-0.406071888331, L33s1=-0.298873738257,
    L34=0.245516538205, L35=0.156757297168,
    L36=-2.87209683462, L36s1=-1.11403445853,
    L37=-14.5992483488, L37s1=-5.60332350924,
    L38=0.0165737376013,
    # dTE/dt
    L41=0.4446375841, L42=-0.274128026111, L43=-0.055319306278, L43s2=-0.359680073336, L43s3=-0.179149525529,
    L44=0.197636043194, L45=0.000101392091971,
    # dtau/dt
    L51=-1.99422904731, L52=0.00445302845042,
    # noise
    su=0.0309888938984, sh=0.0154862207803, sC=0.0309939817235, sE=0.0232457728546,
    tau_amp=0.899858418603, tau_gain=4.5, tau_seas=0.25,
)

_ORDER = ["L11", "L12", "L13",
          "L21", "L22", "L23", "L24", "L25",
          "L31", "L32", "L33", "L33s1", "L34", "L35", "L36", "L36s1", "L37", "L37s1", "L38",
          "L41", "L42", "L43", "L43s2", "L43s3", "L44", "L45",
          "L51", "L52",
          "su", "sh", "sC", "sE", "tau_amp", "tau_gain", "tau_seas"]


# cache=False on purpose: the grader loads this file through importlib with a synthetic
# module name, and numba's on-disk cache cannot resolve that on reload.
@njit(cache=False)
def _advance(TC, TE, hW, u, tau, noise, dt, nsub, t0,
             L11, L12, L13,
             L21, L22, L23, L24, L25,
             L31, L32, L33, L33s1, L34, L35, L36, L36s1, L37, L37s1, L38,
             L41, L42, L43, L43s2, L43s3, L44, L45,
             L51, L52,
             su, sh, sC, sE, tau_amp, tau_gain, tau_seas):
    """Advance an ensemble of nondimensional states by nsub Euler-Maruyama sub-steps."""
    sq = np.sqrt(dt)
    w1 = 2.0 * np.pi / 6.0          # annual
    w2 = 2.0 * np.pi / 3.0          # semiannual
    ph = 2.0 * np.pi / 6.0
    n = TC.shape[0]
    for s in range(nsub):
        t = t0 + s * dt
        s1 = np.sin(w1 * t)
        s2 = np.sin(w1 * t + ph)
        s3 = np.sin(w2 * t + ph)
        cC = L33 + L33s1 * s1
        c2 = L36 + L36s1 * s1
        c3 = L37 + L37s1 * s1
        cE = L43 + L43s2 * s2 + L43s3 * s3
        seas = 1.0 + tau_seas * np.cos(w1 * t)
        for k in range(n):
            up = u[k]; hp = hW[k]; Cp = TC[k]; Ep = TE[k]; tp = tau[k]
            u[k]   = up + (L11 * up + L12 * tp + L13) * dt + su * sq * noise[0, s, k]
            hW[k]  = hp + (L21 * hp + L22 * Cp + L23 * Ep + L24 * tp + L25) * dt \
                     + sh * sq * noise[1, s, k]
            TC[k]  = Cp + (L31 * up + L32 * hp + cC * Cp + L34 * Ep + L35 * tp
                           + c2 * Cp * Cp + c3 * Cp * Cp * Cp + L38) * dt \
                     + sC * sq * noise[2, s, k]
            TE[k]  = Ep + (L41 * hp + L42 * Cp + cE * Ep + L44 * tp + L45) * dt \
                     + sE * sq * noise[3, s, k]
            stau = tau_amp * (np.tanh(tau_gain * Cp) + 1.0) * seas
            tau[k] = tp + (L51 * tp + L52) * dt + stau * sq * noise[4, s, k]


class ENSOModel:
    """Grader-facing wrapper. state is (5, n) in physical units, order [TC, TE, hW, u, tau]."""

    def __init__(self, params=None):
        self.p = dict(DEFAULTS)
        if params:
            self.p.update({k: v for k, v in params.items() if k in DEFAULTS})

    def step(self, state, dt_months, t, rng):
        x = np.asarray(state, float)
        squeeze = (x.ndim == 1)
        if squeeze:
            x = x.reshape(5, 1)
        n = x.shape[1]
        nd = x / SCALES[:, None]                       # physical -> nondimensional
        TC = np.ascontiguousarray(nd[0]); TE = np.ascontiguousarray(nd[1])
        hW = np.ascontiguousarray(nd[2]); u = np.ascontiguousarray(nd[3])
        tau = np.ascontiguousarray(nd[4])

        dt_model = float(dt_months) * MONTH
        nsub = max(1, int(np.ceil(abs(dt_model) / DT_MAX - 1e-12)))
        dt = dt_model / nsub
        noise = rng.standard_normal((5, nsub, n))
        p = self.p
        _advance(TC, TE, hW, u, tau, noise, dt, nsub,
                 (float(t) + p["t_shift"]) * MONTH,
                 *[float(p[k]) for k in _ORDER])

        out = np.vstack([TC, TE, hW, u, tau]) * SCALES[:, None]
        return out[:, 0] if squeeze else out

