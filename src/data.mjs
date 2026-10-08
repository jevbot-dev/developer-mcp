// Where the WWDC transcripts live, and getting them there.
//
// The bundle ships code only: transcripts are © Apple and ~120 MB, so the
// server fetches guitaripod/wwdc-sessions itself on first use (an HTTPS
// archive, no git), keeps the catalog, metadata and transcripts, and swaps the
// new copy in whole. WWDC_REPO points at an existing clone instead, which is
// then used as-is and never downloaded or replaced.

import { execFile } from 'node:child_process'
import { createWriteStream, existsSync } from 'node:fs'
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { promisify } from 'node:util'

const run = promisify(execFile)
const UPSTREAM = 'guitaripod/wwdc-sessions'
const STALE_AFTER_MS = 7 * 24 * 3600 * 1000

export const managed = !process.env.WWDC_REPO
export const dataDir = managed
  ? join(homedir(), 'Library/Application Support/developer-mcp/wwdc-sessions')
  : process.env.WWDC_REPO.replace(/^~(?=\/|$)/, homedir())

/** What `status` reports. `phase`: missing | downloading | ready | failed. */
export const progress = { phase: 'missing', receivedBytes: 0, error: null }
if (hasData()) progress.phase = 'ready'
let pending = null
let generation = 0
const listeners = new Set()

/** Called after a new copy is swapped in, so caches can drop the old one. */
export function onSwap(fn) { listeners.add(fn) }

export function hasData() {
  return existsSync(join(dataDir, 'catalog.json'))
}

export async function source() {
  try { return JSON.parse(await readFile(join(dataDir, 'source.json'), 'utf8')) } catch { return null }
}

/** Resolve once the data is there, starting the download if nobody has. */
export function ensureData() {
  if (hasData()) { progress.phase = 'ready'; return Promise.resolve() }
  if (!managed) return Promise.reject(new Error(`WWDC_REPO has no catalog.json: ${dataDir}`))
  return download()
}

/** Like ensureData, but give up waiting after `ms` and say how far it got. */
export async function dataWithin(ms) {
  let timer
  const late = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(
      `The WWDC transcripts are still downloading (${(progress.receivedBytes / 1e6).toFixed(0)} MB of about 27 MB). Try again in a minute; \`status\` shows progress.`)), ms)
  })
  try { await Promise.race([ensureData(), late]) } finally { clearTimeout(timer) }
}

/** On start: fetch if missing; if older than a week and upstream moved, fetch again in the background. */
export async function refreshIfStale() {
  if (!managed) return
  if (!hasData()) return download().catch(() => {})
  progress.phase = 'ready'
  const have = await source()
  if (have && Date.now() - Date.parse(have.fetchedAt) < STALE_AFTER_MS) return
  try {
    const latest = await headCommit()
    if (latest === have?.commit) {
      await writeFile(join(dataDir, 'source.json'), JSON.stringify({ ...have, fetchedAt: new Date().toISOString() }))
    } else {
      await download(latest)
    }
  } catch { /* offline: keep what we have */ }
}

function download(commit) {
  pending ??= fetchCopy(commit).finally(() => { pending = null })
  return pending
}

async function headCommit() {
  const res = await fetch(`https://api.github.com/repos/${UPSTREAM}/commits/master`,
    { headers: { Accept: 'application/vnd.github.sha', 'User-Agent': 'developer-mcp' } })
  if (!res.ok) throw new Error(`GitHub answered ${res.status} for the latest commit`)
  return (await res.text()).trim()
}

async function fetchCopy(commit) {
  const keepReady = hasData()
  Object.assign(progress, { phase: keepReady ? 'ready' : 'downloading', receivedBytes: 0, error: null })
  const parent = dirname(dataDir)
  const archive = join(parent, `download-${process.pid}.tgz`)
  const incoming = join(parent, `incoming-${process.pid}`)
  const outgoing = join(parent, `outgoing-${process.pid}`)
  try {
    await mkdir(incoming, { recursive: true })
    commit ??= await headCommit()
    const res = await fetch(`https://codeload.github.com/${UPSTREAM}/tar.gz/${commit}`)
    if (!res.ok || !res.body) throw new Error(`GitHub answered ${res.status} for the archive`)
    const body = Readable.fromWeb(res.body)
    body.on('data', chunk => { progress.receivedBytes += chunk.length })
    await pipeline(body, createWriteStream(archive))
    // Only what the tools read: the catalog, and each session's metadata and transcript.
    await run('/usr/bin/tar', ['-xzf', archive, '-C', incoming, '--strip-components', '1',
      '*/catalog.json', '*/sessions/*/*/metadata.json', '*/sessions/*/*/transcript.json'])
    if (!existsSync(join(incoming, 'catalog.json'))) throw new Error('the archive had no catalog.json')
    await writeFile(join(incoming, 'source.json'),
      JSON.stringify({ repo: UPSTREAM, commit, fetchedAt: new Date().toISOString() }))
    if (existsSync(dataDir)) await rename(dataDir, outgoing)
    await rename(incoming, dataDir)
    generation += 1
    for (const fn of listeners) fn(generation)
    progress.phase = 'ready'
  } catch (error) {
    // A failed refresh leaves the old copy in place and in use.
    Object.assign(progress, { phase: keepReady ? 'ready' : 'failed', error: String(error.message ?? error) })
    throw error
  } finally {
    await Promise.all([archive, incoming, outgoing].map(p => rm(p, { recursive: true, force: true })))
  }
}
