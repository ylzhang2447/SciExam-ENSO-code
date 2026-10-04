# ENSOModel model card

This submission is a five-variable stochastic recharge-oscillator model for the
dimensional state `[TC, TE, hW, u, tau]`.

The step method converts the state to nondimensional variables using
`nondim_scales.json`: SST by 7.5 C, thermocline by 150 m, current by 1.5 m/s, wind
by 5 m/s.  In nondimensional monthly time it advances an Euler-Maruyama system:

`dx = (c + A x + nonlinear damping/asymmetry) dt + L dW`.

The matrix `A` and intercept `c` are fitted from the processed monthly 1980-2014
indices as one-month tendencies.  The stochastic term uses the fitted residual
covariance Cholesky factor plus month-of-year and variable-specific amplitude
factors, state-dependent SST and hW noise, a small shared SST noise mode, plus a
seasonally locked independent CP-diversity stochastic mode that can separate TC from TE.  The linear core couples
western-Pacific recharge, SST, current, and wind response; the nonlinearity adds
amplitude saturation, warm-TE, thresholded extreme warm-TE growth, cold-TE,
cold-TC, discharged-thermocline asymmetry, thresholded warm-event discharge of hW,
and mild SST damping so long free runs remain finite and produce ENSO diversity
rather than one unbounded mode.

All parameters are in `params.json`; `step` is the only dynamical source used for
free runs and forecasts.
