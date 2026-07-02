/**
 * Custom Jest environment that extends jest-environment-jsdom to make
 * window.location.href writable for tests.
 *
 * Standard jsdom makes window.location and its properties non-configurable,
 * which prevents the usual Object.defineProperty trick from working.
 *
 * This environment intercepts navigation at the jsdom LocationImpl prototype
 * level so that:
 *  - window.location.href = "/foo"  works without triggering the
 *    "Not implemented: navigation" error
 *  - window.location.href reflects the last assigned value
 *
 * It also exposes `window.__resetLocation()` so beforeEach hooks can reset
 * the location back to "http://localhost/" without needing to reassign
 * window.location (which remains non-configurable by jsdom).
 *
 * Usage — add the following docblock to any test file that needs this:
 *   @jest-environment ./jest-environment-jsdom-location
 */

"use strict";

const JSDOMEnvironment = require("jest-environment-jsdom").TestEnvironment;

class LocationMockEnvironment extends JSDOMEnvironment {
  async setup() {
    await super.setup();

    // this.global is the jsdom Window proxy.
    // this.global._globalObject is the underlying Window implementation object.
    const windowProxy = this.global;
    const realWindow = windowProxy._globalObject ?? windowProxy;

    // -----------------------------------------------------------------------
    // Intercept navigation on the jsdom LocationImpl prototype so that
    // assignments to window.location.href update the document URL and do NOT
    // trigger jsdom's "Not implemented: navigation" console error.
    // -----------------------------------------------------------------------
    const locationObj = realWindow.location;
    const implSymbol = Object.getOwnPropertySymbols(locationObj).find(
      (s) => String(s).includes("impl")
    );

    if (implSymbol) {
      const impl = locationObj[implSymbol];
      const implProto = Object.getPrototypeOf(impl);

      // Patch the setter-navigate method so it updates the document URL.
      implProto._locationObjectSetterNavigate = function(url) {
        try {
          this._relevantDocument._URL = url;
        } catch {
          // noop
        }
      };

      // Patch the general navigate method (used by assign, replace, reload).
      implProto._locationObjectNavigate = function(url) {
        try {
          this._relevantDocument._URL = url;
        } catch {
          // noop
        }
      };
    }

    // -----------------------------------------------------------------------
    // Expose a __resetLocation() helper on the window so beforeEach blocks
    // can reset href to "http://localhost/" without reassigning window.location.
    // -----------------------------------------------------------------------
    windowProxy.__resetLocation = function() {
      try {
        windowProxy.location.href = "http://localhost/";
      } catch {
        // noop — if navigation is somehow broken, ignore
      }
    };
  }
}

module.exports = LocationMockEnvironment;
