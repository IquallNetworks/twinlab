// waitJob rides out a momentary network failure: a browser on the lab host
// sees the host's network change when a lab's bridges go, Chrome fails every
// request in flight, and a destroy's lost poll left the page waiting forever.
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { ApiError, waitJob } from './api'
import type { Job } from './schemas'

const job: Job = {
  id: 'j1',
  lab_name: 'lab1',
  kind: 'destroy',
  status: 'running',
  request: {},
  result: null,
  error: null,
  created_at: '2026-11-18T00:00:00Z',
  finished_at: null,
}

function answer(status: Job['status']): Response {
  return new Response(JSON.stringify({ ...job, status, steps: [] }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

/** Run waitJob against `replies`, one per read, and settle every timer. */
async function run(replies: (() => Promise<Response>)[]) {
  const fetch = vi.fn(() => {
    const next = replies.shift()
    if (next === undefined) throw new Error('read more often than expected')
    return next()
  })
  vi.stubGlobal('fetch', fetch)
  const done = waitJob('lab1', job).then(
    (value) => ({ value }),
    (error: unknown) => ({ error }),
  )
  await vi.runAllTimersAsync()
  return { outcome: await done, reads: fetch.mock.calls.length }
}

const networkFailure = () => Promise.reject(new TypeError('Failed to fetch'))

it('retries a read that failed on the network, then finishes', async () => {
  const { outcome, reads } = await run([
    () => Promise.resolve(answer('running')),
    networkFailure,
    networkFailure,
    () => Promise.resolve(answer('succeeded')),
  ])
  expect(outcome).toMatchObject({ value: { status: 'succeeded' } })
  expect(reads).toBe(4)
})

it('gives up after a run of network failures, with the failure', async () => {
  const { outcome, reads } = await run(Array.from({ length: 6 }, () => networkFailure))
  expect(outcome).toMatchObject({ error: expect.any(TypeError) })
  expect(reads).toBe(6)
})

it("never retries the server's own answer", async () => {
  const { outcome, reads } = await run([
    () =>
      Promise.resolve(
        new Response(JSON.stringify({ code: 'job_not_found', message: 'no such job', extras: {} }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
  ])
  expect(outcome).toMatchObject({ error: expect.any(ApiError) })
  expect(reads).toBe(1)
})
