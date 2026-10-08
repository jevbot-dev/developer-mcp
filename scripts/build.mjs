// Bundle the server into one file Jevbot's own Node can run, and with --zip the
// release archive the app store installs: developer-mcp-<version>.zip holding
// a single developer-mcp/ folder.
//
//   npm run build      dist/developer-mcp/server.mjs
//   npm run package    + release/developer-mcp-<version>.zip and its sha256
//
// The archive is reproducible: the same source and lockfile give the same
// bytes on any machine, so a release can be rebuilt and compared. Entries are
// stored, not deflated (zlib versions compress differently), with a fixed
// time and fixed permissions.

import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { crc32 } from 'node:zlib'
import { build } from 'esbuild'

const { version } = JSON.parse(readFileSync('package.json', 'utf8'))
const folder = 'dist/developer-mcp'

rmSync('dist', { recursive: true, force: true })
await build({
  entryPoints: ['src/server.mjs'],
  outfile: `${folder}/server.mjs`,
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node24',
  // Some dependencies are CommonJS and call require().
  banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
  legalComments: 'none',
})
console.log(`built ${folder}/server.mjs`)

/** A zip of stored entries, 1980-01-01 00:00, 0755 folders and 0644 files. */
function zip(entries) {
  const locals = [], centrals = []
  let offset = 0
  for (const { name, data } of entries) {
    const dir = name.endsWith('/')
    const body = data ?? Buffer.alloc(0)
    const path = Buffer.from(name)
    const crc = crc32(body)
    const local = Buffer.alloc(30)
    local.writeUInt32LE(0x04034b50, 0)
    local.writeUInt16LE(10, 4)                // version needed: 1.0, stored
    local.writeUInt16LE(0, 6)                 // flags
    local.writeUInt16LE(0, 8)                 // method: stored
    local.writeUInt16LE(0, 10)                // time 00:00
    local.writeUInt16LE((0 << 9) | (1 << 5) | 1, 12) // date 1980-01-01
    local.writeUInt32LE(crc, 14)
    local.writeUInt32LE(body.length, 18)
    local.writeUInt32LE(body.length, 22)
    local.writeUInt16LE(path.length, 26)
    local.writeUInt16LE(0, 28)
    const central = Buffer.alloc(46)
    central.writeUInt32LE(0x02014b50, 0)
    central.writeUInt16LE((3 << 8) | 10, 4)   // made by: Unix
    local.copy(central, 6, 4, 30)             // version needed … name length, as in the local header
    central.writeUInt16LE(0, 30)              // extra
    central.writeUInt16LE(0, 32)              // comment
    central.writeUInt16LE(0, 34)              // disk
    central.writeUInt16LE(0, 36)              // internal attributes
    central.writeUInt32LE((((dir ? 0o40755 : 0o100644) << 16) | (dir ? 0x10 : 0)) >>> 0, 38)
    central.writeUInt32LE(offset, 42)
    locals.push(local, path, body)
    centrals.push(central, path)
    offset += local.length + path.length + body.length
  }
  const directory = Buffer.concat(centrals)
  const end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0)
  end.writeUInt16LE(entries.length, 8)
  end.writeUInt16LE(entries.length, 10)
  end.writeUInt32LE(directory.length, 12)
  end.writeUInt32LE(offset, 16)
  return Buffer.concat([...locals, directory, end])
}

if (process.argv.includes('--zip')) {
  const out = `release/developer-mcp-${version}.zip`
  mkdirSync('release', { recursive: true })
  const archive = zip([
    { name: 'developer-mcp/' },
    { name: 'developer-mcp/server.mjs', data: readFileSync(`${folder}/server.mjs`) },
  ])
  writeFileSync(out, archive)
  const sha256 = createHash('sha256').update(archive).digest('hex')
  writeFileSync(`${out}.sha256`, `${sha256}  developer-mcp-${version}.zip\n`)
  console.log(`${out}\nsha256 ${sha256}`)
}
