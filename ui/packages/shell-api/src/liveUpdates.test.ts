import { afterEach, describe, expect, it, vi } from 'vitest'

import { subscribeToChanges, subscribeToInbox } from './liveUpdates'

/** A stand-in EventSource: jsdom has none, and a real one needs a server. */
class FakeEventSource {
  static instances: FakeEventSource[] = []
  closed = false
  // BY EVENT TYPE, as a real EventSource dispatches: an `inbox` event
  // must not reach a `change` listener, nor the reverse.
  private handlers: { type: string; handler: (event: MessageEvent<string>) => void }[] = []
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }
  addEventListener(type: string, handler: (event: MessageEvent<string>) => void) {
    this.handlers.push({ type, handler })
  }
  close() {
    this.closed = true
  }
  emit(data: string, type = 'change') {
    for (const entry of this.handlers) {
      if (entry.type === type) entry.handler(new MessageEvent(type, { data }))
    }
  }
}

afterEach(() => {
  FakeEventSource.instances = []
  vi.unstubAllGlobals()
})

describe('subscribeToChanges', () => {
  it('shares ONE connection between subscribers and closes it after the last', () => {
    vi.stubGlobal('EventSource', FakeEventSource)

    const first = subscribeToChanges(() => {})
    const second = subscribeToChanges(() => {})
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0]!.url).toBe('/api/events')

    first()
    expect(FakeEventSource.instances[0]!.closed).toBe(false)
    second()
    expect(FakeEventSource.instances[0]!.closed).toBe(true)
  })

  it('hands every subscriber the hint, and ignores what is not one', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const seen: unknown[] = []
    const stop = subscribeToChanges((hint) => seen.push(hint))

    FakeEventSource.instances[0]!.emit('{"object_type":"Customer","change":"updated"}')
    FakeEventSource.instances[0]!.emit('not json')

    expect(seen).toEqual([{ object_type: 'Customer', change: 'updated' }])
    stop()
  })
})

describe('subscribeToInbox (16 October)', () => {
  it("is told when the server says this person's inbox changed, and only then", () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    let told = 0
    const stop = subscribeToInbox(() => (told += 1))

    FakeEventSource.instances[0]!.emit('{"object_type":"Customer","change":"updated"}')
    expect(told).toBe(0)
    FakeEventSource.instances[0]!.emit('{}', 'inbox')
    expect(told).toBe(1)
    stop()
  })

  it('shares the one connection with change subscribers', () => {
    vi.stubGlobal('EventSource', FakeEventSource)
    const changes = subscribeToChanges(() => {})
    const inbox = subscribeToInbox(() => {})
    expect(FakeEventSource.instances).toHaveLength(1)

    changes()
    expect(FakeEventSource.instances[0]!.closed).toBe(false)
    inbox()
    expect(FakeEventSource.instances[0]!.closed).toBe(true)
  })
})
