# Seasonal stochastic ENSO recharge and diversity model

The observable state is `[TC, TE, hW, u, tau]`, in degrees C, degrees C,
meters, meters/second, and meters/second. Internally the respective scales are
`[7.5, 7.5, 150, 1.5, 5]`; one model time unit is two months. The western
850-hPa wind index tau is an atmospheric state, not literal surface wind stress.

For nondimensional state x and time s, the model is

    dx = [A(t) x + c + N(x)] ds + B dW,
    A(t) = A + C cos(2 pi t / 12) + S sin(2 pi t / 12).

Here t is calendar time in months, with January at zero. Each SST has a local
nonlinear tendency `q_i (x_i^2 - m2_i) - r_i (x_i^3 - m3_i)`. Central-Pacific
quadratic feedback is negative, eastern-Pacific feedback positive, and both
cubic coefficients are nonnegative. The wind tendency also includes
`wind_q (TC^2 - m2_TC)`. Constants m2 and m3 are training moments in the prescribed
nondimensional units. All coefficients and moments are in the flat params.json.

The coupled drift permits ocean recharge to influence subsequent SST through
thermocline and zonal-current pathways, SST and wind to discharge western heat
content, and SST to drive a damped atmospheric response. The full interaction
matrix represents unresolved spatial processes empirically; individual partial
coefficients are not independently identified causal constants. Two distinct SST
states, their current response, and opposite nonlinear asymmetries permit EP and
CP variability. Annual feedback modulation represents seasonal changes in the
background ocean-atmosphere state. Correlated Gaussian diffusion represents
unresolved shared weather and ocean forcing. Cubic feedback limits SST extremes.

Calibration uses only January 1980–December 2004 processed indices, divided by the
required characteristic scales before fitting. A linear monthly propagator gives
the initial continuous generator; annual modulation and nonlinear coefficients
are fitted by penalized conditional one-month flow regression, with shrinkage of
seasonal and polynomial terms. Diffusion is inferred from monthly innovations.
No 2005–2014 data have yet been used for fitting or validation. The prescribed
1981–2010 anomaly climatology does include some validation years.

step uses symmetric splitting between implicit-midpoint nonlinear evolution and
an exact locally frozen linear Gaussian transition. Seasonal coefficients are
evaluated at the step midpoint; intervals longer than a quarter month are
subdivided. All randomness comes from the supplied NumPy Generator. There are no
hidden state variables, date-specific trajectories, or observation access at
runtime; the same transition drives free runs and initialized forecasts.

Physical foundation: Jin (1997), the supplied recharge-oscillator paper. No
blacklisted reference was accessed. Model extensions and coefficients were built
and estimated here. Frozen diagnostics assess climate, seasonality, events,
memory, coupling, forecasts, and numerical behavior. This is an ongoing development
model; a short observational record limits rare-event and nonlinear identification.
