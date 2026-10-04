"""Simplified models whose teacher refit this release can rerun.

Each entry names the drift basis of the original model, the removed terms (equation index,
term name) and the teacher simulation that produced the released parameters.
"""
TEACHER = dict(years=20000.0, burn=200.0, chains=16, dt=0.1, seed=1)

REFITS = {
    ("fable51", "S3_affine_periodic_drift"): dict(
        basis="fable51",
        knockout=[(0, "b_TC_c"), (0, "b_TC_s"), (0, "n_TC"), (0, "q_TC"), (0, "qw_TC"),
                  (1, "b_TE_c"), (1, "b_TE_s"), (1, "n_TE"), (1, "q_TE"), (1, "q_TE_season"),
                  (2, "g_hW_c"), (2, "g_hW_s"), (2, "n_hW"), (2, "q_hW"),
                  (3, "u_hW_c"), (3, "u_hW_s")],
        teacher=TEACHER),
}
