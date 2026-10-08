// Search over the catalog and transcripts: ranking, caption hits, filters.

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { dataDir, onSwap } from './data.mjs'

let catalog = null
onSwap(() => { catalog = null })

export async function sessions() {
  catalog ??= JSON.parse(await readFile(join(dataDir, 'catalog.json'), 'utf8')).sessions
  return catalog
}

export async function session(id) {
  const s = (await sessions()).find(s => s.id === id)
  if (!s) throw new Error(`No session ${id}. Ids look like wwdc2025-219; \`search\` finds them.`)
  return s
}

export async function transcriptOf(s) {
  try {
    return JSON.parse(await readFile(join(dataDir, s.path, 'transcript.json'), 'utf8')).segments ?? []
  } catch { return [] }
}

export async function metadataOf(s) {
  return JSON.parse(await readFile(join(dataDir, s.path, 'metadata.json'), 'utf8'))
}

/** year: "2025" or "2023-2026"; event: exact; topic: substring, any topic. */
export async function filtered({ year, event, topic } = {}) {
  const [lo, hi] = year ? year.split('-').map(Number) : []
  return (await sessions()).filter(s =>
    (!year || (s.year >= lo && s.year <= (hi || lo))) &&
    (!event || s.event === event) &&
    (!topic || s.topics.some(t => t.toLowerCase().includes(topic.toLowerCase()))))
}

export const timeURL = (s, seconds) => `${s.url.replace(/\/$/, '')}/?time=${Math.floor(seconds)}`

const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const count = (re, text) => (text.match(re) ?? []).length

/** Read transcripts a batch at a time, so a full search does not open 1,600 files at once. */
async function withTranscripts(list, fn) {
  for (let i = 0; i < list.length; i += 64) {
    const batch = list.slice(i, i + 64)
    const segs = await Promise.all(batch.map(transcriptOf))
    batch.forEach((s, j) => fn(s, segs[j]))
  }
}

/** Every word must appear somewhere: title, keywords, description or transcript. */
export async function search(query, filters, limit) {
  const words = query.trim().split(/\s+/).filter(Boolean)
  const list = await filtered(filters)
  if (!words.length) {
    return list.sort((a, b) => b.year - a.year).slice(0, limit)
      .map(s => ({ id: s.id, title: s.title, year: s.year, duration: s.duration, url: s.url, topics: s.topics }))
  }
  const counting = words.map(w => new RegExp(escape(w), 'gi'))
  const testing = words.map(w => new RegExp(escape(w), 'i'))
  const rows = []
  await withTranscripts(list, (s, segs) => {
    const body = segs.map(seg => seg.text).join('\n')
    const meta = [s.title, s.keywords.join(' '), s.description ?? '']
    let score = 0
    const hits = {}
    for (const [i, re] of counting.entries()) {
      const h = { title: count(re, meta[0]), keywords: count(re, meta[1]), description: count(re, meta[2]), transcript: count(re, body) }
      if (!h.title && !h.keywords && !h.description && !h.transcript) return
      hits[words[i]] = h
      score += 10 * !!h.title + 5 * !!h.keywords + 3 * !!h.description + 2 * Math.log2(1 + h.transcript)
    }
    const first = segs.find(seg => testing.some(re => re.test(seg.text)))?.start ?? null
    rows.push({
      id: s.id, title: s.title, year: s.year, duration: s.duration, score: Math.round(score * 10) / 10, hits,
      firstHit: first, url: first === null ? s.url : timeURL(s, first), topics: s.topics,
    })
  })
  return rows.sort((a, b) => b.score - a.score || b.year - a.year).slice(0, limit)
}

/** Caption lines containing `pattern`, five per session at most, busiest sessions first. */
export async function grep(pattern, filters, sessionID, limit) {
  const re = new RegExp(escape(pattern.trim()), 'i')
  const list = sessionID ? [await session(sessionID)] : await filtered(filters)
  const rows = []
  await withTranscripts(list, (s, segs) => {
    const lines = segs.filter(seg => re.test(seg.text))
    if (!lines.length) return
    rows.push({
      id: s.id, title: s.title, count: lines.length,
      matches: lines.slice(0, 5).map(seg => ({ start: seg.start, url: timeURL(s, seg.start), text: seg.text })),
    })
  })
  return rows.sort((a, b) => b.count - a.count).slice(0, limit)
}
