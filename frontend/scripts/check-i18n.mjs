#!/usr/bin/env node
// i18n parity check.
//
// Fails (exit 1) if the EN and FR locale files drift apart: a key present in
// one but not the other, or an empty/whitespace-only translation. Run locally
// with `npm run i18n:check`; the CI frontend job runs it on every PR so a
// half-translated feature can't land.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const localesDir = join(here, '..', 'src', 'i18n', 'locales')

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

const missingInFr = [...enKeys].filter((k) => !frKeys.has(k)).sort()
const missingInEn = [...frKeys].filter((k) => !enKeys.has(k)).sort()

const emptyEn = Object.entries(en)
  .filter(([, v]) => typeof v === 'string' && v.trim() === '')
  .map(([k]) => k)
const emptyFr = Object.entries(fr)
  .filter(([, v]) => typeof v === 'string' && v.trim() === '')
  .map(([k]) => k)

const problems = []
if (missingInFr.length) problems.push(`Missing in fr.json (${missingInFr.length}):\n  ${missingInFr.join('\n  ')}`)
if (missingInEn.length) problems.push(`Missing in en.json (${missingInEn.length}):\n  ${missingInEn.join('\n  ')}`)
if (emptyEn.length) problems.push(`Empty values in en.json (${emptyEn.length}):\n  ${emptyEn.join('\n  ')}`)
if (emptyFr.length) problems.push(`Empty values in fr.json (${emptyFr.length}):\n  ${emptyFr.join('\n  ')}`)

if (problems.length) {
  console.error('i18n parity check FAILED:\n')
  console.error(problems.join('\n\n'))
  process.exit(1)
}

console.log(`i18n parity OK — ${enKeys.size} keys, en/fr in sync, no empty values.`)
