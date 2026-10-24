// Browse held to what every module is held to (@elysium/testing/
// conformance). Its exceptions, each with its reason, would be in
// ../module.conformance.json.
//
// A SCHEMA WITH ONE TYPE, published by the host as the page's would be:
// with the suite's default, an empty one, the search page has nothing to
// look up and reads nothing.
import { describeModule } from '@elysium/testing/conformance'
import { join } from 'node:path'
import { activate } from './module'

describeModule({
  folder: join(import.meta.dirname, '..'),
  activate,
  hostValues: { visibleSchema: { Customer: { fields: { name: { type: 'string' } } } } },
})
