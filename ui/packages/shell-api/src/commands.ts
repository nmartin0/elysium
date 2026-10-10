/**
 * One registry, and everything that invokes a command goes through it.
 *
 * DEV_UI.md 10.1: "ONE command registry as the single source of truth
 * for id, label, default binding, availability and help text. Buttons,
 * shortcuts and the palette all invoke the SAME command. Then shortcut
 * help is generated and cannot drift, and a command that is unavailable
 * is shown disabled WITH THE REASON rather than hidden."
 *
 * WHY A PALETTE AT ALL, in this product specifically: "menus do not
 * scale. Elysium has object types, saved views, actions per type, admin
 * functions and an agent. A sidebar cannot hold that, and a submenu
 * tree is a memory test. A palette turns the whole product into search
 * -- and people prefer search to menus, which only help if you already
 * understand how the menus were organised."
 *
 * DISABLED WITH THE REASON, NOT HIDDEN, is the rule that shapes this
 * type. `unavailable` carries a sentence rather than a boolean, so a
 * command cannot be made unavailable without someone writing down why.
 * Hiding it instead would be the easier code and the worse interface:
 * a person who knows the command exists and cannot find it concludes
 * the product is broken, where one who sees it greyed with "needs a
 * read grant on Customer" has learnt something.
 */

export interface Command {
  /** Stable across releases; what a binding and help text key off. */
  id: string
  label: string
  /** What the palette groups by. */
  group: string
  /**
   * Why this cannot be run right now, as a sentence shown beside the
   * greyed command. Absent means available.
   */
  unavailable?: string
  run: () => void
}

/**
 * Whether a global shortcut may fire right now.
 *
 * DEV_UI.md 10.1's first rule: "never fire a global shortcut while the
 * person is typing". Cmd/Ctrl-K is safe in a text field on most
 * platforms, but the rule is about the CLASS of mistake rather than
 * this one binding, and the registry is where the next binding will be
 * added by someone who has not read the rule.
 *
 * `isContentEditable` is checked as well as the tags, because a rich
 * text surface is a div and would otherwise look like the page
 * background.
 *
 * NOT EXPORTED, deliberately. `mayFireGlobally` below is the question a
 * listener actually has, and exporting this one invited the listener to
 * ask the wrong one -- which it did, and a browser had to find it. knip
 * would not have caught the export going unused either, because this
 * file is a declared entry point and everything it exports counts as
 * public API.
 */
function isTyping(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  if (!element || !element.tagName) return false
  const tag = element.tagName.toUpperCase()
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || element.isContentEditable === true
}

/**
 * May a global binding fire for this keystroke?
 *
 * THE RULE, STATED EXACTLY: a binding that could be TYPED must not fire
 * while somebody is typing. A binding carrying Ctrl or Cmd cannot be
 * typed, so the hazard does not apply to it -- and Superhuman's own
 * guidance, which 10.1 quotes, is to "pick a binding that does not
 * clash with typing" precisely so that it can work everywhere.
 *
 * THIS WAS TOO BROAD AT FIRST, and the browser found it: the guard
 * refused every keystroke inside a field, so Cmd-K did nothing on Query
 * -- whose question box takes focus on arrival. That is the exact
 * failure 10.1 names, "a palette that works on four screens out of
 * seven is one people stop reaching for", produced by the rule meant to
 * prevent a different one. jsdom could not see it; a real page could.
 *
 * SO THE GUARD STAYS, AIMED AT WHAT IT IS FOR. The next binding added
 * to this registry may well be a bare letter or a two-key sequence, and
 * that one must not fire mid-sentence. Expressing the rule here rather
 * than at the listener is what makes it apply to that binding without
 * its author having to rediscover this comment.
 */
export function mayFireGlobally(event: { metaKey: boolean; ctrlKey: boolean }, target: EventTarget | null): boolean {
  if (event.metaKey || event.ctrlKey) return true
  return !isTyping(target)
}

