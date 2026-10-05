/* Cookie consent.
 *
 * THE REQUIREMENTS ARE LEGAL, NOT AESTHETIC, so they are written here
 * next to the code that has to meet them:
 *
 *   PRIOR      non-essential cookies stay blocked until consent. Not
 *              "set then removed" -- never set.
 *   EQUAL      "Reject All" sits at the FIRST layer, same size and
 *              prominence as "Accept All". Regulators treat "a large,
 *              brightly coloured Accept button while hiding Reject
 *              behind a small grey text link" as a dark pattern, and
 *              dark patterns are the current enforcement priority.
 *   GRANULAR   per category, so a visitor can accept analytics and
 *              refuse marketing.
 *   WITHDRAWN  as easily as given -- hence the persistent footer link
 *              on every page.
 *   LOGGED     the choice and when it was made, as proof.
 *
 * Fines reach 20 million euro or 4% of global turnover.
 *
 * WHY NO CONSENT PLATFORM. A third-party CMP is itself a third party
 * loading on first paint, and the product this site sells is about not
 * handing data to things you have not audited. If one is adopted later
 * it belongs in the subprocessor list.
 *
 * THERE ARE NO NON-ESSENTIAL COOKIES ON THIS SITE TODAY. The banner is
 * still correct to ship: the machinery has to exist before the first
 * analytics tag does, or that tag will fire before anyone asks.
 */

;(function () {
  'use strict'

  var KEY = 'elysium.consent'
  var VERSION = 1

  /** Essential is not a choice and is not presented as one. */
  var CATEGORIES = ['analytics', 'marketing']

  function stored() {
    try {
      var raw = window.localStorage.getItem(KEY)
      if (!raw) return null
      var parsed = JSON.parse(raw)
      // A CHANGED CATEGORY SET INVALIDATES OLD CONSENT. Consent is
      // specific to what was asked; adding a category and treating the
      // old answer as covering it is consent for something nobody saw.
      return parsed && parsed.version === VERSION ? parsed : null
    } catch (error) {
      // localStorage can throw: private modes, disabled storage, a
      // full quota. No stored consent means ASK, never assume.
      return null
    }
  }

  function save(choices) {
    var record = {
      version: VERSION,
      at: new Date().toISOString(),
      choices: choices,
    }
    try {
      window.localStorage.setItem(KEY, JSON.stringify(record))
    } catch (error) {
      /* A visitor who cannot store a choice is asked again next time,
       * which is the safe direction: the alternative is treating a
       * failed write as consent. */
    }
    window.dispatchEvent(new CustomEvent('elysium:consent', { detail: record }))
    return record
  }

  function allOf(value) {
    var choices = {}
    CATEGORIES.forEach(function (name) {
      choices[name] = value
    })
    return choices
  }

  function readForm(root) {
    var choices = {}
    CATEGORIES.forEach(function (name) {
      var box = root.querySelector('[data-consent-category="' + name + '"]')
      choices[name] = Boolean(box && box.checked)
    })
    return choices
  }

  function init() {
    var banner = document.querySelector('[data-consent]')
    if (!banner) return

    function close() {
      banner.hidden = true
    }

    function show() {
      banner.hidden = false
    }

    banner.addEventListener('click', function (event) {
      var action = event.target.getAttribute('data-consent-action')
      if (!action) return
      if (action === 'accept') {
        save(allOf(true))
        close()
      } else if (action === 'reject') {
        save(allOf(false))
        close()
      } else if (action === 'save') {
        save(readForm(banner))
        close()
      } else if (action === 'customise') {
        var panel = banner.querySelector('[data-consent-panel]')
        if (panel) panel.hidden = !panel.hidden
      }
    })

    // THE PERSISTENT WITHDRAWAL ROUTE, on every page's footer.
    // Withdrawal must be as easy as giving, and a buried email address
    // is not as easy.
    document.addEventListener('click', function (event) {
      if (!event.target.closest('[data-consent-reopen]')) return
      event.preventDefault()
      var current = stored()
      if (current) {
        CATEGORIES.forEach(function (name) {
          var box = banner.querySelector('[data-consent-category="' + name + '"]')
          if (box) box.checked = Boolean(current.choices[name])
        })
      }
      var panel = banner.querySelector('[data-consent-panel]')
      if (panel) panel.hidden = false
      show()
    })

    if (!stored()) show()
  }

  /** Whether a category may load. Nothing non-essential should run
   *  without asking this first. */
  window.elysiumConsent = {
    allows: function (category) {
      var current = stored()
      return Boolean(current && current.choices[category])
    },
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init)
  } else {
    init()
  }
})()
