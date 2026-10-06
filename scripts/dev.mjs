#!/usr/bin/env node
/**
 * Context Guard — development launcher.
 *
 * Runs both halves of the stack with one command, from the repository root:
 *
 *     npm run dev
 *
 * The backend is Flask (Python) and the frontend is Vite (Node). They are two
 * different runtimes in two different directories, which is the usual reason a
 * `npm run dev` typed inside `backend/` fails with ENOENT.
 *
 * Ctrl-C stops both.
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const isWindows = process.platform === 'win32'

const API_PORT = process.env.FLASK_PORT || '5000'
const WEB_PORT = process.env.VITE_PORT || '3000'

/** Vite binding: plain `vite` binds IPv6 loopback only, so 127.0.0.1 fails. */
const WEB_HOST = process.env.VITE_HOST || '127.0.0.1'

const python = process.env.PYTHON || (isWindows ? 'python.exe' : 'python')

// Spawning `npx.cmd` with shell:false throws EINVAL on Node 24 (Windows blocks
// .cmd/.bat without a shell), so run Vite's own JS entry with this Node binary.
// That is also slightly faster and does not depend on npx being on PATH.
const viteBin = join(root, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js')

const targets = [
  {
    name: 'api',
    colour: '\u001b[36m', // cyan
    cwd: resolve(root, 'backend'),
    command: python,
    args: ['app.py'],
    hint: `${python} app.py  →  http://127.0.0.1:${API_PORT}`,
  },
  {
    name: 'web',
    colour: '\u001b[35m', // magenta
    cwd: resolve(root, 'frontend'),
    command: existsSync(viteBin) ? process.execPath : python,
    args: existsSync(viteBin)
      ? [viteBin, '--host', WEB_HOST, '--port', WEB_PORT]
      : ['-m', 'vite', '--host', WEB_HOST, '--port', WEB_PORT],
    hint: `vite --host ${WEB_HOST} --port ${WEB_PORT}  →  http://${WEB_HOST}:${WEB_PORT}`,
  },
]

const RESET = '\u001b[0m'
const DIM = '\u001b[2m'

for (const target of targets) {
  if (!existsSync(target.cwd)) {
    console.error(`Cannot find ${target.cwd}. Run this from the repository root.`)
    process.exit(1)
  }
}

if (!existsSync(viteBin)) {
  console.error(
    `Vite is not installed. Run:  npm run install:web   (or: cd frontend && npm install)`,
  )
  process.exit(1)
}

console.log(`${DIM}Context Guard — starting backend and frontend${RESET}`)

const children = []

function start(target) {
  console.log(`${target.colour}[${target.name}]${RESET} ${DIM}${target.hint}${RESET}`)

  const child = spawn(target.command, target.args, {
    cwd: target.cwd,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
    shell: false,
  })

  const prefix = `${target.colour}[${target.name}]${RESET} `

  const pipe = (stream) => {
    stream.setEncoding('utf8')
    let buffer = ''
    stream.on('data', (chunk) => {
      buffer += chunk
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line.trim()) console.log(prefix + line)
      }
    })
  }

  pipe(child.stdout)
  pipe(child.stderr)

  child.on('error', (error) => {
    console.error(`${prefix}could not start: ${error.message}`)
    if (target.name === 'api' && error.code === 'ENOENT') {
      console.error(
        `${prefix}no "${target.command}" on PATH — install Python 3.13+ or set PYTHON=<path>`,
      )
    }
    shutdown(1)
  })

  child.on('exit', (code) => {
    console.log(`${prefix}exited with code ${code}`)
    shutdown(code ?? 0)
  })

  children.push(child)
}

let stopping = false

function shutdown(code = 0) {
  if (stopping) return
  stopping = true
  for (const child of children) {
    if (!child.killed) child.kill()
  }
  setTimeout(() => process.exit(code), 300).unref()
}

process.on('SIGINT', () => shutdown(0))
process.on('SIGTERM', () => shutdown(0))

for (const target of targets) start(target)

console.log(`${DIM}Press Ctrl-C to stop both.${RESET}`)
