# update-data (below) needs real outbound internet access to edhrec.com and
# api.scryfall.com to build data/commanders.db -- this only works on a host
# with real network access (e.g. a real deploy target's build servers), not
# in a sandboxed dev environment with restricted egress. Mirrors the root
# Dockerfile's own build-time data bake, for the same reason: no persistent
# disk on a typical free-tier host, so the catalog has to ship inside the
# image rather than being fetched once and reused.
FROM node:22-slim
WORKDIR /app
COPY . .
RUN npm ci && npm run build
# Delete the transient raw caches in the SAME RUN as the fetch -- Docker
# layers are append-only diffs, so deleting them in a later RUN would still
# leave the multi-hundred-MB Scryfall bulk file baked into an earlier layer.
# Only data/commanders.db is needed at runtime -- build_database() already
# resolved every commander's Scryfall image URLs into it at this step.
#
# --discover-sets is required here, not optional -- see the root
# Dockerfile's own comment: without it, commanders.db ships with zero known
# sets on every deploy, no matter what's been discovered on any local
# machine (that data never leaves data/edhrec/, which is gitignored).
RUN node packages/server/dist/cli.js update-data --discover-sets \
    && rm -rf data/scryfall data/edhrec data/edhrec_meta.json
EXPOSE 8000
# `exec` replaces the shell with the node process (PID 1) so it receives
# SIGTERM directly -- see the root Dockerfile's own comment for why this
# matters. ${PORT:-8000} picks up a host's injected PORT env var, falling
# back to 8000 for a plain local `docker run`.
CMD ["sh", "-c", "exec node packages/server/dist/index.js serve --host 0.0.0.0 --port ${PORT:-8000}"]
