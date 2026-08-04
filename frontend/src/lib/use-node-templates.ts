import { useQuery } from '@tanstack/react-query'

import { nodeTemplatesQueryOptions } from '@/lib/queries'
import type { NodeTemplateWire } from '@/lib/schemas'

/** The node-template collection for the builder's Add menu (delta 21). Empty
 * until the query resolves — unlike the device catalog there is no static
 * fallback, because templates are deployment data, not a shipped set. */
export function useNodeTemplates(): readonly NodeTemplateWire[] {
  const query = useQuery(nodeTemplatesQueryOptions)
  return query.data ?? []
}
