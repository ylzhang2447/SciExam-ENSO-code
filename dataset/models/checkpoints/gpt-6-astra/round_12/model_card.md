# Seasonal coupled stochastic ENSO model

State order is `[TC, TE, hW, u, tau]`, in degrees C, degrees C, meters,
meters/second, and meters/second. Internal characteristic scales are
`[7.5, 7.5, 150, 1.5, 5]`; one nondimensional time unit is two months.
Tau is the western-Pacific 850-hPa zonal wind anomaly, used as an atmospheric
forcing index, not literal surface stress. January is t=0; only calendar phase
enters the dynamics.

For nondimensional state x and time s:

    dx = [A(t) x + c + N(x)] ds + D(t) B dW
    A(t) = A + C cos(2 pi t/12) + S sin(2 pi t/12) + R(t)
    N_C = q_C (C^2-m2_C) - r_C (C^3-m3_C)
    N_E = q_E (E^2-m2_E) - r_E (E^3-m3_E)
    N_h = recharge_q (E^2-m2_E)
    N_u = 0
    N_tau = wind_q (C^2-m2_C)

R(t) adds independent second annual harmonics to the two SST self-feedbacks.
Opposite quadratic SST signs represent central warm saturation and eastern warm
amplification; nonnegative cubic terms limit SST growth. Negative recharge_q
allows stronger discharge during intense eastern warm events. Centering moments
are estimated from training data in the required nondimensional units.

Eastern heating also includes
`A_E,tau(t) g [tau tanh((E-C)/L)-m_gate]`, with g=0.2122 and
L=0.09052 in nondimensional SST units. This bounded spatial feedback
reduces wind-driven eastern warming for central-dominated warm anomalies and
strengthens it when anomalies extend eastward. The effective seasonal wind
coefficient remains positive. m_gate removes the training-mean anomalous heat
flux. L is the training SST-contrast scale, not a hidden-state coordinate.

The atmosphere responds directly to the two SST states and relaxes toward that
response; direct hW and u atmospheric coefficients are zero. Recharge affects
winds through SST. Ocean current and thermocline each retain their own dynamics,
connecting winds, surface temperature, and stored heat. Ocean drift coefficients
are empirical closures for unresolved spatial processes; they represent net
feedbacks, not independently identified gross heat-exchange or causal constants.

Distinct SST states and asymmetric feedbacks permit central and eastern variability
within the same coupled system. Correlated Gaussian diffusion represents shared
unresolved weather and ocean forcing.
D(t) is diagonal and positive, with annual and semiannual harmonics in its
log noise amplitudes.

All coefficients are scalar entries in params.json. The same transition drives
free simulation and initialized forecasts. There are no hidden prognostic states,
absolute-year lookups, saved trajectories, or observation access at runtime.

Calibration uses January 1980–December 2004 indices, divided by the mandatory
physical scales before fitting. Numerical standardization afterward is only a
regression preconditioner; stored parameters are converted back to the prescribed
nondimensional coordinates.
Penalized conditional-mean regression fits leads 1,3,6 months.
Gaussian moment equations account approximately for noise-induced mean shifts.
One-dimensional Gaussian quadrature treats the bounded spatial feedback during fitting.
Atmospheric coefficients were estimated at one month and held fixed during the
slower ocean fit; direct current-error fitting also uses one month.
Weak generator identities regularize training moments, covariance, and seasonal variance.
Diffusion is fitted by nonlinear one-month conditional Gaussian likelihood, with
a positive-definite covariance parameterization.

Reserved 2005–2014 forecasts were examined during development, but those indices
never enter coefficient fitting. Such model-selection use reduces the independence
of the reserved period. The prescribed 1981–2010 anomaly climatology also includes
some reserved years. No later observations or blacklisted reference was accessed.

step uses symmetric splitting: implicit-midpoint nonlinear evolution and a locally
exact linear Gaussian transition at the seasonal midpoint. Steps longer than a
quarter month are subdivided. All random draws use the supplied NumPy Generator.
Frozen diagnostics assess distributions, seasonality, events, memory, coupling,
forecasts, and numerical behavior. The short record limits identification of rare
events and nonlinear processes; agreement with individual checks is not evidence
of complete climate fidelity or reliable long-lead prediction.

Physical foundation: Jin (1997), the supplied recharge-oscillator paper. The
stochastic, nonlinear, seasonal, and diversity extensions and their parameters
were constructed and estimated here; no complete published diversity model or
calibrated parameter table was used.
