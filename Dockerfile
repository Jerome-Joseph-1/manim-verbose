# The manim editor's rendering backend, as a container for Google Cloud Run (see
# docs/editor/HOSTING.md). It runs `manimgl-editor --hosted`: no file on disk, documents kept
# in each visitor's browser, hosted-mode limits and rate limits. The browser UI is served from
# Vercel and forwards /api and /files here, so this image only needs the server and a renderer.
#
# Two stages: a Node stage builds the UI into the package's static/ folder, and an Ubuntu
# stage installs the system renderers (LaTeX, Pango, Mesa's software Vulkan, ffmpeg, dvisvgm)
# and the Python package. Ubuntu 24.04 is the base because scripts/ci/apt/*.txt — the package
# set CI verifies against the default TeX template and the wgpu renderer — is pinned to it.

# ---- Stage 1: build the browser editor -------------------------------------------------
FROM node:22-slim AS ui
WORKDIR /src
# Install dependencies against the lockfile first, so this layer is cached across UI edits
COPY editor-ui/package.json editor-ui/package-lock.json ./editor-ui/
RUN cd editor-ui && npm ci
# Vite writes the build into ../manim_verbose/editor/static (see editor-ui/vite.config.ts),
# so both folders have to be present with their real layout
COPY editor-ui ./editor-ui
COPY manim_verbose/editor ./manim_verbose/editor
RUN cd editor-ui && npm run build

# ---- Stage 2: the runtime image --------------------------------------------------------
FROM ubuntu:24.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MANIM_VERBOSE_HOSTED=1 \
    XDG_CACHE_HOME=/tmp/cache

# System packages the renderer needs. The apt/*.txt lists say why each is there and are what
# CI installs; --no-install-recommends keeps the image to what is actually used.
#   python3 / pip / build tools   run and build the package (manimpango builds from source)
#   pango, cairo, glib headers    manimpango (text)
#   mesa-vulkan-drivers, libvulkan software Vulkan, so the wgpu renderer has an adapter
#   texlive-*, cm-super, tipa     the default TeX template (scripts/ci/apt/tex.txt)
#   dvisvgm                       DVI -> SVG
#   fonts-cmu                     CMU Serif, the font the example videos use
#   ffmpeg                        encoding video
COPY scripts/ci/apt /tmp/apt
RUN set -eux; \
    packages="$(cat /tmp/apt/pango.txt /tmp/apt/vulkan.txt /tmp/apt/tex.txt /tmp/apt/ffmpeg.txt \
        | sed 's/#.*//' | tr -s '[:space:]' '\n' | grep -v '^$')"; \
    echo "man-db man-db/auto-update boolean false" | debconf-set-selections; \
    apt-get update -q; \
    apt-get install -y -q --no-install-recommends \
        python3 python3-pip python3-venv python3-dev build-essential pkg-config \
        ca-certificates fonts-cmu \
        $packages; \
    rm -rf /var/lib/apt/lists/* /tmp/apt; \
    # TeX Live ships documentation and sources the renderer never reads; dropping them saves
    # over a gigabyte without changing a single rendered pixel.
    rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/* \
           /usr/share/texlive/texmf-dist/doc /usr/share/texlive/texmf-dist/source \
           /usr/share/texmf/doc /var/cache/apt/archives/*.deb

# The Python package. Copy metadata first so the dependency layer is cached across code edits.
WORKDIR /app
COPY setup.cfg setup.py pyproject.toml MANIFEST.in README.md requirements.txt ./
COPY manimlib ./manimlib
COPY manim_verbose ./manim_verbose
# The built UI from stage 1, so the package ships with static/ in place
COPY --from=ui /src/manim_verbose/editor/static ./manim_verbose/editor/static
# Ubuntu 24.04's pip refuses to touch the system environment without this; the container is
# single-purpose, so a venv would only add a layer of indirection.
RUN pip install --no-cache-dir --break-system-packages ".[editor]"

# Run as a non-root user. Renders write only to /tmp (XDG_CACHE_HOME), which stays writable.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /tmp/cache && chown -R app:app /tmp/cache
USER app

# Cloud Run sends requests to $PORT (8080 by default); hosted mode binds 0.0.0.0:$PORT.
ENV PORT=8080
EXPOSE 8080

# A plain healthcheck for local runs; Cloud Run uses its own startup/liveness probes.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python3 -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/health', timeout=4).status==200 else 1)"

CMD ["manimgl-editor", "--hosted"]
