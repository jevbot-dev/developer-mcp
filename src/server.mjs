// developer-mcp: a bridge to the Developer app (developer.apple.wwdc-Release).
//
//   node server.mjs           serve over stdio (the host starts it)
//
// The app has no intents and no scripting, so this follows the bridge contract
// (jevbot-mac docs/app-bridge-contract.md): lookups read the WWDC transcripts
// directly (channel `data`), and opening hands the session's universal link to
// the app (channel `link`), which says nothing back.

import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { z } from 'zod'
import { dataDir, dataWithin, managed, progress, refreshIfStale, source } from './data.mjs'
import { grep, metadataOf, search, session, timeURL, transcriptOf } from './sessions.mjs'
import pkg from '../package.json' with { type: 'json' }

const run = promisify(execFile)
const APP_ID = 'developer.apple.wwdc-Release'
const APP_PATHS = ['/Applications/Developer.app', join(homedir(), 'Applications/Developer.app')]

// Nothing here changes anything: searching reads files, and opening only shows
// a page. `open_at` does bring the Developer app forward — like turning to a
// page, not like editing one.
const LOOKING = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }

/** How a tool reaches the app, and whether its result can be confirmed. */
const bridge = (channel, verify) => ({ 'dev.jevbot/bridge': { version: 1, channel, verify } })
const DATA = bridge('data', 'result')

const INSTRUCTIONS = `\
Apple WWDC sessions (2014–2026, Tech Talks, Meet with Apple): 1,600+ talks with timecoded English transcripts, searched locally, and the Developer app to show them in.

To find a moment and show it:
1. \`search\` to find candidate sessions (ranked; several words must all appear). Filter by year / event / topic when the user implies them.
2. \`grep\` for the exact lines and their start times, or \`transcript\` to read the talk around a time and confirm it says what the user asked about. A hit on a keyword is not yet the answer — read the lines around it.
3. \`open_at\` with the session id and the second where the relevant passage starts (a few seconds before the first line is fine). It asks the Developer app to open that session ready to start there; it does not press play, and nothing comes back to confirm it.

Session ids look like \`wwdc2025-219\`. Transcripts are English; coverage before 2019 is sparse. Times are seconds.
The transcripts are downloaded on first use (about 27 MB); until then tools say so and \`status\` shows progress.`

const developerApp = () => APP_PATHS.find(existsSync) ?? null

