"""Teacher refit of a simplified model (twin experiment).

The original agent model is integrated for a long record (the teacher simulation), and the
drift coefficients of the simplified model are refit by ordinary least squares on the one-step
increments of that record, with the removed terms fixed at zero. Noise, saturation scales,
seasonal phases and means are copied from the original parameters. No observation and no
score enters the fit.
"""
