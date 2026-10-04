# 5D reference model (not an agent submission, not ranked)

The five-variable stochastic ENSO model identified by Zhang, Chen, Vialard and Fang (2024,
J. Climate 37(23), arXiv:2402.04585), Appendix 8.2 ("interannual intraseasonal model with
advection"), with the coefficients of Table 4, written in the submission interface for this
benchmark. Five state variables (T_C, T_E, h_W, u, tau), no hidden index. Nondimensional to
physical scales [T] = 7.5 K, [h] = 150 m, [u] = 1.5 m/s, [tau] = 5.

The only adjustment is t_shift = -1 month in `params.json`, a calendar alignment: the paper's
seasonal phase is defined under a convention that labels model time t as calendar month t, while
the grader's free run labels it as month t - 1. It changes which calendar month model time zero is
called, nothing about the dynamics.
