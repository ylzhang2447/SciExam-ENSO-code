# Coupled stochastic recharge oscillator

The state is `(TC, TE, hW, u, tau)` in the dimensional units required by the
interface. Internally it is divided by the supplied scales `(7.5 degC, 7.5 degC,
150 m, 1.5 m/s, 5 m/s)`. Time remains in months; equivalently, all monthly rates
can be multiplied by two when expressed in the supplied two-month time unit.

The baseline equation is the multivariate stochastic differential equation

`dz = G (z - zbar) dt + L dW`,

integrated with Euler--Maruyama. The full, non-diagonal drift is essential: warm
SST excites westerly wind anomalies, wind and eastern SST discharge western heat
content, western heat content drives the current, and thermocline/current/wind
feedbacks act differently on central and eastern SST. This produces two coupled
SST expressions of a shared recharge oscillator rather than independent curves.
The fitted slow complex mode is damped and is continually excited by weather
noise. Correlated innovations represent unresolved atmospheric and oceanic
forcing shared among variables.

Coefficients were estimated only from January 1980--December 2004. A fitted
one-month transition was converted to a quarter-month Euler generator, and the
innovation covariance was converted consistently to quarter-month diffusion.
No post-2004 value was used to estimate a coefficient.
