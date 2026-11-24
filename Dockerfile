# syntax=docker/dockerfile:1

ARG ALPINE_VERSION=3.24.2

FROM alpine:${ALPINE_VERSION}

# squashfuse: the xattr segfault fix (vasi/squashfuse#149) first shipped in 0.6.3. Alpine's stable
# repositories still carry 0.6.1, so this one package comes from `edge` (tagged repository, so
# nothing else is taken from it). Drop this block once the stable release has >= 0.6.3.
RUN echo "@edge https://dl-cdn.alpinelinux.org/alpine/edge/community" >> /etc/apk/repositories \
    && apk add --no-cache "squashfuse@edge>=0.6.3" \
    && apk info -v squashfuse

RUN apk add --no-cache \
    apptainer ca-certificates libseccomp squashfs-tools fuse2fs fuse-overlayfs gocryptfs \
    python3 py3-pip git git-annex openssh-client curl bzip2 bash jq 7zip tzdata uv

# faire lives in its own virtualenv; the patched squashfuse comes first on PATH
ENV PATH=/opt/faire/bin:/opt/squashfuse/bin:$PATH
COPY . /src/faire
RUN uv venv /opt/faire --python /usr/bin/python3 \
 && uv pip install --python /opt/faire/bin/python /src/faire \
 && rm -rf /src/faire \
 && faire --help >/dev/null \
 && apptainer --version \
 && git-annex version >/dev/null

ENTRYPOINT ["faire"]
CMD ["--help"]
