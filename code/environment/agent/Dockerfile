# Agent image of `sciexam run-agent`.
#
# Ubuntu 24.04 pinned by digest, Node.js and the Python packages pinned by sha256, and ONE
# agent CLI, which is installed at build time from its official source with a pinned version
# and a sha256 check. No CLI is stored in this repository. The Claude Code and Antigravity
# CLIs are proprietary and are used under their own terms with the user's own sign-in, so an
# image built from this file is for local use and must not be pushed to a public registry.
#
# Build arguments (run-agent passes them from agents/<arm>.yaml):
#   CLAUDE_CODE_VERSION, CLAUDE_CODE_SHA256   npm @anthropic-ai/claude-code, sha256 of bin/claude.exe
#   CODEX_VERSION, CODEX_SHA256               npm @openai/codex (Apache-2.0), sha256 of bin/codex.js
#   ANTIGRAVITY_URL, ANTIGRAVITY_SHA256       official Antigravity CLI binary (Linux x64) and its sha256
#
# The system packages, the Python stack and Node.js 22.23.2 match the image of the formal
# runs (whose Python packages were numpy 2.5.1, scipy 1.18.0, pandas 3.0.5, xarray 2026.7.0,
# netCDF4 1.7.4). There is deliberately no PDF renderer, as in the formal image.
FROM ubuntu@sha256:008173c23f95b170204355c12626cb5a965d779a7e1283b09e9cffbb1bf33ca3

ARG NODE_VERSION=22.23.2
ARG NODE_SHA256=d60acfe00a2932254bb0ad20e01b0d74397a0875595de719654b214f4b03f307
ARG CLAUDE_CODE_VERSION=
ARG CLAUDE_CODE_SHA256=
ARG CODEX_VERSION=
ARG CODEX_SHA256=
ARG ANTIGRAVITY_URL=
ARG ANTIGRAVITY_SHA256=

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y curl ca-certificates python3 python3-pip git xz-utils \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN curl -fsSLo /tmp/node.tar.xz \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    && echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/node.tar.xz -C /usr --strip-components=1 \
           --exclude CHANGELOG.md --exclude LICENSE --exclude README.md \
    && rm /tmp/node.tar.xz && node --version && npm --version

COPY requirements.lock /tmp/requirements.lock
RUN pip3 install --break-system-packages --no-cache-dir --require-hashes --no-deps \
        --only-binary=:all: -r /tmp/requirements.lock \
    && rm /tmp/requirements.lock \
    && python3 -c "import numpy, scipy, pandas, xarray, netCDF4"

RUN set -e; n=0; \
    if [ -n "$CLAUDE_CODE_VERSION" ]; then \
      n=$((n+1)); [ -n "$CLAUDE_CODE_SHA256" ] || { echo "CLAUDE_CODE_SHA256 is required"; exit 1; }; \
      npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"; \
      f="$(readlink -f "$(command -v claude)")"; \
      echo "${CLAUDE_CODE_SHA256}  $f" | sha256sum -c -; \
    fi; \
    if [ -n "$CODEX_VERSION" ]; then \
      n=$((n+1)); [ -n "$CODEX_SHA256" ] || { echo "CODEX_SHA256 is required"; exit 1; }; \
      npm install -g "@openai/codex@${CODEX_VERSION}"; \
      f="$(readlink -f "$(command -v codex)")"; \
      echo "${CODEX_SHA256}  $f" | sha256sum -c -; \
    fi; \
    if [ -n "$ANTIGRAVITY_URL" ]; then \
      n=$((n+1)); [ -n "$ANTIGRAVITY_SHA256" ] || { echo "ANTIGRAVITY_SHA256 is required"; exit 1; }; \
      curl -fsSLo /usr/local/bin/agy "$ANTIGRAVITY_URL"; \
      echo "${ANTIGRAVITY_SHA256}  /usr/local/bin/agy" | sha256sum -c -; \
      chmod 755 /usr/local/bin/agy; \
    fi; \
    [ "$n" -eq 1 ] || { echo "set exactly one of CLAUDE_CODE_VERSION, CODEX_VERSION, ANTIGRAVITY_URL"; exit 1; }; \
    npm cache clean --force >/dev/null 2>&1 || true

WORKDIR /work
CMD ["sleep", "infinity"]
