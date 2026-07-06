const statusEl = document.getElementById("systemDocStatus");
const contentEl = document.getElementById("systemDocContent");
const tocEl = document.getElementById("systemDocToc");
const COPY_ICON =
  '<svg aria-hidden="true" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
const CHECK_ICON = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"></path></svg>';
const ERROR_ICON =
  '<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"></circle><path d="m15 9-6 6"></path><path d="m9 9 6 6"></path></svg>';

loadSystemDoc();

async function loadSystemDoc() {
  try {
    const response = await fetch("/static/system.md", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const markdown = await response.text();
    contentEl.innerHTML = renderMarkdown(markdown);
    buildSystemToc();
    setupCodeCopyButtons();
    statusEl.classList.add("hidden");
  } catch (error) {
    statusEl.textContent = `系统说明加载失败：${error.message}`;
    statusEl.classList.add("failed");
    if (tocEl) {
      tocEl.innerHTML = '<span class="system-toc-empty">目录加载失败</span>';
    }
  }
}

function buildSystemToc() {
  if (!tocEl) return;
  const headings = Array.from(contentEl.querySelectorAll("h1, h2, h3, h4, h5, h6"));
  if (!headings.length) {
    tocEl.innerHTML = '<span class="system-toc-empty">暂无标题</span>';
    return;
  }

  const usedIds = new Set();
  const tocItems = [];
  let currentBranch = null;

  const makeLink = (heading, level, id) =>
    `<a class="system-toc-link level-${level}" href="#${id}">${escapeHtml(heading.textContent || "")}</a>`;

  const flushBranch = () => {
    if (!currentBranch) return;
    if (currentBranch.children.length) {
      tocItems.push(
        `<div class="system-toc-branch"><div class="system-toc-branch-row">${currentBranch.link}<button class="system-toc-toggle" type="button" aria-expanded="false">展开</button></div><div class="system-toc-children" hidden>${currentBranch.children.join("")}</div></div>`,
      );
    } else {
      tocItems.push(currentBranch.link);
    }
    currentBranch = null;
  };

  headings.forEach((heading) => {
    const level = Number(heading.tagName.slice(1));
    const id = uniqueHeadingId(heading.textContent || "section", usedIds);
    const link = makeLink(heading, level, id);
    heading.id = id;

    if (level < 3) {
      flushBranch();
      tocItems.push(link);
    } else if (level === 3) {
      flushBranch();
      currentBranch = { link, children: [] };
    } else if (currentBranch) {
      currentBranch.children.push(link);
    } else {
      tocItems.push(link);
    }
  });
  flushBranch();

  tocEl.innerHTML = tocItems.join("");
  setupTocToggles();
}

function setupTocToggles() {
  tocEl.querySelectorAll(".system-toc-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const branch = button.closest(".system-toc-branch");
      const children = branch?.querySelector(".system-toc-children");
      if (!children) return;
      const expanded = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", String(!expanded));
      button.textContent = expanded ? "展开" : "收起";
      children.hidden = expanded;
    });
  });
}

function uniqueHeadingId(text, usedIds) {
  const base =
    text
      .trim()
      .toLowerCase()
      .replace(/[^\w\u4e00-\u9fa5]+/g, "-")
      .replace(/^-+|-+$/g, "") || "section";
  let id = base;
  let index = 2;
  while (usedIds.has(id)) {
    id = `${base}-${index}`;
    index += 1;
  }
  usedIds.add(id);
  return id;
}

