#!/usr/bin/env node
// i18n checks.
//
// 1. Parity: fails (exit 1) if the EN and FR locale files drift apart — a key
//    present in one but not the other, or an empty/whitespace-only value.
// 2. Usage: scans src/ for static `t('...')` / `$t('...')` calls and fails if
//    a used key is missing from the locales. Keys built dynamically (template
//    literals, variables) can't be checked statically and are skipped.
// 3. Orphans: keys defined in the locales but never referenced statically are
//    reported as a WARNING only — dynamic keys (e.g. `t(\`ip.status.${s}\`)`,
//    router `titleKey` meta) make orphan detection unreliable, so this never
//    fails the build.
//
// Run locally with `npm run i18n:check`; the CI frontend job runs it on every
// PR so a half-translated feature can't land.

import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, relative } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const srcDir = join(here, '..', 'src')
const localesDir = join(srcDir, 'i18n', 'locales')

/** @type {Record<string, string>} flattened "a.b.c" -> leaf value */
function flatten(obj, prefix = '', acc = {}) {
  for (const key of Object.keys(obj)) {
    const full = prefix ? `${prefix}.${key}` : key
    const value = obj[key]
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      flatten(value, full, acc)
    } else {
      acc[full] = value
    }
  }
  return acc
}

function load(locale) {
  const raw = readFileSync(join(localesDir, `${locale}.json`), 'utf8')
  return flatten(JSON.parse(raw))
}

const en = load('en')
const fr = load('fr')

const enKeys = new Set(Object.keys(en))
const frKeys = new Set(Object.keys(fr))

// --- 1. Parity -------------------------------------------------------------

const missingInFr = [...enKeys].filter((k) => !frKeys.has(k)).sort()
const missingInEn = [...frKeys].filter((k) => !enKeys.has(k)).sort()

const emptyEn = Object.entries(en)
  .filter(([, v]) => typeof v === 'string' && v.trim() === '')
  .map(([k]) => k)
const emptyFr = Object.entries(fr)
  .filter(([, v]) => typeof v === 'string' && v.trim() === '')
  .map(([k]) => k)

// --- 2. Usage scan ---------------------------------------------------------

/** Recursively collect .vue/.ts source files, skipping generated .d.ts. */
function sourceFiles(dir) {
  const out = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      out.push(...sourceFiles(full))
    } else if (/\.(vue|ts)$/.test(entry.name) && !entry.name.endsWith('.d.ts')) {
      out.push(full)
    }
  }
  return out
}

// Static translation calls only: `t('key')`, `$t("key")`, `i18n.global.t('key')`.
// The lookbehind rejects identifiers that merely end in `t` (split(, sort(, …).
// Template literals and variable keys are intentionally NOT matched — they are
// dynamic and cannot be resolved statically.
const CALL_RE = /(?<![\w$])\$?t\(\s*(['"])((?:\\.|(?!\1).)+)\1/g

/** @type {Map<string, string[]>} key -> ["path:line", ...] */
const usages = new Map()
for (const file of sourceFiles(srcDir)) {
  const text = readFileSync(file, 'utf8')
  for (const match of text.matchAll(CALL_RE)) {
    const key = match[2]
    const line = text.slice(0, match.index).split('\n').length
    const loc = `${relative(join(here, '..'), file).replaceAll('\\', '/')}:${line}`
    if (!usages.has(key)) usages.set(key, [])
    usages.get(key).push(loc)
  }
}

const undefinedKeys = [...usages.keys()].filter((k) => !enKeys.has(k) && !frKeys.has(k)).sort()

// --- 3. Orphans (warning only) ----------------------------------------------

const unusedKeys = [...enKeys].filter((k) => !usages.has(k)).sort()

// --- Report ------------------------------------------------------------------

const problems = []
if (missingInFr.length)
  problems.push(`Missing in fr.json (${missingInFr.length}):\n  ${missingInFr.join('\n  ')}`)
if (missingInEn.length)
  problems.push(`Missing in en.json (${missingInEn.length}):\n  ${missingInEn.join('\n  ')}`)
if (emptyEn.length)
  problems.push(`Empty values in en.json (${emptyEn.length}):\n  ${emptyEn.join('\n  ')}`)
if (emptyFr.length)
  problems.push(`Empty values in fr.json (${emptyFr.length}):\n  ${emptyFr.join('\n  ')}`)
if (undefinedKeys.length)
  problems.push(
    `Keys used in src/ but missing from the locales (${undefinedKeys.length}):\n` +
      undefinedKeys.map((k) => `  ${k}  (${usages.get(k).slice(0, 3).join(', ')})`).join('\n'),
  )

if (problems.length) {
  console.error('i18n check FAILED:\n')
  console.error(problems.join('\n\n'))
  process.exit(1)
}

if (unusedKeys.length) {
  console.warn(
    `WARNING: ${unusedKeys.length} locale key(s) have no static t()/$t() reference in src/.\n` +
      'This is informational only — keys referenced dynamically (template literals,\n' +
      'router titleKey meta, computed key paths) cannot be detected statically:\n' +
      unusedKeys.map((k) => `  ${k}`).join('\n'),
  )
}

console.log(
  `i18n check OK — ${enKeys.size} keys, en/fr in sync, no empty values, ` +
    `${usages.size} statically referenced key(s) all defined` +
    (unusedKeys.length ? `, ${unusedKeys.length} unreferenced (warning above)` : '') +
    '.',
)
