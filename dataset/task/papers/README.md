# Reference paper (given to the agent)

This provides the foundational mechanism only. It does not contain a stochastic,
nonlinear, or ENSO-diversity model; building those parts is your task.

- **Jin_1997_Recharge_Oscillator_Part1_ConceptualModel_JAS.pdf**
  Jin, F.-F. (1997). An Equatorial Ocean Recharge Paradigm for ENSO. Part I:
  Conceptual Model. J. Atmos. Sci., 54, 811-829. The foundational recharge-discharge
  oscillator: the growth (Bjerknes) and phase-transition (recharge) mechanisms, as a
  single-region, linear, deterministic two-variable (T, h) model. It has NO stochastic
  forcing, NO nonlinearity (no quadratic/cubic/multiplicative-noise terms), NO
  seasonality, and NO ENSO diversity. You must add the stochastic forcing, the
  nonlinearity that produces El Nino / La Nina asymmetry, the seasonal phase locking,
  and the two-region (Central vs Eastern Pacific) diversity yourself, and calibrate
  everything to the observed indices.

Reviews or papers that already give the full nonlinear stochastic ENSO-diversity model
(its equations and/or parameter tables) are out of scope; see ../blacklist.txt.
