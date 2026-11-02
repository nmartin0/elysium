// The language picker reloads the page, so it asks first while the
// reload would lose work (anything a module registers). Choosing the language already active does nothing.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { StyleManager } from './applicationShell.js';
import {
  describeUnsavedWork,
  msg,
  registerUnsavedWork,
  setLocale,
} from '../i18n/index.js';

/** Wire the shell's language choice with the given shell state. No picker
 * markup here: the picker's own behaviour is covered by localePicker.test. */
function renderSwitch({ unsaved = false } = {}) {
  const previous = {
    document: globalThis.document,
    location: globalThis.location,
    history: globalThis.history,
    confirm: globalThis.confirm,
  };
  const reloads = [];
  const prompts = [];
  let answer = true;
  globalThis.document = { getElementById: () => null };
  globalThis.location = {
    href: 'https://gev.example/#v=2',
    assign() {},
    reload: () => reloads.push(true),
  };
  globalThis.history = { replaceState() {} };
  globalThis.confirm = (text) => {
    prompts.push(text);
    return answer;
  };
  const shell = {
    _confirmLocaleReload: StyleManager.prototype._confirmLocaleReload,
    _chooseLocale: StyleManager.prototype._chooseLocale,
  };
  StyleManager.prototype._initLocaleSelector.call(shell);
  const unregisterWork = unsaved
    ? registerUnsavedWork(() => msg('unsaved fixture work'))
    : () => {};
  return {
    choose: (locale) => shell._chooseLocale(locale),
    reloads,
    prompts,
    answer: (value) => (answer = value),
    restore() {
      unregisterWork();
      Object.assign(globalThis, previous);
    },
  };
}

const storage = globalThis.localStorage;
test.before(() => {
  globalThis.localStorage = { setItem() {}, getItem: () => null };
});
test.after(() => {
  globalThis.localStorage = storage;
});

test('nothing to lose: the switch reloads without asking', () => {
  const view = renderSwitch();
  try {
    view.choose('es');
    assert.deepEqual(view.prompts, []);
    assert.equal(view.reloads.length, 1);
  } finally {
    view.restore();
  }
});

test('unsaved work: the switch asks first', () => {
  const view = renderSwitch({ unsaved: true });
  try {
    view.answer(false);
    view.choose('ru');
    assert.equal(view.prompts.length, 1);
    assert.match(view.prompts[0], /unsaved fixture work/);
    assert.equal(view.reloads.length, 0, 'declined: no reload');
    view.answer(true);
    view.choose('ru');
    assert.equal(view.reloads.length, 1, 'confirmed: reload');
  } finally {
    view.restore();
  }
});

test('modules register their own unsaved work', () => {
  const unregister = registerUnsavedWork(() => msg('drawings on the map'));
  const failing = registerUnsavedWork(() => {
    throw new Error('broken check');
  });
  const view = renderSwitch();
  try {
    view.answer(false);
    view.choose('es');
    assert.match(view.prompts[0], /drawings on the map/);
    assert.equal(view.reloads.length, 0);
  } finally {
    view.restore();
    unregister();
    failing();
  }
  assert.deepEqual(describeUnsavedWork(), []);
});

test('the prompt reads in the active language', () => {
  setLocale('es');
  const view = renderSwitch({ unsaved: true });
  try {
    view.answer(false);
    view.choose('en');
    assert.equal(view.prompts.length, 1);
    assert.doesNotMatch(view.prompts[0], /Switching language/);
  } finally {
    view.restore();
    setLocale('en');
  }
});

test('the language already active neither asks nor reloads', () => {
  const view = renderSwitch({ unsaved: true });
  try {
    assert.equal(view.choose('en'), 'unchanged');
    assert.deepEqual(view.prompts, []);
    assert.equal(view.reloads.length, 0);
  } finally {
    view.restore();
  }
});
