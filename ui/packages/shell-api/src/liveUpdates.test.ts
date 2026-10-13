import { afterEach, describe, expect, it, vi } from 'vitest'

import { subscribeToChanges } from './liveUpdates'

/** A stand-in EventSource: jsdom has none, and a real one needs a server. */
class FakeEventSource {
  static instances: FakeEventSource[] = []
  closed = false
  private handlers: ((event: MessageEvent<string>) => void)[] = []
  constructor(public url: string) {
    FakeEventSource.instances.push(this)
  }
  addEventListener(_type: string, handler: (event: MessageEvent<string>) => void) {
    this.handlers.push(handler)
  }
  close() {
    this.closed = true
  }
  emit(data: string) {
    for (const handler of this.handlers) handler(new MessageEvent('change', { data }))
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
