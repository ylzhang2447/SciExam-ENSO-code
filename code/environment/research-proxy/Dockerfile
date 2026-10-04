# Web research proxy of the web-access conditions (sciexam/agent/research).
#
# mitmproxy 12.1.2 with the three decoders the policy needs to inspect a body in full: a PDF
# reader (a PDF is read to text on every page, or refused) and brotli and zstandard (a
# compressed body is inspected in its decoded form). The policy scripts are not part of the
# image: run-agent mounts sciexam/agent/research read only, so the image does not change when
# the configuration of a run does.
FROM mitmproxy/mitmproxy:12.1.2@sha256:0d7b2a14b4a71a908cd6f31b8f50e29bbc5c8720fe6caa706acf782da558e5c7

RUN pip install --no-cache-dir "pypdf==6.1.1" "brotli==1.1.0" "zstandard==0.23.0" \
    && mitmdump --version | grep -q "Mitmproxy: 12.1.2" \
    && python3 -c "import pypdf, brotli, zstandard"
