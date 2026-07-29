# SSH jump host: stock OpenSSH sshd, keys resolved live from the backend.
# Debian to stay in the same distro family as the other images (python:*-slim
# is Debian too); OpenSSH is BSD-licensed, curl is curl-licensed (MIT-like).
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-server curl \
    && rm -rf /var/lib/apt/lists/*

# `jump` is the single account every connection authenticates as (which KEY is
# offered selects the Twinlab identity). No shell, no password login — but the
# account must not be LOCKED: `useradd` without -p writes '!' to the shadow
# field, and with UsePAM no sshd refuses ALL auth for a locked account, even
# publickey. '*' means "valid account, no password".
RUN useradd --create-home --shell /usr/sbin/nologin -p '*' jump \
    # Dedicated no-privilege identity sshd runs the AuthorizedKeysCommand as.
    && useradd --system --shell /usr/sbin/nologin jumpauth

COPY sshd_config /etc/ssh/sshd_config.twinlab
# sshd requires the command (and its parent dirs) root-owned, not group/world
# writable, absolute path.
COPY --chmod=0755 twinlab-authorized-keys /usr/local/bin/twinlab-authorized-keys
COPY --chmod=0755 entrypoint.sh /entrypoint.sh

EXPOSE 2222
ENTRYPOINT ["/entrypoint.sh"]
