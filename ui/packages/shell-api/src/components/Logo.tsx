/**
 * Logo -- the Elysium mark: a bee skep, coiled straw bands under a
 * small crown, with an entrance arch cut out of the bottom.
 *
 * THE SAME DRAWING AS THE WEBSITE'S (site/img/logo.svg), so the product
 * and the site carry one mark; the geometry below is copied from it,
 * not redrawn. Two differences, both deliberate:
 *
 *   - It is inline, not an <img>, so `currentColor` is the surrounding
 *     text colour and it follows the light and dark themes for free. An
 *     <img> of an SVG cannot inherit colour.
 *   - THE ENTRANCE IS A HOLE, NOT A PAINTED SHAPE. The site paints it in
 *     the page's ground colour (--logo-ground); here the mark sits on a
 *     sidebar, a login card or a tab strip, and a painted arch would be
 *     the wrong colour on all but one of them. A mask makes it
 *     transparent whatever is behind.
 *
 * DECORATIVE BY DEFAULT: the word "Elysium" sits beside it everywhere it
 * is used, so a screen reader hears the name once. Pass `title` where
 * the mark stands alone.
 */

import { useId } from 'react'

const BANDS = [
  [2.0, 105.1, 108.0],
  [2.0, 94.9, 108.0],
  [2.1, 84.7, 107.8],
  [2.5, 74.5, 107.0],
  [3.3, 64.2, 105.3],
  [4.9, 54.0, 102.2],
  [7.6, 43.8, 96.7],
  [12.3, 33.6, 87.5],
  [20.6, 23.3, 70.9],
] as const

const ENTRANCE = 'M 47 114 a 9 12 0 0 1 18 0 z'

export default function Logo({ size = 22, title }: { size?: number; title?: string }) {
  const maskId = useId()
  return (
    <svg
      className="logo"
      viewBox="0 0 112 116"
      // The viewBox is 112 x 116; width follows height so the mark is
      // never squashed.
      height={size}
      width={(size * 112) / 116}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <mask id={maskId}>
        <rect width="112" height="116" fill="white" />
        <path d={ENTRANCE} fill="black" />
      </mask>
      <g fill="currentColor" mask={`url(#${maskId})`}>
        {BANDS.map(([x, y, width]) => (
          <rect key={y} x={x} y={y} width={width} height="9.2" rx="4.6" />
        ))}
        <path d="M 20.0 27.9 a 36 22.32 0 0 1 72 0 z" />
      </g>
    </svg>
  )
}
