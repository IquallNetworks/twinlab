import { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  redirect,
} from '@tanstack/react-router'

import { AppShell } from '@/components/app-shell'
import { meQueryOptions } from '@/lib/queries'
import { LabDetailPage } from '@/pages/lab-detail'
import { LabsPage } from '@/pages/labs'
import { LoginPage } from '@/pages/login'
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
  beforeLoad: () => {
    throw redirect({ to: '/labs' })
  },
})

const labsRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/labs',
  component: LabsPage,
})

const labDetailRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/labs/$name',
  component: LabDetailRouteComponent,
})

function LabDetailRouteComponent() {
  const { name } = labDetailRoute.useParams()
  return <LabDetailPage name={name} />
}

const usersRoute = createRoute({
  getParentRoute: () => authRoute,
  path: '/users',
  component: UsersPage,
})

const routeTree = rootRoute.addChildren([
  loginRoute,
  authRoute.addChildren([indexRoute, labsRoute, labDetailRoute, usersRoute]),
])

export const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultPreload: 'intent',
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
