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
Bounded central feedback represents central warm saturation; nonnegative
cubic terms limit SST growth. Eastern asymmetry uses bounded thermocline heating. Negative recharge_q
allows stronger discharge during intense eastern warm events. Centering moments
are estimated from training data in the required nondimensional units.

Eastern heating also includes
`A_E,tau(t) g [tau tanh((E-C)/L)-m_gate]`, with g=0.1662 and
L=0.09052 in nondimensional SST units. This bounded spatial feedback
reduces wind-driven eastern warming for central-dominated warm anomalies and
strengthens it when anomalies extend eastward. The effective seasonal wind
coefficient remains positive. m_gate removes the training-mean anomalous heat
flux. L is the training SST-contrast scale, not a hidden-state coordinate.

Eastern thermocline heating additionally uses
`K [tanh(z0 + a_E E + a_h hW) - m_thermo]`, with positive K, a_E, a_h.
The offset z0 is negative, allowing warm amplification before entrainment
temperature saturates. The combination of western stored heat and eastern SST
is an empirical proxy for the eastern subsurface thermal state. Direct linear
hW-to-TE coefficients and the local eastern quadratic term are zero in this
version: thermocline sensitivity comes from this monotone bounded response.
A nonnegative eastern cubic term retains dissipative growth control. The
centering constant m_thermo is estimated from the training states.

Central SST feedback includes K_C[tanh(z_C+a_C C)-m_C], with positive K_C,
a_C, and z_C. This bounded response limits central warm amplification and
permits stronger cold excursions. The local central quadratic is zero; cubic
damping retains far-field growth control. The term is an empirical net local
thermodynamic feedback, distinct from the eastern subsurface-temperature closure.

Wind relaxation includes `A_tau,tau(t) g_w L_w [log(cosh(tau/L_w))-m_w]`.
With negative seasonal wind self-feedback and |g_w|<1, relaxation remains
restoring. Positive g_w damps westerlies more strongly; negative g_w damps
easterlies more strongly and permits greater westerly persistence.
The width and centering moment come from training winds; g_w is fitted at one month.

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

The independent wind-forcing channel (the last column of lower-triangular B) is
additionally multiplied by `exp(tanh(noise_state_C C+noise_state_E E))`.
This bounded weather-activity response is estimated from conditional innovation
likelihood. Other independent forcing channels retain their specified activities. The SDE
uses the Ito convention: activity is evaluated before each random increment.

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
Current and atmospheric coefficients were estimated at one month and held fixed
during the slower SST/recharge fit.
Weak generator identities regularize training moments, covariance, and seasonal variance.
Joint martingale covariance, with mild correlation shrinkage, weights those identities.
Trapezoidal path integrals retain the observed endpoint terms in the generator identities.
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
