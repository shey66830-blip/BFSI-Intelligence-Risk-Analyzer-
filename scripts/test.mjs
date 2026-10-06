#!/usr/bin/env node
/**
 * Context Guard — test runner.
 *
 *     npm test              # both suites
 *     npm test -- rbac      # one suite
 *
 * Sets PYTHONIOENCODING so the ₹ and box-drawing characters in the reports
 * survive the console on Windows, and reports a non-zero exit if either
 * suite fails.
 */

import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const isWindows = process.platform === 'win32'
const python = process.env.PYTHON || (isWindows ? 'python.exe' : 'python')

const suites = [
  { name: 'pipeline', file: 'test_pipeline.py', label: '12-stage investigation pipeline' },
  { name: 'rbac', file: 'test_rbac.py', label: 'authentication, roles and privacy' },
  { name: 'workflow', file: 'test_workflow.py', label: 'reports, evidence, access and audit' },
  { name: 'security', file: 'test_security.py', label: 'credential, session, authorisation and audit invariants' },
  { name: 'controls', file: 'test_security_controls.py', label: 'hardening, origin trust, throttling, validation, posture and privacy' },
  { name: 'docs', file: 'test_documentation.py', label: 'documentation drift: the gap register, roadmap and README against the code' },
]

const filter = process.argv.slice(2).filter((arg) => !arg.startsWith('-'))
const selected = filter.length
  ? suites.filter((suite) => filter.some((f) => suite.name.includes(f) || suite.file.includes(f)))
  : suites

if (!selected.length) {
  console.error(`No suite matched ${filter.join(', ')}. Try: ${suites.map((s) => s.name).join(', ')}`)
  process.exit(1)
}

const results = []

for (const suite of selected) {
  console.log(`\n\u001b[1m${suite.file}\u001b[0m — ${suite.label}`)
  const started = Date.now()
  const run = spawnSync(python, [suite.file], {
    cwd: resolve(root, 'backend'),
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
    encoding: 'utf8',
  })

  const output = `${run.stdout ?? ''}${run.stderr ?? ''}`
  // The suites print their own summaries; show the tail so failures stay visible.
  const lines = output.trimEnd().split('\n')
  const tail = lines.filter((line) => /FAIL|Traceback|Error|passed|failed/.test(line))
  console.log(tail.length ? tail.slice(-8).join('\n') : lines.slice(-8).join('\n'))

  results.push({
    suite,
    ok: run.status === 0,
    seconds: ((Date.now() - started) / 1000).toFixed(1),
  })
}

// The interface has tests too. They run on Node's built-in runner, so there is no
// dependency to install or keep current, and a full `npm test` cannot skip them.
if (!filter.length || filter.some((f) => f.includes('frontend') || f.includes('format'))) {
  console.log(`\n\u001b[1mfrontend/src/lib\u001b[0m — shared formatting and statement-gate helpers`)
  const started = Date.now()
  // Passed as a glob rather than a directory: Node expands it itself, so this works
  // the same whether or not a shell is in the middle.
  const run = spawnSync(process.execPath, ['--test', 'src/lib/*.test.js'], {
    cwd: resolve(root, 'frontend'),
    encoding: 'utf8',
  })
  const output = `${run.stdout ?? ''}${run.stderr ?? ''}`
  const lines = output.trimEnd().split('\n')
  const interesting = lines.filter((line) => /not ok|^# (pass|fail)/.test(line))
  console.log(interesting.length ? interesting.slice(0, 8).join('\n') : lines.slice(-6).join('\n'))
  results.push({
    suite: { file: 'format.test.js', label: 'shared formatting and statement-gate helpers' },
    ok: run.status === 0,
    seconds: ((Date.now() - started) / 1000).toFixed(1),
  })
}

console.log('')
for (const { suite, ok, seconds } of results) {
  const mark = ok ? '\u001b[32mPASS\u001b[0m' : '\u001b[31mFAIL\u001b[0m'
  console.log(`  ${mark}  ${suite.file}  (${seconds}s)`)
}

const failed = results.filter((result) => !result.ok)
if (failed.length) {
  console.error(`\n${failed.length} suite(s) failed.`)
  process.exit(1)
}
console.log(`\nAll ${results.length} suite(s) passed.`)
