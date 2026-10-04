# Phase 2A instrumentation baseline — uncalibrated

The five states are TC, TE, hW, u, tau in the dimensional units required by
interface.md. Each independently obeys dx = -x/L dt + s sqrt(2/L) dW, with
L=6 months and stationary standard deviations s=(0.7 C, 1 C, 15 m, 0.15 m/s,
2 m/s). These are round, hand-chosen test values; no parameters were fitted.
The implementation scales state internally by the supplied characteristic scales
(7.5 C, 7.5 C, 150 m, 1.5 m/s, 5 m/s) and uses an exact OU transition in months.
All noise comes from the caller's NumPy Generator. The same step drives all checks.

This intentionally simple stochastic baseline makes the default diagnostics
executable before their freeze. It has no recharge coupling, seasonal modulation,
nonlinearity or physical ENSO diversity mechanism. Its shortcomings are expected to
be measured by the instruments. Replace it when the modeling phase is authorized;
this is not a calibrated scientific submission. The reserved 2005–2014 record has
not been used for calibration or diagnostic evaluation.
