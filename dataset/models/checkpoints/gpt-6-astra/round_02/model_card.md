# Coupled linear ENSO development model

The observable state is `[TC, TE, hW, u, tau]`, in degrees C, degrees C,
meters, meters/second, and meters/second. Internally the respective scales are
`[7.5, 7.5, 150, 1.5, 5]`; one model time unit is two months.

The current development model is `dx = A x ds + B dW`, with a coupled drift
estimated from the January 1980–December 2004 nondimensional monthly indices.
The continuous generator is the matrix logarithm of a fitted monthly propagator;
the diffusion covariance is inferred from its innovations and projected onto the
positive semidefinite cone. The exact linear Gaussian transition implements step.
All randomness comes from the supplied Generator; no observations are loaded at
runtime. The five variables interact through the same equations in free runs and
initialized forecasts. This first fitted version still lacks nonlinear asymmetry
and annual modulation. Those omissions will be examined with the frozen checks.

Physical foundation: Jin (1997), the supplied recharge-oscillator paper. Western
thermocline depth carries ocean memory; warm SST and westerlies discharge it,
and recharge can subsequently warm the surface. No blacklisted reference used.
The 2005–2014 segment has not been used for fitting or validation yet.
