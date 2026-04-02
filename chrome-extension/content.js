function cleanText(text) {
  return text
    .replace(/\s+/g, " ")
    .replace(/(\n\s*)+/g, "\n")
    .trim();
}

function pickRootElement() {
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
}

function extractMainContent() {
  const root = pickRootElement();
  const blocks = Array.from(root.querySelectorAll("h1, h2, h3, p, li"))
    .map((el) => el.innerText || "")
    .map((text) => text.trim())
    .filter((text) => text && text.trim().length > 0)
    .filter((text) => text.split(/\s+/).length >= 5)
    .filter((text) => !/^(Donate|Log in|Create account|Tools|View source|View history)$/i.test(text))
    .join("\n");

  const fallback = root ? root.innerText : (document.body ? document.body.innerText : "");
  const cleaned = cleanText(blocks || fallback);
  return cleaned.slice(0, 12000);
}

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action !== "GET_PAGE_TEXT") {
    return;
  }

  const content = extractMainContent();
  sendResponse({ text: content });
});
