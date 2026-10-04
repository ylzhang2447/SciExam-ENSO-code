# LiteLLM gateway of the OpenRouter arms (`sciexam run-agent` builds it when the arm's route
# is the gateway). The formal runs used LiteLLM 1.83.9, which is MIT licensed (see NOTICE).
#
# Only the open core is installed, plus the individual open dependencies its proxy server
# needs. The `litellm[proxy]` extra is NOT used: it pulls litellm-enterprise (proprietary
# license) and litellm-proxy-extras (no license metadata). The proxy starts and serves
# /health and /v1 without either, which was checked with exactly these pins.
#
# APPLY_CACHE_USAGE_PATCH=1 applies litellm-stream-cache-usage.patch, the change the gateway
# of the later formal runs carried (see route.gateway_patch in the arm configs).
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

ARG APPLY_CACHE_USAGE_PATCH=0

COPY requirements.txt constraints.txt litellm-stream-cache-usage.patch /tmp/gateway/
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore \
        -r /tmp/gateway/requirements.txt -c /tmp/gateway/constraints.txt \
    && python -c "import importlib.util as u, sys; sys.exit(u.find_spec('litellm_enterprise') is not None or u.find_spec('litellm_proxy_extras') is not None)" \
    && if [ "$APPLY_CACHE_USAGE_PATCH" = "1" ]; then \
         apt-get update && apt-get install -y --no-install-recommends patch \
         && cd "$(python -c 'import litellm, os; print(os.path.dirname(os.path.dirname(litellm.__file__)))')" \
         && patch -p1 --forward < /tmp/gateway/litellm-stream-cache-usage.patch \
         && python -c "import litellm.llms.anthropic.experimental_pass_through.adapters.streaming_iterator" \
         && apt-get purge -y patch && rm -rf /var/lib/apt/lists/*; \
       fi \
    && rm -rf /tmp/gateway

# Use the model cost map bundled with 1.83.9 instead of fetching the current one from the
# network at start-up, so the gateway behaves the same on every rerun.
ENV LITELLM_LOCAL_MODEL_COST_MAP=True

EXPOSE 4000
CMD ["litellm", "--config", "/config.yaml", "--port", "4000"]
