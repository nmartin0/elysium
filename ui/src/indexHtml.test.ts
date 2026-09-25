/**
 * The HTML shell, which nothing else tests.
 *
 * 10-S2-01 and 10-S2-02. index.html is the one file no unit test
 * renders and no component owns: every test here mounts React into a
 * jsdom body, so the real document -- its head, its icon, its
 * no-JavaScript fallback -- is invisible to the entire suite. Both
 * defects lived there for that reason.
 *
 * WHAT THESE ASSERT is presence and wiring, not appearance. Whether
 * the noscript LOOKS right, or whether the icon renders legibly at
 * 16px, is a browser question and jsdom cannot answer it. Said here
 * rather than implied, because a green suite over this file is
 * exactly what let both slip.
 */

import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiRoot = path.resolve(here, '..')
const HTML = readFileSync(path.join(uiRoot, 'index.html'), 'utf8')

describe('index.html', () => {
  it('tells a visitor with scripting off what happened', () => {
    // Without this the root div stays empty and the page is blank
    // white -- indistinguishable from a broken deployment.
    const noscript = /<noscript>([\s\S]*?)<\/noscript>/.exec(HTML)?.[1] ?? ''

    expect(noscript).not.toBe('')
    // NOT JUST THE TAG. An empty <noscript></noscript> would satisfy
    // a presence check and help nobody, which is the shape of test
    // this file exists to avoid.
    expect(noscript.replace(/<[^>]*>/g, '').trim().length).toBeGreaterThan(80)
    expect(noscript).toMatch(/JavaScript/i)
  })

  it('styles that fallback without depending on a stylesheet', () => {
    // In dev, Vite injects CSS through the module graph -- JavaScript,
    // which is precisely what is missing when a noscript renders. A
    // fallback relying on the stylesheet is unstyled in the one mode
    // it exists for.
    const noscript = /<noscript>([\s\S]*?)<\/noscript>/.exec(HTML)?.[1] ?? ''

    expect(noscript).toMatch(/style="/)
  })

  it('declares an icon, so the browser stops asking for one', () => {
    // 10-S2-02: with no icon link the browser requests /favicon.ico
    // itself on every load. Measured against the real serving path:
    // the SPA fallback answers a navigation but declines an image
    // request, so that 404 is real rather than swallowed.
    expect(HTML).toMatch(/<link[^>]+rel="icon"/)
  })

  it('ships the icon file it points at', () => {
    // THE HALF THAT MATTERS. A link tag alone turns one 404 into a
    // different 404 while making the page look fixed -- so this
    // resolves the href against what is actually on disk.
    const href = /<link[^>]+rel="icon"[^>]+href="([^"]+)"/.exec(HTML)?.[1]

    expect(href).toBeDefined()
    // Served from Vite's publicDir, which is copied to the root of
    // dist/ at build time -- so a root-relative href maps to public/.
    const onDisk = path.join(uiRoot, 'public', (href ?? '').replace(/^\//, ''))

    expect(existsSync(onDisk), `${href} should exist at public/`).toBe(true)
  })

  it('keeps the icon a text asset, and a real one', () => {
    // SVG rather than .ico so the repository holds no binary: a text
    // file can be diffed in a patch and can carry its own reasoning.
    const href = /<link[^>]+rel="icon"[^>]+href="([^"]+)"/.exec(HTML)?.[1] ?? ''
    const svg = readFileSync(path.join(uiRoot, 'public', href.replace(/^\//, '')), 'utf8')

    expect(href).toMatch(/\.svg$/)
    expect(HTML).toMatch(/type="image\/svg\+xml"/)
    // A well-formed root element with drawn content -- not an empty
    // <svg/> that would satisfy every check above and show nothing.
    expect(svg).toMatch(/<svg[\s>]/)
    expect(svg).toMatch(/<\/svg>/)
    expect(svg).toMatch(/<(rect|path|circle|polygon)\b/)
  })
})
