#!/bin/sh
# Jump-host entrypoint: stage the lookup script's config, ensure host keys and
# the privsep dir exist, then exec sshd in the foreground.
set -eu

: "${JUMP_TOKEN:?JUMP_TOKEN is required (the shared secret for the backend's /internal lookup)}"
: "${BACKEND_URL:?BACKEND_URL is required (e.g. http://backend:8000)}"

# The AuthorizedKeysCommand runs as jumpauth with a minimal environment, so
# hand it the config via a file only root and jumpauth can read.
mkdir -p /etc/twinlab-jump
{
    printf 'BACKEND_URL=%s\n' "$BACKEND_URL"
    printf 'JUMP_TOKEN=%s\n' "$JUMP_TOKEN"
} > /etc/twinlab-jump/env
chown root:jumpauth /etc/twinlab-jump/env
chmod 0640 /etc/twinlab-jump/env

# Host keys persist on a named volume: a recreated container must present the
# same identity or every user's known_hosts raises a MITM alarm.
mkdir -p /etc/ssh/host_keys
[ -f /etc/ssh/host_keys/ssh_host_ed25519_key ] \
    || ssh-keygen -q -t ed25519 -N '' -f /etc/ssh/host_keys/ssh_host_ed25519_key
[ -f /etc/ssh/host_keys/ssh_host_rsa_key ] \
    || ssh-keygen -q -t rsa -b 3072 -N '' -f /etc/ssh/host_keys/ssh_host_rsa_key

# Debian sshd wants its privilege-separation directory at runtime.
mkdir -p /run/sshd

exec /usr/sbin/sshd -D -e -f /etc/ssh/sshd_config.twinlab