/**
 * Does this keystroke open the palette?
 *
 * Cmd-K on a Mac and Ctrl-K elsewhere, "which is what Linear, Slack and
 * Superhuman all use -- so it is already in the hands of anyone who
 * would use Elysium".
 *
 * `metaKey` AND `ctrlKey` ARE BOTH ACCEPTED rather than branched on the
 * platform. Reading the platform means reading a user-agent string,
 * which lies; accepting both costs nothing, because no keyboard sends
 * them together by accident and neither combination means anything else
 * in this application.
 */
export function opensPalette(event: {
  key: string
  metaKey: boolean
  ctrlKey: boolean
  altKey: boolean
  shiftKey: boolean
}): boolean {
  if (event.key.toLowerCase() !== 'k') return false
  if (event.altKey || event.shiftKey) return false
  return event.metaKey || event.ctrlKey
}

/**
 * The commands matching what somebody typed.
 *
 * SUBSEQUENCE, NOT SUBSTRING. Typing "bc" should find "Browse
 * Customer", which is how every palette people already use behaves --
 * matching on initials is most of what makes one feel fast.
 *
 * UNAVAILABLE COMMANDS STILL MATCH, and sort after the available ones.
 * That is the disabled-with-reason rule as a search behaviour: a
 * command you cannot run is exactly the one you most need to be told
 * about.
 */
export function matching(commands: Command[], query: string): Command[] {
  const needle = query.trim().toLowerCase()
  if (needle === '') {
    return [...commands].sort(byUnavailableLast)
  }

  return commands
    .map((command) => ({ command, rank: rankOf(command, needle) }))
    .filter((scored) => scored.rank < NO_MATCH)
    .sort(
      (a, b) =>
        Number(Boolean(a.command.unavailable)) - Number(Boolean(b.command.unavailable)) ||
        a.rank - b.rank ||
        a.command.label.localeCompare(b.command.label),
    )
    .map((scored) => scored.command)
}

function byUnavailableLast(a: Command, b: Command): number {
  return Number(Boolean(a.unavailable)) - Number(Boolean(b.unavailable))
}

/**
 * HOW GOOD A MATCH IS, LOW IS BETTER.
 *
 * FILTERING ALONE IS NOT ENOUGH, and a browser is what showed it. A
 * loose subsequence over "group label" matched almost everything:
 * typing "br" returned Approvals and Query beside Browse, because
 * "o-B-jects ... que-R-y" is a subsequence too. With six commands that
 * is untidy; with object types, saved views and an action list per type
 * -- the surface 10.1 says a menu cannot hold -- it is noise, and a
 * palette whose first hit is arbitrary is one people stop trusting.
 *
 * SO RANK RATHER THAN NARROW. Everything that matches is still listed,
 * because "a command you cannot find looks broken" is the rule this
 * whole module is shaped by; the weak matches simply fall below the
 * strong ones, and below the fold.
 *
 * THE TIERS, IN THE ORDER PEOPLE EXPECT:
 *   0  the label starts with what was typed -- "br" -> Browse
 *   1  the label contains it -- "ove" -> Discover
 *   2  it matches the words' initials -- "bc" -> Browse Customer,
 *      which 10.1 calls out as most of what makes a palette feel fast
 *   3  a subsequence of the label
 *   4  a subsequence of the group and label together, the loosest
 *      thing that still counts as a find
 */
const NO_MATCH = 5

function rankOf(command: Command, needle: string): number {
  const label = command.label.toLowerCase()
  if (label.startsWith(needle)) return 0
  if (label.includes(needle)) return 1
  if (initialsOf(label).startsWith(needle)) return 2
  if (isSubsequence(needle, label)) return 3
  if (isSubsequence(needle, `${command.group} ${label}`.toLowerCase())) return 4
  return NO_MATCH
}

function initialsOf(text: string): string {
  return text
    .split(/[^a-z0-9]+/i)
    .filter(Boolean)
    .map((word) => word[0]!)
    .join('')
}

function isSubsequence(needle: string, haystack: string): boolean {
  let at = 0
  for (const character of haystack) {
    if (character === needle[at]) at += 1
    if (at === needle.length) return true
  }
  return at === needle.length
}
