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
- E: `K[tanh(z+a_E E+a_H H)-m_T] - r_E(E³-m3_E)`.
- H: `q_H(E²-m2_E)`; u: zero additional nonlinear tendency.
- tau: `q_W(C²-m2_C)` plus
  `A_tau,tau(t) g_W L_W[logcosh(tau/L_W)-m_W]`.

Positive thermal sensitivities transmit recharge into SST growth. Wind-driven
heat discharge and current transport close the delayed negative feedback.
Central and eastern bounded feedbacks have different curvature, allowing central
warm saturation and stronger eastern warm events. Winds respond to both SST
regions, whose different thermal responses permit central/eastern diversity.
The fitted additional spatial wind-heating gate is zero. Positive cubic damping
limits large SST excursions. Asymmetric wind relaxation permits longer westerly
anomalies. Centering constants are training means of the indicated functions.

In thermocline-scaled units, stored heat H and observed depth obey
`hW = H - eta[sqrt(H²+L_H²)-L_H]`, with eta=0.08427. This smooth invertible
response has a positive bounded derivative and compresses deep positive D20
excursions. It adds no state. The physical hW equation follows Ito's formula:
its drift is f'(H)b_H + f''(H)Q_HH/2 and diffusion is f'(H)B_H.

A fitted lower-triangular diffusion factor represents correlated unresolved
forcing. Positive annual/semiannual row modulation supplies seasonal noise.
Forcing is additive in the core coordinates. The optional independent-wind
activity coefficients are zero: conditional wind variance already changes through
nonlinear coupled dynamics. All noise is drawn from the caller's Generator.

Calibration uses only 1980–2004. Slow drift coefficients use regularized joint
conditional mean/covariance likelihood at one, three and six months, estimated
with 128-path simulations of the core step and finite-record martingale
constraints. Fast coefficients retain one-month conditional-flow calibration;
diffusion uses conditional covariance likelihood at one, three and six months. The heat response likelihood includes its coordinate
Jacobian. The later supplied decade was consulted in four explicitly logged groups of development
forecasts and was never fitted; it is not an untouched test set. The fixed
1981–2010 anomaly climatology overlaps that decade. Jin (1997), supplied with the task, provides the
recharge mechanism; these stochastic and nonlinear closures were constructed here.
A final unfitted simplification removed explicit SST-dependent wind-noise activity:
the frozen training checks found it overstated warm/cold wind variance differences
without materially changing SST climate or forecasts.

The integrator composes implicit nonlinear midpoint steps with exact seasonal
linear stochastic transitions, subdividing increments above a quarter month.
Heat coordinates are transformed exactly. Caches contain only deterministic
transition factors. Free runs and forecasts use the same five-state step.
Frozen checks find reproducible transitions, finite 500-year stress runs, and both
SST ensemble means beating persistence at the tested one-to-twelve-month leads
in training. Its parent with state-dependent wind activity also beat persistence
in the reserved decade, but long-lead eastern forecasts were worse than zero
anomaly, with insufficient ensemble coverage and persistent central-SST innovations.
The final noise simplification has not been queried on that decade. Weak eastern extremes, excess central events, imperfect
winter locking, excessive SST–heat innovation correlation and weak long recharge
memory remain. The few observed cycles limit inference; matching individual
checks is insufficient.
