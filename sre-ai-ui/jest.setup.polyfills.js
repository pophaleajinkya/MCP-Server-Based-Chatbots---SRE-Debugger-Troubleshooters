/**
 * Jest polyfills file (JavaScript version for Node.js --require preloading)
 * This runs BEFORE Jest initialization to define globals needed by Next.js
 */

// Polyfill Web Streams API first (needed by Node.js fetch)
if (typeof ReadableStream === "undefined") {
  const { ReadableStream, TransformStream, WritableStream } = require("stream/web");
  Object.assign(global, { ReadableStream, TransformStream, WritableStream });
}

// Polyfill TextEncoder/TextDecoder
if (typeof TextEncoder === "undefined") {
  const { TextEncoder, TextDecoder } = require("util");
  Object.assign(global, { TextEncoder, TextDecoder });
}

// Polyfill Cookies API needed by NextRequest
if (typeof RequestCookie === "undefined") {
  global.RequestCookie = class RequestCookie {
    constructor(name, value) {
      this.name = name;
      this.value = value;
    }
  };
}

if (typeof RequestCookies === "undefined") {
  global.RequestCookies = class RequestCookies {
    constructor(headersValue) {
      this.headersValue = headersValue;
    }
    get(name) {
      return undefined;
    }
    getAll() {
      return [];
    }
    has(name) {
      return false;
    }
    clear() {}
    set(name, value) {}
    delete(name) {}
    [Symbol.iterator]() {
      return [][Symbol.iterator]();
    }
  };
}

if (typeof ResponseCookies === "undefined") {
  global.ResponseCookies = class ResponseCookies {
    constructor() {}
    append(name, value, options) {}
    set(name, value, options) {}
    delete(name) {}
    getSetCookieHeader() {
      return undefined;
    }
    [Symbol.iterator]() {
      return [][Symbol.iterator]();
    }
  };
}

// Polyfill Request/Response types for Node environment
if (typeof Request === "undefined") {
  global.Request = class Request {};
}
if (typeof Response === "undefined") {
  global.Response = class Response {
    constructor() {
      this.ok = true;
      this.status = 200;
      this.statusText = "OK";
    }
    async json() { return {}; }
  };
}
