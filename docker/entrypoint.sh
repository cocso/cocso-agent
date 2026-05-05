#!/usr/bin/env bash
#
# COCSO Agent docker entrypoint.
#
# Runs as root to remap the internal `cocso` user (UID/GID 10000) to the
# host user that owns the bind-mounted ~/.cocso volume. Without this
# remap, files created inside the container show up as UID 10000 on the
# host and become unreadable by the actual host user.
#
# Pass the desired host UID/GID via the COCSO_UID / COCSO_GID env
# vars (docker-compose.yml does this automatically).
#
# After remapping, drops privileges via gosu and exec's the cocso CLI
# with whatever arguments docker passed (CMD or `docker run ... <args>`).
#

set -euo pipefail

TARGET_UID="${COCSO_UID:-10000}"
TARGET_GID="${COCSO_GID:-10000}"

CURRENT_UID="$(id -u cocso)"
CURRENT_GID="$(id -g cocso)"

if [[ "${TARGET_GID}" != "${CURRENT_GID}" ]]; then
    groupmod -o -g "${TARGET_GID}" cocso
fi

if [[ "${TARGET_UID}" != "${CURRENT_UID}" ]]; then
    usermod -o -u "${TARGET_UID}" cocso
fi

# Make the data volume writable by the (possibly remapped) cocso user.
# Best-effort: the volume might be a read-only bind mount, in which case
# we skip and let cocso surface the permission error itself.
chown -R cocso:cocso /opt/data 2>/dev/null || true

# Drop privileges and exec the cocso CLI. $@ comes from the Dockerfile
# CMD or `docker run ... <args>` — for example `gateway run`.
exec gosu cocso /opt/cocso/cocso "$@"
