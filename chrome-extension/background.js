const BACKEND_BASE_URLS = ["http://127.0.0.1:8000", "http://localhost:8000"];
const REQUEST_TIMEOUT_MS = 30000;

function configureSidePanelBehavior() {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
}

chrome.runtime.onInstalled.addListener(configureSidePanelBehavior);
configureSidePanelBehavior();

function sendMessageToTab(tabId, message) {
  return new Promise((resolve, reject) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}

function injectContentScript(tabId) {
  return new Promise((resolve, reject) => {
    chrome.scripting.executeScript(
      {
        target: { tabId },
        files: ["content.js"],
      },
      () => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        resolve();
      }
    );
  });
}

function extractPageTextDirectly(tabId) {
  return new Promise((resolve, reject) => {
    chrome.scripting.executeScript(
      {
        target: { tabId },
        func: () => {
          const pickRootElement = () => {
            const candidates = [
              "article",
              "main",
              "[role='main']",
              "#content",
              ".mw-body-content",
              ".article-content",
            ];
            for (const selector of candidates) {
              const el = document.querySelector(selector);
              if (el && el.innerText && el.innerText.trim().length > 200) {
                return el;
              }
            }
            return document.body;
          };

          const cleanText = (text) =>
            text
              .replace(/\s+/g, " ")
              .replace(/(\n\s*)+/g, "\n")
              .trim();

          const root = pickRootElement();
          const blocks = Array.from(root.querySelectorAll("h1, h2, h3, p, li"))
            .map((el) => el.innerText || "")
            .map((text) => text.trim())
            .filter((text) => text && text.trim().length > 0)
            .filter((text) => text.split(/\s+/).length >= 5)
            .filter((text) => !/^(Donate|Log in|Create account|Tools|View source|View history)$/i.test(text))
            .join("\n");

          const fallback = root ? root.innerText : (document.body ? document.body.innerText : "");
          return cleanText(blocks || fallback).slice(0, 12000);
        },
      },
      (results) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }

        if (!results || !results[0]) {
          reject(new Error("Unable to extract page content."));
          return;
        }

        resolve(results[0].result || "");
      }
    );
  });
}

async function getPageTextWithFallback(tab) {
  const restrictedPrefixes = ["chrome://", "edge://", "about:", "chrome-extension://"];
  if (restrictedPrefixes.some((prefix) => (tab.url || "").startsWith(prefix))) {
    throw new Error("This page is restricted. Open a normal website tab and try again.");
  }

  try {
    return await sendMessageToTab(tab.id, { action: "GET_PAGE_TEXT" });
  } catch (error) {
    try {
      await injectContentScript(tab.id);
      return await sendMessageToTab(tab.id, { action: "GET_PAGE_TEXT" });
    } catch (retryError) {
      const directText = await extractPageTextDirectly(tab.id);
      return { text: directText };
    }
  }
}

function withTimeout(url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  return fetch(url, {
    ...options,
    signal: controller.signal,
  }).finally(() => clearTimeout(timeoutId));
}

async function callBackendAnalyze(payload) {
  const errors = [];

  for (const baseUrl of BACKEND_BASE_URLS) {
    const analyzeUrl = `${baseUrl}/analyze`;
    const healthUrl = `${baseUrl}/`;
    try {
      await withTimeout(healthUrl, { method: "GET" }, 5000);
      const apiResponse = await withTimeout(analyzeUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      return { apiResponse, analyzeUrl };
    } catch (error) {
      errors.push(`${analyzeUrl}: ${error && error.message ? error.message : "unknown error"}`);
    }
  }

  throw new Error(`Cannot reach backend. Tried: ${errors.join(" | ")}`);
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action !== "ANALYZE_PAGE") {
    return;
  }

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const activeTab = tabs && tabs[0];
    if (!activeTab || typeof activeTab.id !== "number") {
      sendResponse({ result: "No active tab found." });
      return;
    }

    (async () => {
      let content = "";
      try {
        const response = await getPageTextWithFallback(activeTab);
        content = (response && response.text ? response.text : "").trim();
        if (!content) {
          sendResponse({ result: "No readable text found on this page." });
          return;
        }
      } catch (error) {
        const message = error && error.message ? error.message : "Unknown content script failure";
        sendResponse({ result: `Content script error: ${message}` });
        return;
      }

      try {
        const payload = {
          mode: request.mode,
          task: request.task || "",
          language: request.language || "Hindi",
          detail: request.detail || "short",
          content,
        };
        const { apiResponse, analyzeUrl } = await callBackendAnalyze(payload);

        const data = await apiResponse.json().catch(() => ({}));
        if (!apiResponse.ok) {
          const detail = data.detail || "Unknown backend error";
          sendResponse({
            result: `Backend error (${apiResponse.status}) from ${analyzeUrl}: ${JSON.stringify(detail)}`,
          });
          return;
        }
        sendResponse({ result: data.result || "No result returned." });
      } catch (error) {
        if (error && error.name === "AbortError") {
          sendResponse({ result: `Backend error: Request timed out after ${REQUEST_TIMEOUT_MS / 1000}s` });
          return;
        }
        sendResponse({ result: `Backend error: ${error.message}` });
      }
    })();
  });

  return true;
});
