// @vitest-environment node
//
// NO DOM IS TOUCHED HERE, so this file does not pay for one.
import { describe, expect, it } from 'vitest'

import { type Command, matching, mayFireGlobally, opensPalette } from './commands'

const command = (id: string, label: string, group: string, unavailable?: string): Command => ({
  id,
  label,
  group,
  unavailable,
  run: () => {},
})

describe('the binding', () => {
  /**
   * Cmd-K on a Mac and Ctrl-K elsewhere, "which is what Linear, Slack
   * and Superhuman all use -- so it is already in the hands of anyone
   * who would use Elysium".
   */
  const press = (over: Partial<Parameters<typeof opensPalette>[0]>) =>
    opensPalette({ key: 'k', metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, ...over })

  it('opens on Cmd-K and on Ctrl-K', () => {
    expect(press({ metaKey: true })).toBe(true)
    expect(press({ ctrlKey: true })).toBe(true)
  })

  it('ignores a bare k, so typing never opens it', () => {
    expect(press({})).toBe(false)
  })

  it('ignores the same key with a modifier that means something else', () => {
    /** Cmd-Shift-K and Cmd-Alt-K are other people's bindings. Claiming
     *  them would break the rule about not overriding a browser or
     *  system binding without an alternative. */
    expect(press({ metaKey: true, shiftKey: true })).toBe(false)
    expect(press({ ctrlKey: true, altKey: true })).toBe(false)
  })

  it('ignores every other key', () => {
    expect(opensPalette({ key: 'j', metaKey: true, ctrlKey: false, altKey: false, shiftKey: false })).toBe(false)
  })
})

describe('never while the person is typing', () => {
  /** DEV_UI.md 10.1's first rule. */
  const element = (tag: string, editable = false) =>
    ({ tagName: tag, isContentEditable: editable }) as unknown as EventTarget

  /** Asked the way the listener asks it: an unmodified binding, which
   *  is the kind the typing rule is for. */
  const unmodified = (target: EventTarget | null) => mayFireGlobally({ metaKey: false, ctrlKey: false }, target)

  it('recognises the fields somebody types into', () => {
    for (const tag of ['INPUT', 'TEXTAREA', 'SELECT']) {
      expect(unmodified(element(tag))).toBe(false)
    }
  })

  it('recognises a rich text surface, which is a div', () => {
    expect(unmodified(element('DIV', true))).toBe(false)
  })

  it('does not treat the page itself as a text field', () => {
    expect(unmodified(element('DIV'))).toBe(true)
    expect(unmodified(null)).toBe(true)
  })

  /**
   * THE RULE AS THE LISTENER ACTUALLY ASKS IT, and the distinction a
   * browser had to teach. `isTyping` answers where the keystroke came
   * from; this answers whether a binding may fire, which is not the
   * same question for a binding carrying a modifier.
   *
   * APPLYING `isTyping` DIRECTLY WAS THE BUG: Query takes focus into
   * its question box on arrival, so the palette would not open on the
   * screen people land on -- 10.1's own "works on four screens out of
   * seven" failure, produced by 10.1's own typing rule aimed at the
   * wrong binding.
   */
  const typed = element('TEXTAREA')

  it('lets a modifier-qualified binding fire inside a field, because it cannot be typed', () => {
    expect(mayFireGlobally({ metaKey: true, ctrlKey: false }, typed)).toBe(true)
    expect(mayFireGlobally({ metaKey: false, ctrlKey: true }, typed)).toBe(true)
  })

  it('still refuses an unmodified binding inside a field -- the rule, kept for the binding it is for', () => {
    expect(mayFireGlobally({ metaKey: false, ctrlKey: false }, typed)).toBe(false)
  })
})

describe('finding a command', () => {
  const all = [
    // THE UNAVAILABLE ONE IS DECLARED FIRST, DELIBERATELY. With it
    // declared last the sort has nothing to do, and "sorts the
    // unavailable ones last" passed with the sort deleted -- caught by
    // a control, which is the only thing that catches a test like that.
    command('admin', 'Admin', 'Settings', 'needs manage:users'),
    command('browse', 'Browse Customer', 'Objects'),
    command('schema', 'Schema', 'Ontology'),
  ]

  it('matches on initials, not just substrings', () => {
    /** Typing "bc" should find "Browse Customer". Matching on initials
     *  is most of what makes a palette feel fast. */
    expect(matching(all, 'bc').map((c) => c.id)).toContain('browse')
  })

  /**
   * RANKING, WHICH A BROWSER HAD TO ASK FOR. Filtering on a loose
   * subsequence alone returned Approvals and Query beside Browse for
   * "br", because "o-B-jects ... que-R-y" is a subsequence too. The
   * weak matches are still listed -- a command you cannot find looks
   * broken -- but they go below the strong ones.
   */
  const ranked = [
    command('approvals', 'Approvals', 'Inbox'),
    command('query', 'Query', 'Objects'),
    command('browse', 'Browse Customer', 'Objects'),
  ]

  it('puts a label that starts with what was typed first', () => {
    expect(matching(ranked, 'br').map((c) => c.id)[0]).toBe('browse')
  })

  it('still lists the weak matches, after it', () => {
    expect(matching(ranked, 'br').map((c) => c.id)).toEqual(['browse', 'approvals', 'query'])
  })

  it('ranks a label that STARTS with the query above one that merely contains it', () => {
    /** Tier 0 against tier 1, and nothing else separates them -- every
     *  prefix is also a substring, so without a case where the two
     *  compete the prefix tier could be deleted with the suite still
     *  green. It was, which is how this test came to exist. */
    const both = [command('contains', 'Discover', 'Objects'), command('starts', 'Overview', 'Objects')]

    expect(matching(both, 'ove').map((c) => c.id)).toEqual(['starts', 'contains'])
  })

  it('ranks a label match above a group-only one', () => {
    const both = [command('a', 'Zebra', 'Objects'), command('b', 'Object list', 'Settings')]

    expect(matching(both, 'object').map((c) => c.id)[0]).toBe('b')
  })

  it('ranks initials above a scattered subsequence', () => {
    const both = [command('scattered', 'Backup records', 'Inbox'), command('initials', 'Browse Customer', 'Objects')]

    expect(matching(both, 'bc').map((c) => c.id)[0]).toBe('initials')
  })

  it('breaks a tie by label, so the same query never reorders between renders', () => {
    const tied = [command('b', 'Browse B', 'Objects'), command('a', 'Browse A', 'Objects')]

    expect(matching(tied, 'browse').map((c) => c.id)).toEqual(['a', 'b'])
  })

  it('keeps an unavailable command last even when it is the better match', () => {
    const mixed = [
      command('exact', 'Browse', 'Settings', 'needs manage:users'),
      command('loose', 'Backup rows', 'Objects'),
    ]

    expect(matching(mixed, 'br').map((c) => c.id)).toEqual(['loose', 'exact'])
  })

  it('returns everything for an empty query', () => {
    expect(matching(all, '  ')).toHaveLength(3)
  })

  it('searches the group as well as the label', () => {
    expect(matching(all, 'ontology').map((c) => c.id)).toEqual(['schema'])
  })

  it('still finds a command that cannot be run', () => {
    /** The disabled-with-reason rule as a search behaviour: a command
     *  you cannot run is exactly the one you most need told about. */
    expect(matching(all, 'admin').map((c) => c.id)).toEqual(['admin'])
  })

  it('sorts the unavailable ones last', () => {
    const order = matching(all, '').map((c) => c.id)

    expect(order.indexOf('admin')).toBe(order.length - 1)
  })
})
