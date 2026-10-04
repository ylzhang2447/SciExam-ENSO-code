"""Rebuild the task inputs that are not redistributed with the dataset.

* ``sciexam prepare-data`` downloads the public NOAA observations that the agents received as
  raw data, rebuilds the five monthly indices with the task's data processing recipe and
  compares them with the reference indices in the dataset (``download``, ``indices``).
* ``sciexam fetch-paper`` explains how to obtain the reference paper given to the agents and
  checks and installs a copy supplied by the user (``paper``).
"""
