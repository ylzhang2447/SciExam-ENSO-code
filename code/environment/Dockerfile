# Grading environment for SciExam-ENSO.
# Ubuntu 24.04 (pinned by digest) with its Python 3.12 and wheels pinned by sha256.
# The grader code itself is mounted read only at run time (see sciexam/grader/sandbox.py).
FROM ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock /tmp/requirements.lock
RUN pip3 install --break-system-packages --require-hashes --no-deps --only-binary=:all: \
        -r /tmp/requirements.lock \
    && rm /tmp/requirements.lock \
    && python3 -c "import numpy, scipy, pandas, xarray, netCDF4, numba; print(numpy.__version__, scipy.__version__, numba.__version__)"

ENV HOME=/tmp NUMBA_CACHE_DIR=/tmp/numba PYTHONPATH=/opt/sciexam
WORKDIR /tmp
CMD ["python3"]
