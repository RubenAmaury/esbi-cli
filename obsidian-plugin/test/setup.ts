// Obsidian runs the plugin in a window; the tests run in Node, where `window` is the global object.
(globalThis as { window?: unknown }).window = globalThis;
