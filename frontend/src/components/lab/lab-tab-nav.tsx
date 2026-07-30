import { Link } from '@tanstack/react-router'

import { PERM_LAB_EDIT, PERM_LAB_GRANT } from '@/lib/lab-permissions'

// Router Links styled as tabs (not radix Tabs): tab state lives in the URL, so
// views deep-link, survive reload, and preload on intent like any route. The
// links are spelled out (no generic wrapper) so the router's typed params
// checking applies to each literal path.
const TAB_LINK =
  '-mb-px border-b-2 border-transparent px-1 pb-2 text-sm text-muted-foreground transition-colors hover:text-foreground data-[status=active]:border-primary data-[status=active]:font-medium data-[status=active]:text-foreground'

/** The lab page's tab strip. Only permitted tabs render; the tab components
 * themselves also self-guard so a hand-typed URL degrades gracefully. */
export function LabTabNav({ name, permissions }: { name: string; permissions: string[] }) {
  return (
    <nav className="flex items-center gap-4 border-b">
      <Link to="/labs/$name/overview" params={{ name }} className={TAB_LINK}>
        Overview
      </Link>
      <Link to="/labs/$name/topology" params={{ name }} className={TAB_LINK}>
        Topology
      </Link>
      {permissions.includes(PERM_LAB_EDIT) && (
        <Link to="/labs/$name/build" params={{ name }} className={TAB_LINK}>
          Build
        </Link>
      )}
      <Link to="/labs/$name/nodes" params={{ name }} className={TAB_LINK}>
        Nodes
      </Link>
      <Link to="/labs/$name/operations" params={{ name }} className={TAB_LINK}>
        Operations
      </Link>
      {permissions.includes(PERM_LAB_GRANT) && (
        <Link to="/labs/$name/access" params={{ name }} className={TAB_LINK}>
          Access
        </Link>
      )}
    </nav>
  )
}
