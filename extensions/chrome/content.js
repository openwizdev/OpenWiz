if (!globalThis.__openwizContent) {
  globalThis.__openwizContent = true;

  function collect() {
    const selection = String(window.getSelection ? window.getSelection() : "").trim().slice(0, 4000);
    let text = document.body ? document.body.innerText || "" : "";
    text = text.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim().slice(0, 20000);
    return {
      url: String(location.href || "").slice(0, 2048),
      title: String(document.title || "").slice(0, 300),
      selection,
      text
    };
  }

  function showBanner() {
    const existing = document.getElementById("openwiz-acting-host");
    if (existing) return existing;
    const host = document.createElement("div");
    host.id = "openwiz-acting-host";
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = [
      ":host { all: initial; }",
      ".bar {",
      "  position: fixed; z-index: 2147483647; top: 0; left: 0; right: 0;",
      "  display: flex; align-items: center; justify-content: space-between; gap: 12px;",
      "  padding: 10px 14px; background: #f5b942; color: #1a1200;",
      "  font: 600 14px/1.3 system-ui, sans-serif;",
      "}",
      "button { font: 600 13px/1 system-ui, sans-serif; border: 0; border-radius: 999px;",
      "  padding: 6px 12px; background: #1a1200; color: #f5b942; cursor: pointer; }"
    ].join("\n");
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.setAttribute("role", "status");
    const label = document.createElement("span");
    label.textContent = "OpenWiz agent is acting in this tab";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Revoke";
    button.addEventListener("click", () => {
      host.remove();
      chrome.runtime.sendMessage({ type: "revoke-acting" });
    });
    bar.append(label, button);
    shadow.append(style, bar);
    document.documentElement.append(host);
    return host;
  }

  function find(action) {
    if (action.selector) {
      let element;
      try {
        element = document.querySelector(action.selector);
      } catch {
        throw new Error("That selector is not valid.");
      }
      if (!element) throw new Error("Nothing matched that selector.");
      return element;
    }
    if (action.op === "type" && !action.text) {
      const field = document.querySelector(
        "textarea, input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio])"
      );
      if (!field) throw new Error("No field was found.");
      return field;
    }
    const want = String(action.text || "").trim().toLowerCase();
    if (!want) throw new Error("The action needs a target.");
    const nodes = document.querySelectorAll("button, a, input, textarea, select, label, summary, [role=button], h1, h2, h3");
    for (const element of nodes) {
      const label = [
        element.innerText || "",
        element.value || "",
        element.getAttribute("aria-label") || "",
        element.getAttribute("placeholder") || ""
      ].join(" ").trim().toLowerCase();
      if (label === want || label.includes(want)) return element;
    }
    throw new Error("Nothing on the page matched that text.");
  }

  function typeInto(element, value) {
    element.focus();
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
      element.value = value;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return;
    }
    if (element.isContentEditable) {
      element.textContent = value;
      return;
    }
    throw new Error("That element cannot take text.");
  }

  function perform(action) {
    if (action.op === "read") {
      const page = collect();
      return `Read ${page.title || "this page"} (${page.text.length} characters)`;
    }
    if (action.op === "navigate") {
      let url;
      try {
        url = new URL(action.url);
      } catch {
        throw new Error("That address is not http(s).");
      }
      if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("That address is not http(s).");
      setTimeout(() => location.assign(url.href), 80);
      return `Opening ${url.href}`;
    }
    const element = find(action);
    if (action.op === "click") {
      element.click();
      const name = String(element.innerText || element.getAttribute("aria-label") || element.id || "element").trim().slice(0, 80);
      return `Clicked ${name || "element"}`;
    }
    if (action.op === "type") {
      typeInto(element, action.value);
      return "Typed into the page";
    }
    throw new Error("That action is not supported.");
  }

  function known(action) {
    return action && (action.op === "read" || action.op === "click" || action.op === "type" || action.op === "navigate");
  }

  let bannerTimer = null;

  function scheduleHide(banner) {
    if (bannerTimer) clearTimeout(bannerTimer);
    bannerTimer = setTimeout(() => {
      bannerTimer = null;
      if (banner.isConnected) banner.remove();
    }, 700);
  }

  async function act(action) {
    if (!known(action)) return { ok: false, error: "That action is not supported." };
    const allowed = await chrome.runtime.sendMessage({ type: "can-act" });
    if (!allowed || !allowed.ok) return { ok: false, error: "permission_required" };
    const banner = showBanner();
    try {
      return { ok: true, detail: perform(action) };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : "The action failed." };
    } finally {
      scheduleHide(banner);
    }
  }

  async function bannerOnly() {
    const allowed = await chrome.runtime.sendMessage({ type: "can-act" });
    if (!allowed || !allowed.ok) return { ok: false, error: "permission_required" };
    scheduleHide(showBanner());
    return { ok: true };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || typeof message.type !== "string") return false;
    if (message.type === "read") {
      sendResponse({ ok: true, page: collect() });
      return false;
    }
    if (message.type === "banner") {
      bannerOnly().then(sendResponse, () => sendResponse({ ok: false }));
      return true;
    }
    if (message.type === "act") {
      act(message.action).then(sendResponse, () => sendResponse({ ok: false, error: "The action failed." }));
      return true;
    }
    return false;
  });
}
