// Bundle the server into one file Jevbot's own Node can run, and with --zip the
// release archive the app store installs: developer-mcp-<version>.zip holding
// a single developer-mcp/ folder.
//
//   npm run build      dist/developer-mcp/server.mjs
//   npm run package    + release/developer-mcp-<version>.zip and its sha256

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdirSync, readFileSync, rmSync } from 'node:fs'
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

if (process.argv.includes('--zip')) {
  const zip = `release/developer-mcp-${version}.zip`
  mkdirSync('release', { recursive: true })
  rmSync(zip, { force: true })
  execFileSync('/usr/bin/ditto', ['-c', '-k', '--keepParent', '--norsrc', '--noextattr', folder, zip])
  const sha256 = createHash('sha256').update(readFileSync(zip)).digest('hex')
  console.log(`${zip}\nsha256 ${sha256}`)
}
