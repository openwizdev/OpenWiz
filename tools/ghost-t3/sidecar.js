"use strict";

(function () {
  if (document.documentElement.dataset.openwizGhost === "on") return;
  var sessionId = globalThis.__openwizGhostSession;
  if (typeof sessionId !== "string" || sessionId.length === 0) return;
  var longPressMs = globalThis.__openwizGhostLongPressMs;
  if (typeof longPressMs !== "number" || !Number.isFinite(longPressMs) || longPressMs < 1) {
    longPressMs = 500;
  }
  document.documentElement.dataset.openwizGhost = "on";

  var SELECTOR = '[data-testid="composer-editor"][contenteditable="true"]';
  var TIERS = { recall: 1, small_model: 1, draft: 1 };
  var state = {
    sessionId: sessionId,
    seq: 0,
    prefix: "",
    suggestion: null,
    ghost: "",
    shown: Object.create(null),
    suppress: null,
    applying: false,
    composing: false,
  };

  function stamp(date) {
    return date.toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  function settle() {
    var next = Number(document.documentElement.dataset.openwizSettled || "0") + 1;
    document.documentElement.dataset.openwizSettled = String(next);
  }

  function composerFrom(node) {
    var el = node && node.nodeType === 1 ? node : node && node.parentElement;
    return el && el.closest ? el.closest(SELECTOR) : null;
  }

  function activeEditor() {
    var sel = window.getSelection();
    var fromSel = sel && sel.anchorNode ? composerFrom(sel.anchorNode) : null;
    if (fromSel) return fromSel;
    var focused = document.activeElement;
    if (focused && focused.matches && focused.matches(SELECTOR)) return focused;
    return document.querySelector(SELECTOR);
  }

  function prefixBeforeCaret(editor) {
    var sel = window.getSelection();
    if (!sel || !sel.isCollapsed || !sel.anchorNode || !editor.contains(sel.anchorNode)) {
      return editorText(editor);
    }
    var range = document.createRange();
    range.selectNodeContents(editor);
    range.setEnd(sel.anchorNode, sel.anchorOffset);
    return range.toString();
  }

  function editorText(editor) {
    var range = document.createRange();
    range.selectNodeContents(editor);
    return range.toString();
  }

  function caretAtEnd(editor) {
    return prefixBeforeCaret(editor) === editorText(editor);
  }

  function exactKeys(obj, keys) {
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return false;
    var got = Object.keys(obj);
    if (got.length !== keys.length) return false;
    for (var i = 0; i < keys.length; i += 1) {
      if (got.indexOf(keys[i]) === -1) return false;
    }
    return true;
  }

  function validSuggestion(suggestion, prefix) {
    if (!exactKeys(suggestion, ["id", "text", "full_text", "tier", "confidence", "latency_ms"])) {
      return false;
    }
    if (typeof suggestion.id !== "string" || suggestion.id.length === 0) return false;
    if (typeof suggestion.text !== "string" || suggestion.text.length === 0) return false;
    if (suggestion.full_text !== prefix + suggestion.text) return false;
    if (!TIERS[suggestion.tier]) return false;
    if (typeof suggestion.confidence !== "number" || !Number.isFinite(suggestion.confidence)) return false;
    if (suggestion.confidence < 0 || suggestion.confidence > 1) return false;
    if (typeof suggestion.latency_ms !== "number" || !Number.isFinite(suggestion.latency_ms)) return false;
    if (suggestion.latency_ms < 0) return false;
    var words = suggestion.text.split(/\s+/).filter(Boolean);
    return words.length >= 1 && words.length <= 8;
  }

  function extensionTransport(route, body) {
    var runtime = globalThis.chrome && globalThis.chrome.runtime;
    if (!runtime || typeof runtime.id !== "string" || !runtime.sendMessage) return null;
    return new Promise(function (resolve) {
      try {
        runtime.sendMessage({ route: route, body: body }, function (response) {
          if (runtime.lastError || !response || response.status !== 200) resolve(null);
          else resolve(response.body || null);
        });
      } catch (error) {
        resolve(null);
      }
    });
  }

  function transport(route, body) {
    if (typeof globalThis.__openwizGhostCall === "function") {
      return globalThis.__openwizGhostCall(route, body).then(function (result) {
        if (!result || result.ok !== true || !result.body || typeof result.body !== "object") return null;
        return result.body;
      }, function () { return null; });
    }
    var viaExtension = extensionTransport(route, body);
    if (viaExtension) return viaExtension;
    return Promise.resolve(null);
  }

  function host() {
    var node = document.getElementById("openwiz-ghost-host");
    if (node) return node;
    node = document.createElement("div");
    node.id = "openwiz-ghost-host";
    node.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483646;";
    node.attachShadow({ mode: "open" });
    document.documentElement.appendChild(node);
    return node;
  }

  function caretRect(editor) {
    var sel = window.getSelection();
    if (sel && sel.rangeCount && sel.anchorNode && editor.contains(sel.anchorNode)) {
      var range = sel.getRangeAt(0).cloneRange();
      range.collapse(false);
      var rects = range.getClientRects();
      var rect = rects.length ? rects[rects.length - 1] : range.getBoundingClientRect();
      if (rect && rect.height > 0) return rect;
    }
    return editor.getBoundingClientRect();
  }

  function render() {
    var root = host().shadowRoot;
    root.textContent = "";
    if (!state.ghost) return;
    var editor = activeEditor();
    if (!editor) return;
    var rect = caretRect(editor);
    var style = getComputedStyle(editor);
    var span = document.createElement("span");
    span.setAttribute("data-ghost", "");
    span.textContent = state.ghost;
    span.style.position = "fixed";
    span.style.left = rect.left + "px";
    span.style.top = (rect.top || editor.getBoundingClientRect().top) + "px";
    span.style.color = style.color;
    span.style.opacity = "0.45";
    span.style.font = style.font;
    span.style.whiteSpace = "pre";
    span.style.pointerEvents = "auto";
    span.addEventListener("pointerdown", onPointerDown);
    root.appendChild(span);
  }

  function clearSuggestion() {
    state.suggestion = null;
    state.ghost = "";
    render();
  }

  function feedback(outcome, chars) {
    var suggestion = state.suggestion;
    if (!suggestion) return Promise.resolve();
    return transport("feedback", {
      schema: "openwiz.ghost.v1",
      kind: "event",
      at: stamp(new Date()),
      suggestion_id: suggestion.id,
      session_id: state.sessionId,
      surface: "t3-code",
      outcome: outcome,
      tier: suggestion.tier,
      confidence: suggestion.confidence,
      latency_ms: suggestion.latency_ms,
      chars_accepted: chars,
    });
  }

  function insertText(editor, text) {
    editor.focus();
    state.applying = true;
    var ok = false;
    try {
      ok = document.execCommand("insertText", false, text);
    } finally {
      state.applying = false;
      state.prefix = prefixBeforeCaret(editor);
    }
    return ok;
  }

  function wordSlice(ghost) {
    var i = 0;
    while (i < ghost.length && (ghost[i] === " " || ghost[i] === "\n" || ghost[i] === "\t")) i += 1;
    if (i === ghost.length) return ghost;
    while (i < ghost.length && ghost[i] !== " " && ghost[i] !== "\n" && ghost[i] !== "\t") i += 1;
    if (i < ghost.length && ghost[i] === " ") i += 1;
    return ghost.slice(0, i);
  }

  async function accept(slice, outcome) {
    var editor = activeEditor();
    if (!editor || !state.suggestion || !slice) return;
    if (!insertText(editor, slice)) {
      settle();
      return;
    }
    state.ghost = state.ghost.slice(slice.length);
    await feedback(outcome, slice.length);
    if (!state.ghost) clearSuggestion();
    else render();
    settle();
  }

  function acceptAll() {
    return accept(state.ghost, "accepted_all");
  }

  function acceptWord() {
    return accept(wordSlice(state.ghost), "accepted_word");
  }

  async function dismiss() {
    var editor = activeEditor();
    if (!state.suggestion || !editor) return;
    state.suppress = prefixBeforeCaret(editor);
    await feedback("dismissed", 0);
    clearSuggestion();
    settle();
  }

  function suppressed(prefix) {
    if (state.suppress === null) return false;
    if (!prefix.startsWith(state.suppress)) {
      state.suppress = null;
      return false;
    }
    var rest = prefix.slice(state.suppress.length);
    if (rest === "" || /^\S*$/.test(rest) || /^\s+$/.test(rest)) return true;
    if (/^\s+\S/.test(rest)) {
      state.suppress = null;
      return false;
    }
    return true;
  }

  async function complete(prefix) {
    var my = ++state.seq;
    var body = null;
    try {
      body = await transport("complete", {
        session_id: state.sessionId,
        surface: "t3-code",
        prefix: prefix,
        seq: my,
      });
    } catch (error) {
      body = null;
    }
    if (my !== state.seq) {
      document.documentElement.dataset.openwizDropped = String(my);
      return;
    }
    var suggestion = body && body.suggestion;
    if (!body || body.schema !== "openwiz.ghost.v1" || body.seq !== my
        || !exactKeys(body, ["schema", "seq", "suggestion"])
        || (suggestion !== null && !validSuggestion(suggestion, prefix))) {
      clearSuggestion();
      settle();
      return;
    }
    var editor = activeEditor();
    if (!editor || prefixBeforeCaret(editor) !== prefix) {
      settle();
      return;
    }
    if (suggestion === null) {
      clearSuggestion();
      settle();
      return;
    }
    state.suggestion = suggestion;
    state.ghost = suggestion.text;
    render();
    if (!state.shown[suggestion.id]) {
      state.shown[suggestion.id] = true;
      await feedback("shown", 0);
    }
    settle();
  }

  async function handlePrefix(editor) {
    var next = prefixBeforeCaret(editor);
    var prev = state.prefix;
    if (next === prev) {
      settle();
      return;
    }
    state.prefix = next;
    var consumed = next.slice(prev.length);
    if (state.ghost && next.startsWith(prev) && consumed.length > 0 && state.ghost.startsWith(consumed)) {
      state.ghost = state.ghost.slice(consumed.length);
      await feedback("typed_through", consumed.length);
      if (!state.ghost) clearSuggestion();
      else render();
      settle();
      return;
    }
    if (state.suggestion) {
      await feedback("typed_over", 0);
      clearSuggestion();
    }
    if (suppressed(next)) {
      render();
      settle();
      return;
    }
    await complete(next);
  }

  function onInput(event) {
    if (state.applying || state.composing) return;
    var editor = composerFrom(event.target);
    if (!editor) return;
    void handlePrefix(editor);
  }

  function plainKey(event) {
    return !event.shiftKey && !event.altKey && !event.ctrlKey && !event.metaKey && !event.isComposing;
  }

  function onKeyDown(event) {
    if (event.isComposing || event.keyCode === 229) return;
    var editor = activeEditor();
    if (!editor) return;
    var inEditor = composerFrom(event.target) || document.activeElement === editor
      || (event.target && event.target.nodeType === 1 && editor.contains(event.target));
    if (!inEditor) return;
    if (event.key === "Tab" && plainKey(event)) {
      if (!state.ghost) return;
      event.preventDefault();
      event.stopPropagation();
      void acceptAll();
      return;
    }
    if (event.key === "Escape" && plainKey(event)) {
      if (!state.ghost) return;
      event.preventDefault();
      event.stopPropagation();
      void dismiss();
      return;
    }
    if (event.key === "ArrowRight" && !event.shiftKey && !event.metaKey && !event.isComposing) {
      var chord = event.ctrlKey || event.altKey;
      if (!state.ghost || (!chord && !caretAtEnd(editor))) return;
      event.preventDefault();
      event.stopPropagation();
      void acceptWord();
    }
  }

  function onPointerDown(event) {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    var held = false;
    var span = event.currentTarget;
    var timer = setTimeout(function () {
      held = true;
      void acceptAll();
    }, longPressMs);
    function end(acceptWordNow) {
      clearTimeout(timer);
      span.removeEventListener("pointerup", up);
      span.removeEventListener("pointercancel", cancel);
      span.removeEventListener("pointerleave", cancel);
      if (acceptWordNow && !held) void acceptWord();
    }
    function up() { end(true); }
    function cancel() { end(false); }
    span.addEventListener("pointerup", up);
    span.addEventListener("pointercancel", cancel);
    span.addEventListener("pointerleave", cancel);
  }

  document.addEventListener("keydown", onKeyDown, true);
  document.addEventListener("input", onInput, true);
  document.addEventListener("compositionstart", function () { state.composing = true; }, true);
  document.addEventListener("compositionend", function (event) {
    state.composing = false;
    var editor = composerFrom(event.target) || activeEditor();
    if (editor) void handlePrefix(editor);
  }, true);
  document.addEventListener("selectionchange", function () { if (!state.applying) render(); }, true);
  window.addEventListener("scroll", render, true);
  window.addEventListener("resize", render, true);
  render();
})();
