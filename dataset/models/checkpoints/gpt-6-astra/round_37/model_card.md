# Coupled stochastic ENSO model

The observable state is `[TC, TE, hW, u, tau]`, in °C, °C, m, m/s, m/s.
Tau is western-Pacific 850-hPa zonal wind, used as an atmospheric forcing index.
Internal units are `[7.5, 7.5, 150, 1.5, 5]`, with two months per time unit.
Only annual calendar phase enters; January is t=0.

In core coordinates x=(C,E,H,u,tau), the Ito system is
`dx = [A(t)x+c+N(x,t)] ds + diffusion(x,t) dW`.
A(t) contains annual sine/cosine coefficients and second harmonics of the two
SST self-feedbacks. Flat JSON entries give every coefficient in these units.
The active nonlinear tendencies are:

- C: `K_C[tanh(z_C+a_C C)-m_C] - r_C(C³-m3_C)`.
- E: `K[tanh(z+a_E E+a_H H)-m_T] - r_E(E³-m3_E)` plus
  `A_E,tau(t) g[tau tanh((E-C)/L)-m_g]`.
- H: `q_H(E²-m2_E)`; u: zero additional nonlinear tendency.
- tau: `q_W(C²-m2_C)` plus
  `A_tau,tau(t) g_W L_W[logcosh(tau/L_W)-m_W]`.

Positive thermal sensitivities transmit recharge into SST growth. Wind-driven
heat discharge and current transport close the delayed negative feedback.
Central and eastern bounded feedbacks have different curvature, allowing central
warm saturation and stronger eastern warm events. The spatial wind-heating gate
reduces eastern amplification when warming stays central. Positive cubic damping
limits large SST excursions. Asymmetric wind relaxation permits longer westerly
anomalies. Centering constants are training means of the indicated functions.

Stored heat H and observed thermocline depth obey
`hW = H - eta[sqrt(H²+L_H²)-L_H]`, with eta=0.08427. This smooth invertible
response has a positive bounded derivative and compresses deep positive D20
excursions. It adds no state. The physical hW equation follows Ito's formula:
its drift is f'(H)b_H + f''(H)Q_HH/2 and diffusion is f'(H)B_H.

A fitted lower-triangular diffusion factor represents correlated unresolved
forcing. Positive annual/semiannual row modulation supplies seasonal noise.
The independent wind channel also has bounded activity
`exp(tanh(b_C C+b_E E))`. All noise is drawn from the caller's Generator.

Calibration uses only 1980–2004: regularized conditional means at one, three, six and twelve months, estimated
with 256-path simulations of the core step, finite-record martingale constraints,
and one-month conditional
covariance likelihood. The heat response likelihood includes its coordinate
Jacobian. The later supplied decade was consulted sparingly for development
forecasts and was never fitted. Jin (1997), supplied with the task, provides the
recharge mechanism; these stochastic and nonlinear closures were constructed here.

The integrator composes implicit nonlinear midpoint steps with exact seasonal
linear stochastic transitions, subdividing increments above a quarter month.
Heat coordinates are transformed exactly. Caches contain only deterministic
transition factors. Free runs and forecasts use the same five-state step.
Frozen checks find finite stress runs and SST forecast improvement over
persistence, but excess eastern warm values, imperfect winter locking and weak
long recharge memory remain. Earlier versions’ long-lead eastern forecasts in the reserved decade
were worse than a zero-anomaly forecast; matching individual checks is insufficient.
