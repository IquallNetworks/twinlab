#!/usr/bin/env node
// Empty a RUNNING twinlab-e2e stack through the API — the iteration
// alternative to `stack.sh reset`, which drops volumes and rebuilds images
// (minutes) where this takes seconds. Removes every lab (destroy with
// remove=true, each job polled to its terminal state), every non-bootstrap
// user, every group, every user-tier node template, and the admin's own
// SSH/API keys.
//
// NOT pristine on purpose: sessions, id sequences and anything a future
// resource adds all survive, so the specs that assert a truly virgin stack
// still belong to a `reset` run — this is for the loop in between.
//
// Env (exported by stack.sh from stack.env):
//   E2E_BASE_URL  E2E_ADMIN_USERNAME  E2E_ADMIN_PASSWORD

const base = need('E2E_BASE_URL') + '/api/v1'
const adminUsername = need('E2E_ADMIN_USERNAME')
const adminPassword = need('E2E_ADMIN_PASSWORD')

function need(name) {
  const value = process.env[name]
  if (!value) {
    console.error(`api-clean: ${name} is not set (stack.sh exports it from stack.env)`)
    process.exit(2)
  }
  return value
}

let cookie = ''

async function send(method, path, body) {
  const res = await fetch(base + path, {
    method,
    headers: {
      ...(body === undefined ? {} : { 'content-type': 'application/json' }),
      ...(cookie === '' ? {} : { cookie }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const setCookie = res.headers.get('set-cookie')
  if (setCookie) cookie = setCookie.split(';')[0]
  const text = await res.text()
  let payload = null
  if (text !== '') {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }
  return { status: res.status, payload }
}

function fail(what, detail) {
  console.error(`api-clean: ${what}: ${JSON.stringify(detail)}`)
  console.error('api-clean: the stack may need a full `stack.sh reset`')
  process.exit(1)
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

const login = await send('POST', '/auth/login', {
  username: adminUsername,
  password: adminPassword,
})
if (login.status !== 200) fail('login failed', login)

// Labs first: a remove=true destroy releases the mgmt subnet, the host-bridge
// claim and the lab-files tree, so everything else is independent afterwards.
const labs = await send('GET', '/labs')
if (labs.status !== 200) fail('listing labs failed', labs)

const destroys = []
for (const lab of labs.payload) {
  let res
  // A running job holds the per-lab mutex; a submit landing on it is a clean
  // 409 that resolves when the job does — retry for up to a minute.
  for (let attempt = 0; ; attempt++) {
    res = await send('DELETE', `/labs/${lab.name}?remove=true`)
    const busy = res.status === 409 && res.payload?.code === 'job_in_flight'
    if (!busy || attempt >= 30) break
    await sleep(2000)
  }
  if (res.status !== 202) fail(`destroying lab ${lab.name} was refused`, res)
  destroys.push({ lab: lab.name, id: res.payload.id })
}

for (const { lab, id } of destroys) {
  const deadline = Date.now() + 180_000
  for (;;) {
    const res = await send('GET', `/labs/${lab}/jobs/${id}`)
    if (res.status !== 200) fail(`polling the destroy job for ${lab} failed`, res)
    if (res.payload.status !== 'running') {
      if (res.payload.status !== 'succeeded')
        fail(`the destroy job for ${lab} ${res.payload.status}`, res.payload.error)
      break
    }
    if (Date.now() > deadline) fail(`the destroy job for ${lab} is still running after 180s`, id)
    await sleep(1000)
  }
  console.log(`api-clean: removed lab ${lab}`)
}

const users = await send('GET', '/users')
if (users.status !== 200) fail('listing users failed', users)
for (const user of users.payload) {
  if (user.username === adminUsername) continue
  const res = await send('DELETE', `/users/${user.id}`)
  if (res.status !== 204) fail(`deleting user ${user.username} failed`, res)
  console.log(`api-clean: deleted user ${user.username}`)
}

const groups = await send('GET', '/groups')
if (groups.status !== 200) fail('listing groups failed', groups)
for (const group of groups.payload) {
  const res = await send('DELETE', `/groups/${group.id}`)
  if (res.status !== 204) fail(`deleting group ${group.name} failed`, res)
  console.log(`api-clean: deleted group ${group.name}`)
}

const templates = await send('GET', '/templates/node')
if (templates.status !== 200) fail('listing node templates failed', templates)
for (const template of templates.payload) {
  if (template.tier === 'builtin') continue
  const res = await send('DELETE', `/templates/node/${template.name}`)
  if (res.status !== 204) fail(`deleting node template ${template.name} failed`, res)
  console.log(`api-clean: deleted node template ${template.name}`)
}

// The admin's own credentials-adjacent state: specs register keys under the
// bootstrap account, and a leftover name collides as 409 name_taken.
for (const [path, label] of [
  ['/auth/ssh-keys', 'ssh key'],
  ['/auth/api-keys', 'api key'],
]) {
  const keys = await send('GET', path)
  if (keys.status !== 200) fail(`listing ${label}s failed`, keys)
  for (const key of keys.payload) {
    const res = await send('DELETE', `${path}/${key.id}`)
    if (res.status !== 204) fail(`deleting ${label} ${key.name} failed`, res)
    console.log(`api-clean: deleted ${label} ${key.name}`)
  }
}

console.log(
  `api-clean: done — ${destroys.length} lab(s), stack emptied through the API (not pristine: use \`reset\` for the gated run)`,
)
