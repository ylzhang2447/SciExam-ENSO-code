# Seasonal stochastic ENSO recharge and diversity model

State order is `[TC, TE, hW, u, tau]`, in degrees C, degrees C, meters,
meters/second, and meters/second. Internal scales are `[7.5, 7.5, 150, 1.5, 5]`;
one nondimensional time unit is two months. Tau is the observed western-Pacific
850-hPa zonal wind anomaly, used as an atmospheric forcing index, not literal
surface wind stress. January corresponds to t=0; only the annual phase is used.

For nondimensional state x and time s:

    dx = [A(t) x + c + N(x)] ds + D(t) B dW
    A(t) = A + C cos(2 pi t/12) + S sin(2 pi t/12) + R(t)
    N_C = q_C (C^2-m2_C) - r_C (C^3-m3_C) - adv_C (u C - m_uC)
    N_E = q_E (E^2-m2_E) - r_E (E^3-m3_E) - adv_E (u (E-C) - m_uGrad)
          + A_E,tau(t) g [tau tanh((E-C)/L) - m_gate]
    N_h = recharge_q (E^2-m2_E)
    N_u = 0
    N_tau = wind_q (C^2-m2_C)

R(t) is diagonal on the two SST coordinates, with separately fitted second
annual harmonics; it allows different seasonal rates of event growth and decay.
The bounded spatial gate g changes eastern heating by western winds according
to whether SST anomalies extend eastward or remain central. Its width L is the
training SST-contrast scale. The effective wind coefficient remains positive;
the gate reduces it for central-dominated warm anomalies and strengthens it for
eastern-dominated ones. m_gate removes the training-mean anomalous heat flux.
The current fit has adv_C=adv_E=0. The opposite SST quadratic signs represent
central warm saturation and eastern warm amplification; nonnegative cubic
coefficients limit growth. Negative recharge_q represents stronger heat discharge
in intense eastern warm events. Centering moments are training-data moments in
the prescribed nondimensional units; no observations are loaded at runtime.

The atmosphere responds directly to TC and TE and relaxes toward that response;
direct hW and u atmospheric terms are zero in the current fit. Recharge influences
winds through surface temperature. The ocean current and thermocline retain their
own dynamics, coupling wind, SST, and stored heat. Full ocean drift coefficients
are empirical closures for spatially unresolved processes, not independently
identified causal constants. Two distinct surface temperatures and their different
nonlinearities support eastern and central variability within one coupled system.

D(t) is a positive diagonal modulation of noise amplitude, with log amplitudes
containing annual and semiannual harmonics; those coefficients are zero in the
current fit. B permits correlated unresolved weather/ocean forcing. All coefficients
are explicit scalar entries in params.json. The same equations drive initialized
forecasts and free runs; there are no hidden dynamical states or date-specific paths.

Calibration uses January 1980–December 2004 only, after division by the mandatory
physical scales. Penalized regression fits conditional means at 1, 3, and 6 months;
Gaussian moment equations account approximately for noise-induced nonlinear mean
shifts during fitting; one-dimensional Gaussian quadrature handles the spatial
gate. Weak generator equations also regularize training distribution and seasonal
moments. Atmospheric coefficients are first fitted at one month, then held fixed
while fitting the slower ocean evolution. Current errors enter directly at one month.
Diffusion is inferred from monthly innovations. The reserved 2005–2014 period was
first examined for earlier linear and nonlinear models, revealing long-lead warm
bias despite improvement over persistence; it is not used in coefficient fitting.
Repeated use for selection would reduce its independence. The required 1981–2010
anomaly climatology already includes some reserved years.

step uses symmetric splitting: implicit-midpoint nonlinear half-steps and a locally
exact linear Gaussian transition evaluated at the seasonal midpoint. Intervals
longer than a quarter month are subdivided. All noise comes from the caller's
NumPy Generator. Frozen diagnostics assess distributions, seasonality, events,
memory, coupling, forecasts, and numerics. Current development limitations include
weak interannual memory and imperfect seasonal phase locking; the short training
record poorly identifies rare events and nonlinear terms.

Physical foundation: Jin (1997), the supplied recharge-oscillator paper. The
stochastic, nonlinear, seasonal, and diversity extensions and their parameters
were constructed and estimated here. No blacklisted reference was accessed.