function clock(seconds) {
  const s = Math.floor(seconds)
  const mm = String(Math.floor(s % 3600 / 60)).padStart(2, '0'), ss = String(s % 60).padStart(2, '0')
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mm}:${ss}` : `${Math.floor(s / 60)}:${ss}`
}

/** The Developer app's own icon, so the host shows what this opens. */
async function appIcon() {
  const app = developerApp()
  if (!app) return []
  const dir = await mkdtemp(join(tmpdir(), 'developer-mcp-'))
  try {
    const { stdout } = await run('/usr/bin/defaults', ['read', join(app, 'Contents/Info'), 'CFBundleIconFile'])
    const name = stdout.trim() || 'AppIcon'
    const icns = join(app, 'Contents/Resources', name.endsWith('.icns') ? name : `${name}.icns`)
    const png = join(dir, 'icon.png')
    await run('/usr/bin/sips', ['-s', 'format', 'png', '-Z', '256', icns, '--out', png])
    const data = (await readFile(png)).toString('base64')
    return [{ src: `data:image/png;base64,${data}`, mimeType: 'image/png', sizes: ['256x256'] }]
  } catch {
    return []
  } finally {
    await rm(dir, { recursive: true, force: true })
  }
}

/** One JSON object per result: a top-level list would reach the host as many pieces. */
const reply = value => ({ content: [{ type: 'text', text: JSON.stringify(value, null, 2) }] })

/** Wait a while for a first download rather than failing the first question outright. */
const ready = () => dataWithin(90_000)

const filters = {
  year: z.string().optional().describe('"2025" or "2023-2026"'),
  event: z.string().optional().describe('e.g. "wwdc2025", "tech-talks", "meet-with-apple"'),
  topic: z.string().optional().describe('substring of a topic, e.g. "swiftui"'),
}

let lastOpenRequest = null

const server = new McpServer(
  { name: 'developer-mcp', title: 'Developer', version: pkg.version, icons: await appIcon() },
  { instructions: INSTRUCTIONS },
)

server.registerTool('status', {
  description: 'Where the transcripts are and whether they are ready, whether the Developer app is installed, and the last session this server asked it to open.\n\n'
    + '`lastOpenRequest` is what was sent, not what the app shows now: the user may have moved on since.',
  annotations: LOOKING, _meta: DATA,
}, async () => reply({
  data: { dir: dataDir, managed, ...progress, source: await source() },
  developerApp: developerApp(),
  lastOpenRequest,
}))

server.registerTool('search', {
  description: 'Rank sessions by relevance to `query` (several words must all appear, anywhere in the title, keywords, description or transcript). With no query, list the sessions the filters match, newest first.\n\n'
    + 'Each result has the session id, title, year, duration in seconds, first transcript hit in seconds and a link.',
  inputSchema: { query: z.string().default(''), ...filters, limit: z.number().int().default(10) },
  annotations: LOOKING, _meta: DATA,
}, async ({ query, year, event, topic, limit }) => {
  await ready()
  return reply({ results: await search(query, { year, event, topic }, Math.max(1, Math.min(limit, 50))) })
})

server.registerTool('grep', {
  description: 'Transcript lines that say `pattern` (case-insensitive substring), each with its start second; at most five lines per session, busiest sessions first.\n\n'
    + 'Matches within one caption segment, so a phrase split across two segments can be missed — then search, or grep for fewer words. Pass session_id to look inside one talk only.',
  inputSchema: { pattern: z.string().min(1), session_id: z.string().optional(), ...filters, limit: z.number().int().default(20) },
  annotations: LOOKING, _meta: DATA,
}, async ({ pattern, session_id, year, event, topic, limit }) => {
  await ready()
  return reply({ results: await grep(pattern, { year, event, topic }, session_id, Math.max(1, Math.min(limit, 100))) })
})

server.registerTool('show', {
  description: "One session's metadata: title, event, duration in seconds, topics, keywords, description, resources and link.",
  inputSchema: { session_id: z.string() },
  annotations: LOOKING, _meta: DATA,
}, async ({ session_id }) => {
  await ready()
  const s = await session(session_id)
  const meta = await metadataOf(s).catch(() => ({}))
  return reply({
    id: s.id, title: s.title, year: s.year, event: s.event, duration: s.duration, url: s.url,
    topics: s.topics, platforms: s.platforms, keywords: s.keywords, description: s.description ?? null,
    hasTranscript: s.hasTranscript, codeSnippets: (meta.codeSnippets ?? []).length,
    resources: (meta.resources ?? []).map(r => ({ title: r.title, url: r.sosumiURL ?? r.url })),
  })
})

server.registerTool('transcript', {
  description: "The talk's words between `start` and `end` seconds (default: two minutes from start), one line per caption with its start time.",
  inputSchema: { session_id: z.string(), start: z.number().default(0), end: z.number().optional() },
  annotations: LOOKING, _meta: DATA,
}, async ({ session_id, start, end }) => {
  await ready()
  const s = await session(session_id)
  const stop = end ?? start + 120
  const lines = (await transcriptOf(s)).filter(seg => seg.start >= start && seg.start <= stop)
    .map(seg => `[${clock(seg.start)}] ${seg.text}`)
  return reply({ id: s.id, title: s.title, from: clock(start), to: clock(stop), lines })
})

server.registerTool('open_at', {
  description: 'Ask the Developer app to open the session, ready to start at `seconds`. It does not press play; the user does.\n\n'
    + 'The link is handed to the app and nothing comes back, so the result says what was sent, not what the app shows.',
  inputSchema: { session_id: z.string(), seconds: z.number().default(0) },
  annotations: LOOKING, _meta: bridge('link', 'none'),
}, async ({ session_id, seconds }) => {
  await ready()
  if (!developerApp()) throw new Error('The Developer app is not installed; it is free on the Mac App Store.')
  const s = await session(session_id)
  const url = timeURL(s, Math.max(0, seconds))
  // By bundle id: a plain `open` of the URL lands in the default browser instead.
  await run('/usr/bin/open', ['-b', APP_ID, url])
  lastOpenRequest = { id: s.id, title: s.title, seconds: Math.floor(seconds), url }
  return reply({
    sent: url, session: s.title, at: clock(seconds), verified: false,
    note: "Asked the Developer app to open this session at this time; whether it did can't be read back. Playing is the user's to press.",
  })
})

await server.connect(new StdioServerTransport())
refreshIfStale()
