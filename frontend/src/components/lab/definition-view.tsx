import { Link } from '@tanstack/react-router'
import { useMemo, useState } from 'react'

import { CodeEditor } from '@/components/code-editor'
import { TopologyCanvas } from '@/components/lab/topology/topology-canvas'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { PERM_LAB_EDIT } from '@/lib/lab-permissions'
import type { LabDetail } from '@/lib/schemas'
import { parseTopology } from '@/lib/topology'

type View = 'visual' | 'text'

function Notice({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

/** The lab's stored definition, shown two ways with the Build tab's selector:
 * Visual is the topology drawn from it (with the live node/link overlay),
 * Text is its YAML source. Visual leads — the drawing answers "what is this
 * lab" faster than the source does, and a lab that isn't deployed still
 * renders, so the topology doubles as documentation.
 *
 * Read-only in both views: editing lives on the Build tab, which owns the
 * same two modes as an EDITOR. */
export function DefinitionView({ lab }: { lab: LabDetail }) {
  const name = lab.name
  const [view, setView] = useState<View>('visual')
  const topology = useMemo(
    () => (lab.definition !== null ? parseTopology(lab.definition) : null),
    [lab.definition],
  )
  const canEdit = lab.permissions.includes(PERM_LAB_EDIT)

  if (lab.definition === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Definition</CardTitle>
        </CardHeader>
        <CardContent>
          <Notice>
            No definition yet
            {canEdit ? (
              <>
                {' '}
                — build one on the{' '}
                <Link
                  to="/labs/$name/build"
                  params={{ name }}
                  className="underline hover:text-foreground"
                >
                  Build
                </Link>{' '}
                tab, and the topology renders here.
              </>
            ) : (
              ' — the topology renders here once one is authored.'
            )}
          </Notice>
        </CardContent>
      </Card>
    )
  }

  // The canvas goes edge to edge; every other body wants the card's padding.
  const drawable = view === 'visual' && topology !== null && topology.nodes.length > 0

  return (
    <Card className={drawable ? 'pb-0' : undefined}>
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle className="text-base">Definition</CardTitle>
        <div className="flex items-center gap-3">
          {canEdit && (
            <Link
              to="/labs/$name/build"
              params={{ name }}
              className="text-xs text-muted-foreground underline hover:text-foreground"
            >
              Edit on the Build tab
            </Link>
          )}
          <Tabs value={view} onValueChange={(value) => setView(value as View)}>
            <TabsList>
              <TabsTrigger value="visual">Visual</TabsTrigger>
              <TabsTrigger value="text">Text</TabsTrigger>
            </TabsList>
          </Tabs>
        </div>
      </CardHeader>
      <CardContent className={drawable ? 'px-0' : undefined}>
        {view === 'text' ? (
          <CodeEditor value={lab.definition} language="yaml" className="max-h-[32rem]" />
        ) : topology === null ? (
          <Notice>
            The stored definition is not valid YAML —{' '}
            <Button
              variant="link"
              className="h-auto p-0 text-sm"
              onClick={() => setView('text')}
            >
              read the source
            </Button>
            .
          </Notice>
        ) : topology.nodes.length === 0 ? (
          <Notice>The definition declares no nodes.</Notice>
        ) : (
          <div className="h-[max(28rem,calc(100vh-22rem))]">
            <TopologyCanvas lab={lab} topology={topology} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}
