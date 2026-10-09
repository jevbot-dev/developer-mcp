// The Developer app's player, through accessibility (channel `ax`).
//
// The page a session opens to has a "play/pause" checkbox in the player controls
// — its value is 1 while playing — and, until the first play, a "Play" button
// (identifier play.fill) over the poster. While the poster is up the checkbox is
// there but pressing it does nothing, so the poster's button goes first.
// Pressing is a toggle, so the state is read first and pressed only when not
// already playing, then read back: what this returns is what the app shows.
//
// osascript runs the JavaScript below; its own process is what macOS asks
// about, under this server's permission (it does not inherit Jevbot's).

import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

const run = promisify(execFile)

const SCRIPT = String.raw`
ObjC.import('ApplicationServices'); ObjC.import('AppKit')
const attr = (el, name) => { const r = Ref(); return $.AXUIElementCopyAttributeValue(el, $(name), r) === 0 ? r[0] : null }
const val = v => { try { return ObjC.unwrap(ObjC.castRefToObject(v)) } catch (e) { return null } }
function find(el, pred, depth) {
  if (depth > 40) return null
  if (pred(el)) return el
  const kids = attr(el, 'AXChildren')
  if (!kids) return null
  const list = ObjC.castRefToObject(kids)
  for (let i = 0; i < list.count; i++) { const hit = find(list.objectAtIndex(i), pred, depth + 1); if (hit) return hit }
  return null
}
const is = (role, key, text) => el => val(attr(el, 'AXRole')) === role && val(attr(el, key)) === text
function run(argv) {
  const [bundle, title, waitSeconds] = argv
  if (!$.AXIsProcessTrusted()) return JSON.stringify({ trusted: false })
  const apps = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(bundle)
  if (apps.count === 0) return JSON.stringify({ trusted: true, running: false })
  const app = $.AXUIElementCreateApplication(apps.objectAtIndex(0).processIdentifier)
  const toggle = () => find(app, is('AXCheckBox', 'AXDescription', 'play/pause'), 0)
  const poster = () => find(app, is('AXButton', 'AXIdentifier', 'play.fill'), 0)
  const page = () => !title || find(app, is('AXStaticText', 'AXValue', title), 0)
  // The page may still be loading after open_at: wait for its title and a player.
  let box = null, button = null
  for (let t = 0; t < Number(waitSeconds) * 4; t++) {
    if (page()) { button = poster(); box = toggle(); if (box || button) break }
    delay(0.25)
  }
  if (!box && !button) return JSON.stringify({ trusted: true, running: true, page: !!page(), player: false })
  const before = box ? val(attr(box, 'AXValue')) : 0
  let pressed = false
  if (before !== 1) { $.AXUIElementPerformAction(button ?? box, $('AXPress')); pressed = true }
  let after = before
  for (let t = 0; t < 20; t++) {
    const now = toggle()
    after = now ? val(attr(now, 'AXValue')) : null
    if (after === 1) break
    delay(0.25)
  }
  return JSON.stringify({ trusted: true, running: true, page: true, player: true, before, pressed, after })
}
`

/** Plays what the Developer app shows; with `title`, only once that session's page is up. */
export async function play(bundleID, title = '', waitSeconds = 8) {
  const { stdout } = await run('/usr/bin/osascript', ['-l', 'JavaScript', '-e', SCRIPT, bundleID, title, String(waitSeconds)])
  return JSON.parse(stdout.trim())
}
