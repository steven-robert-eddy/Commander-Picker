# update-data (below) needs real outbound internet access to edhrec.com and
# api.scryfall.com to build data/commanders.db -- this only works on a host
# with real network access (e.g. Render's build servers), not in a sandboxed
# dev environment with restricted egress. See PLAN.md Phase 6.
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
# Delete the transient raw caches in the SAME RUN as the fetch -- Docker
# layers are append-only diffs, so deleting them in a later RUN would still
# leave the multi-hundred-MB Scryfall bulk file baked into an earlier layer.
# Only data/commanders.db is needed at runtime: build_database() already
# resolved every commander's Scryfall image URLs into it at this step, so
# the app never touches data/scryfall/ again once this RUN completes.
#
# --discover-sets is required here, not optional: there's no persistent
# disk on Render's free tier (see PLAN.md), so commanders.db -- and with
# it the commander_sets table the Set filter reads from -- is rebuilt
# from nothing on every single deploy. Without this flag, set_slugs stays
# unset the whole way through and every deploy ships with zero known
# sets, no matter what's been discovered on any local machine (that
# data never leaves data/edhrec/, which is gitignored). This does add a
# few hundred speculative EDHREC requests to each build.
RUN commander-picker update-data --discover-sets \
    && rm -rf data/scryfall data/edhrec data/edhrec_meta.json
EXPOSE 8000
# `exec` replaces the shell with the uvicorn process (PID 1) so it receives
# SIGTERM directly -- without it, `sh` doesn't forward signals and a
# shutdown/restart hangs until the hard SIGKILL timeout. ${PORT:-8000}
# picks up Render's injected PORT env var, falling back to 8000 for a plain
# local `docker run`.
CMD ["sh", "-c", "exec commander-picker serve --host 0.0.0.0 --port ${PORT:-8000}"]
