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

/** The ssh_config alias a node answers to: `<node>.<lab>`.
 *
 * Both halves are netlab identifiers (a letter, then letters/digits/dash/
 * underscore) and so can never contain a dot — the separator is unambiguous,
 * and two labs cannot produce the same alias the way a bare node name would. */
export function nodeAlias(labName: string, nodeName: string): string {
  return `${nodeName}.${labName}`
}

export interface AliasableNode {
  name: string
  mgmt_ip: string
}

/** The ssh_config entry that makes `ssh <node>.<lab>` reach the node.
 *
 * `HostName` stays the management ADDRESS on purpose. The alias is resolved
 * client-side, so the jump host still receives the IP in its channel-open
 * request — which is exactly what the backend's permitopen list authorizes.
 * sshd matches permitopen literally ("no pattern matching or name lookup is
 * performed"), so a name it has never been told about is refused as
 * "administratively prohibited" no matter what the jump can resolve. */
export function nodeConfigBlock(
  jump: JumpCoordinates | null,
  labName: string,
  node: AliasableNode,
  nodeUser: string,
): string {
  const lines = [`Host ${nodeAlias(labName, node.name)}`, `  HostName ${node.mgmt_ip}`]
  if (nodeUser) lines.push(`  User ${nodeUser}`)
  if (jump) lines.push(`  ProxyJump ${JUMP_HOST_ALIAS}`)
  return lines.join('\n')
}

/** Every node of a lab in one paste. Nodes with no management address (not
 * deployed, or live state unavailable) have nothing to alias and are left out
 * rather than emitted half-formed. */
export function labConfigBlocks(
  jump: JumpCoordinates | null,
  labName: string,
  nodes: readonly AliasableNode[],
  nodeUser: string,
): string {
  return nodes
    .filter((node) => node.mgmt_ip)
    .map((node) => nodeConfigBlock(jump, labName, node, nodeUser))
    .join('\n\n')
}

/** The everyday command, once both blocks are in ~/.ssh/config. */
export function sshAliasCommand(labName: string, nodeName: string): string {
  return `ssh ${nodeAlias(labName, nodeName)}`
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
