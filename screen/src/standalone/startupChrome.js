import { startApplicationChrome } from '../app/startupChrome.js';
import { initKeySetup } from '../keySetup.js';
import { isEmbedded } from '../embedFlag.js';
export function startStandaloneChrome(options) {
  return startApplicationChrome({
    // Fork: an embedded globe has no key setup (it asks /api/setup/status).
    initializeSettings: isEmbedded() ? undefined : initKeySetup,
    ...options,
  });
}
