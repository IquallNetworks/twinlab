import type { SshAccess } from '@/lib/schemas'

// SSH guidance builders — the single source of truth for what we tell users
// to put in their terminal. The trap this exists to avoid: command-line -i/-o
// do NOT apply to a -J/ProxyJump hop (the hop is its own implicit connection
// using default identities), so a bare `ssh -i key -J jump@host ip` fails at
// the jump with "Permission denied (publickey)". The working recipes are an
// ~/.ssh/config Host block the -J alias resolves, or an explicit ProxyCommand
// carrying the identity itself.

export const JUMP_HOST_ALIAS = 'twinlab-jump'

// Shown where the user must substitute their own registered key file.
const IDENTITY_PLACEHOLDER = '~/.ssh/<your-registered-key>'

export interface JumpCoordinates {
  host: string
  port: number
  user: string
}

/** The advertised jump coordinates, or null when the deployment has no jump
 * host (SSH then only works from the lab host itself). */
export function jumpCoordinates(jump: SshAccess | undefined): JumpCoordinates | null {
  if (!jump?.enabled || jump.host === null || jump.port === null || jump.user === null) {
    return null
  }
  return { host: jump.host, port: jump.port, user: jump.user }
}

/** The ~/.ssh/config block that makes `ssh -J twinlab-jump …` work: the hop
 * resolves this Host entry, so the registered key actually reaches it. */
export function sshConfigBlock(jump: JumpCoordinates): string {
  return [
    `Host ${JUMP_HOST_ALIAS}`,
    `  HostName ${jump.host}`,
    `  Port ${jump.port}`,
    `  User ${jump.user}`,
    `  IdentityFile ${IDENTITY_PLACEHOLDER}`,
    `  IdentitiesOnly yes`,
  ].join('\n')
}

function destination(nodeUser: string, ip: string): string {
  return nodeUser ? `${nodeUser}@${ip}` : ip
}

/** The everyday command, once the config block is in place. */
export function sshJumpCommand(nodeUser: string, ip: string): string {
  return `ssh -J ${JUMP_HOST_ALIAS} ${destination(nodeUser, ip)}`
}

/** Config-free alternative: the ProxyCommand carries the identity to the hop
 * explicitly, so it works without touching ~/.ssh/config. */
export function sshProxyCommand(jump: JumpCoordinates, nodeUser: string, ip: string): string {
  return (
    `ssh -o ProxyCommand='ssh -i ${IDENTITY_PLACEHOLDER} -o IdentitiesOnly=yes ` +
    `-p ${jump.port} -W %h:%p ${jump.user}@${jump.host}' ${destination(nodeUser, ip)}`
  )
}

/** No jump host advertised: plain ssh, reachable from the lab host only. */
export function sshDirectCommand(nodeUser: string, ip: string): string {
  return `ssh ${destination(nodeUser, ip)}`
}
