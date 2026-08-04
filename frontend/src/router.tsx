import { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
} from '@tanstack/react-router'

import { AppShell } from '@/components/app-shell'
import { RouteErrorFallback, RouteNotFound } from '@/components/route-errors'
import { defaultLabTab } from '@/lib/lab-permissions'
import { labQueryOptions, meQueryOptions } from '@/lib/queries'
import { AccountPage } from '@/pages/account'
import { DashboardPage } from '@/pages/dashboard'
import { GroupsPage } from '@/pages/groups'
import { JobsPage } from '@/pages/jobs'
import { AccessTab } from '@/pages/lab/access-tab'
import { BuildTab } from '@/pages/lab/build-tab'
import { LabDetailLayout } from '@/pages/lab/lab-detail-layout'
import { NodesTab } from '@/pages/lab/nodes-tab'
import { OperationsTab } from '@/pages/lab/operations-tab'
import { OverviewTab } from '@/pages/lab/overview-tab'
import { LabImportPage } from '@/pages/lab-import'
import { LabsPage } from '@/pages/labs'
import { LoginPage } from '@/pages/login'
import { StyleguidePage } from '@/pages/styleguide'
import { UsersPage } from '@/pages/users'

export const queryClient = new QueryClient()

interface RouterContext {
  queryClient: QueryClient
}

const rootRoute = createRootRouteWithContext<RouterContext>()()

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/login',
  component: LoginPage,
})

// Pathless layout route: everything under it requires an authenticated session.
// beforeLoad resolves `me` once (cached) and redirects to /login on 401.
const authRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'auth',
  component: AppShell,
  beforeLoad: async ({ context }) => {
    try {
      await context.queryClient.ensureQueryData(meQueryOptions)
    } catch {
      throw redirect({ to: '/login' })
    }
  },
})

const indexRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/',
  component: DashboardPage,
})

const labsRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/labs',
  component: LabsPage,
  // ?new=1 opens the create-lab dialog (the command palette links here).
  validateSearch: (search: Record<string, unknown>): { new?: true } =>
    search['new'] === true || search['new'] === '1' || search['new'] === 1 ? { new: true } : {},
})

// The import wizard (delta 22). A static segment, so TanStack Router ranks it
// above /labs/$name — "import" is not a creatable lab name in practice, and
// the wizard needs a full page (multi-file gather + review), not a dialog.
const labImportRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/labs/import',
  component: LabImportPage,
})

// /labs/$name is a layout: the tab pages are child routes so views deep-link
// and survive reload; the layout owns the lab query and its error states.
const labDetailRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/labs/$name',
  component: LabDetailRouteComponent,
})

function LabDetailRouteComponent() {
  const { name } = labDetailRoute.useParams()
  return <LabDetailLayout name={name} />
}

// Role-aware landing: authors/operators open Overview, pure consumers open
// Nodes (connect, not authoring). Needs the lab loaded to read permissions —
// the same fetch the layout needs anyway, so it's cached, not extra.
const labIndexRoute = createRoute({
  getParentRoute: () => labDetailRoute,
  path: '/',
  beforeLoad: async ({ context, params }) => {
    let tab: 'overview' | 'nodes' = 'overview'
    try {
      const lab = await context.queryClient.ensureQueryData(labQueryOptions(params.name))
      tab = defaultLabTab(lab.permissions)
    } catch {
      // 404/error: land on Overview and let the layout render its error state.
    }
    throw redirect(
      tab === 'nodes'
        ? { to: '/labs/$name/nodes', params: { name: params.name } }
        : { to: '/labs/$name/overview', params: { name: params.name } },
    )
  },
})

const labOverviewRoute = createRoute({
  getParentRoute: () => labDetailRoute,
  path: '/overview',
  component: function LabOverviewRouteComponent() {
    const { name } = labOverviewRoute.useParams()
    return <OverviewTab name={name} />
  },
})

// The topology is Overview's Visual view now; the old path stays as a redirect
// so bookmarks and pasted links keep landing somewhere useful.
const labTopologyRoute = createRoute({
  getParentRoute: () => labDetailRoute,
  path: '/topology',
  beforeLoad: ({ params }) => {
    throw redirect({ to: '/labs/$name/overview', params: { name: params.name } })
  },
})

const labBuildRoute = createRoute({
  getParentRoute: () => labDetailRoute,
  path: '/build',
  component: function LabBuildRouteComponent() {
    const { name } = labBuildRoute.useParams()
    return <BuildTab name={name} />
  },
})

const labNodesRoute = createRoute({
  getParentRoute: () => labDetailRoute,
  path: '/nodes',
  component: function LabNodesRouteComponent() {
    const { name } = labNodesRoute.useParams()
    return <NodesTab name={name} />
  },
})

const labOperationsRoute = createRoute({
  getParentRoute: () => labDetailRoute,
  path: '/operations',
  component: function LabOperationsRouteComponent() {
    const { name } = labOperationsRoute.useParams()
    return <OperationsTab name={name} />
  },
})

const labAccessRoute = createRoute({
  getParentRoute: () => labDetailRoute,
  path: '/access',
  component: function LabAccessRouteComponent() {
    const { name } = labAccessRoute.useParams()
    return <AccessTab name={name} />
  },
})

const jobsRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/jobs',
  component: JobsPage,
})

const usersRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/users',
  component: UsersPage,
})

const groupsRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/groups',
  component: GroupsPage,
})

const accountRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/account',
  component: AccountPage,
})

// Phase-1 bake-off gallery; the component renders a stub outside dev builds.
const styleguideRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/styleguide',
  component: StyleguidePage,
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  authRoute.addChildren([
    indexRoute,
    labsRoute,
    labImportRoute,
    labDetailRoute.addChildren([
      labIndexRoute,
      labOverviewRoute,
      labTopologyRoute,
      labBuildRoute,
      labNodesRoute,
      labOperationsRoute,
      labAccessRoute,
    ]),
    jobsRoute,
    usersRoute,
    groupsRoute,
    accountRoute,
    styleguideRoute,
  ]),
])

export const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: 'intent',
  defaultErrorComponent: RouteErrorFallback,
  defaultNotFoundComponent: RouteNotFound,
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