function renderMarkdown(markdown) {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let paragraph = [];
  let unorderedItems = [];
  let orderedItems = [];
  let quoteLines = [];
  let codeLines = [];
  let inCode = false;
  let codeLang = "";

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${renderInline(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const flushUnorderedList = () => {
    if (!unorderedItems.length) return;
    html.push(`<ul>${unorderedItems.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ul>`);
    unorderedItems = [];
  };

  const flushOrderedList = () => {
    if (!orderedItems.length) return;
    html.push(`<ol>${orderedItems.map((item) => `<li>${renderInline(item)}</li>`).join("")}</ol>`);
    orderedItems = [];
  };

  const flushLists = () => {
    flushUnorderedList();
    flushOrderedList();
  };

  const flushBlockquote = () => {
    if (!quoteLines.length) return;
    const quoteHtml = quoteLines
      .join("\n")
      .split(/\n{2,}/)
      .map((item) => `<p>${renderInline(item.replace(/\n/g, " "))}</p>`)
      .join("");
    html.push(`<blockquote>${quoteHtml}</blockquote>`);
    quoteLines = [];
  };

  const flushCode = () => {
    const langClass = codeLang ? ` class="language-${escapeAttribute(codeLang)}"` : "";
    html.push(
      `<div class="markdown-code-block"><button class="markdown-code-copy" type="button" aria-label="复制代码" title="复制代码">${COPY_ICON}</button><pre><code${langClass}>${escapeHtml(codeLines.join("\n"))}</code></pre></div>`,
    );
    codeLines = [];
    codeLang = "";
  };

  const flushBlocks = () => {
    flushParagraph();
    flushLists();
    flushBlockquote();
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const codeFence = line.match(/^```([\w-]*)\s*$/);
    if (codeFence) {
      if (inCode) {
        flushCode();
        inCode = false;
      } else {
        flushBlocks();
        inCode = true;
        codeLang = codeFence[1] || "";
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    const trimmed = line.trim();
    if (!trimmed) {
      flushBlocks();
      continue;
    }

    if (isTableStart(lines, index)) {
      flushBlocks();
      const table = collectTable(lines, index);
      html.push(renderTable(table.rows));
      index = table.endIndex;
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushBlocks();
      const level = heading[1].length;
      html.push(`<h${level}>${renderInline(heading[2])}</h${level}>`);
      continue;
    }

    const blockquote = trimmed.match(/^>\s?(.*)$/);
    if (blockquote) {
      flushParagraph();
      flushLists();
      quoteLines.push(blockquote[1]);
      continue;
    }

    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      flushUnorderedList();
      flushBlockquote();
      orderedItems.push(ordered[1]);
      continue;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph();
      flushOrderedList();
      flushBlockquote();
      unorderedItems.push(trimmed.replace(/^[-*]\s+/, ""));
      continue;
    }

    if (/^---+$/.test(trimmed)) {
      flushBlocks();
      html.push("<hr />");
      continue;
    }

    flushLists();
    flushBlockquote();
    paragraph.push(trimmed);
  }

  if (inCode) flushCode();
  flushBlocks();
  return html.join("\n");
}

function isTableStart(lines, index) {
  const current = lines[index] || "";
  const next = lines[index + 1] || "";
  return isTableRow(current) && isTableSeparator(next);
}

function collectTable(lines, startIndex) {
  const rows = [];
  let index = startIndex;
  while (index < lines.length && isTableRow(lines[index])) {
    if (!isTableSeparator(lines[index])) {
      rows.push(splitTableRow(lines[index]));
    }
    index += 1;
  }
  return { rows, endIndex: index - 1 };
}

function isTableRow(line) {
  return /\|/.test(line.trim());
}

function isTableSeparator(line) {
  const cells = splitTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()));
}

function splitTableRow(line) {
  let value = line.trim();
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);
  return value.split("|").map((cell) => cell.trim());
}

function renderTable(rows) {
  if (!rows.length) return "";
  const [head, ...body] = rows;
  const headerHtml = head.map((cell) => `<th>${renderInline(cell)}</th>`).join("");
  const bodyHtml = body
    .map((row) => `<tr>${row.map((cell) => `<td>${renderInline(cell)}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="markdown-table-wrap"><table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
}

function renderInline(text) {
  let html = escapeHtml(text);
  html = html.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (_, alt, src) => {
    const safeSrc = sanitizeUrl(src);
    if (!safeSrc) return "";
    return `<img src="${safeSrc}" alt="${alt}" />`;
  });
  html = html.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (_, label, href) => {
    const safeHref = sanitizeUrl(href);
    if (!safeHref) return label;
    const target = /^https?:\/\//i.test(safeHref) ? ' target="_blank" rel="noreferrer"' : "";
    return `<a href="${safeHref}"${target}>${label}</a>`;
  });
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[\s>])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  html = html.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  return html;
}

function setupCodeCopyButtons() {
  contentEl.querySelectorAll(".markdown-code-copy").forEach((button) => {
    button.addEventListener("click", async () => {
      const code = button.parentElement?.querySelector("code")?.textContent || "";
      try {
        await copyText(code);
        flashCodeCopyButton(button, CHECK_ICON, "已复制");
      } catch (error) {
        flashCodeCopyButton(button, ERROR_ICON, "复制失败");
      }
    });
  });
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

function flashCodeCopyButton(button, icon, label) {
  const original = button.innerHTML;
  const originalLabel = button.getAttribute("aria-label") || "复制代码";
  button.innerHTML = icon;
  button.setAttribute("aria-label", label);
  button.setAttribute("title", label);
  window.setTimeout(() => {
    button.innerHTML = original || COPY_ICON;
    button.setAttribute("aria-label", originalLabel);
    button.setAttribute("title", originalLabel);
  }, 1200);
}

function sanitizeUrl(url) {
  const value = String(url || "").trim();
  if (/^(https?:\/\/|\/|#|\.\/|\.\.\/)/i.test(value)) {
    return escapeAttribute(value);
  }
  return "";
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/\s+/g, "-");
}
