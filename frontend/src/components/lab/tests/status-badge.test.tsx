// @vitest-environment jsdom
//
// The tab's colour grammar is a DECISION (attention goes to what is wrong —
// see the reading pass in docs/test-suite-builder.md), and decisions regress
// silently: a well-meaning edit that hands `fail` back to shadcn's pale
// destructive tint would render and ship. These assertions pin the grammar's
// load-bearing properties, not the exact class strings.
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { StageBadge, StatusBadge, statusTone, SuiteStatusBadge } from './status-badge'

it('error is the only solid fill — the roll-up ranking made visible', () => {
  expect(statusTone('error')).toContain('bg-destructive ')
  for (const quiet of ['pass', 'fail', 'skip']) {
    expect(statusTone(quiet)).not.toContain('bg-destructive ')
  }
})

it('a pass is quiet and a failure is loud, never the other way around', () => {
  expect(statusTone('fail')).toContain('text-destructive')
  expect(statusTone('fail')).toContain('font-semibold')
  expect(statusTone('pass')).toContain('text-foreground')
})

it('an unknown status renders as an error badge, never invisibly', () => {
  render(<StatusBadge status="exploded" />)
  const badge = screen.getByText('exploded')
  expect(badge.className).toContain('bg-destructive')
})

it('every state carries an icon, so the reading does not depend on colour', () => {
  for (const status of ['pass', 'fail', 'error', 'skip']) {
    const { container, unmount } = render(<StatusBadge status={status} />)
    expect(container.querySelector('svg'), `no icon for ${status}`).not.toBeNull()
    unmount()
  }
})

it('the suite roll-up speaks the same grammar', () => {
  render(<SuiteStatusBadge status="failing" />)
  expect(screen.getByText('failing').className).toContain('text-destructive')
})

it('a stage is context, not a verdict — config-time keeps the accent, quietly', () => {
  render(<StageBadge stage="config-time" />)
  const stage = screen.getByText('config-time')
  expect(stage.className).toContain('text-primary')
  expect(stage.className).not.toContain('bg-primary ')
})
