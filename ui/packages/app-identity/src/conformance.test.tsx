// The Identity review held to what every module is held to (@elysium/
// testing/conformance), its Inbox tab checked as a page is. Its
// exceptions, each with its reason, would be in ../module.conformance.json.
import { describeModule } from '@elysium/testing/conformance'
import { join } from 'node:path'
import { activate } from './module'

describeModule({ folder: join(import.meta.dirname, '..'), activate })
