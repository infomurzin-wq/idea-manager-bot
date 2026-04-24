#!/usr/bin/env node

const fs = require("fs/promises");
const path = require("path");
const { marked } = require("marked");
const { chromium } = require("playwright");

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
].filter(Boolean);

function usage() {
  console.error(
    "Usage: export_report_pdf.cjs <input.md> [output.pdf]\n" +
      "Exports a Markdown report to PDF using Playwright."
  );
  process.exit(1);
}

function buildHtml(title, bodyHtml) {
  return `<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${title}</title>
    <style>
      :root {
        color-scheme: light;
        --text: #1f2937;
        --muted: #6b7280;
        --border: #d1d5db;
        --surface: #ffffff;
        --surface-2: #f8fafc;
        --accent: #0f766e;
      }

      * {
        box-sizing: border-box;
      }

      body {
        margin: 0;
        background: #eef2f7;
        color: var(--text);
        font-family: "SF Pro Text", "Segoe UI", sans-serif;
        font-size: 13px;
        line-height: 1.42;
        orphans: 3;
        widows: 3;
      }

      main {
        max-width: 860px;
        margin: 0 auto;
        padding: 20px 18px 28px;
      }

      article {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 22px 24px;
        box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
      }

      h1,
      h2,
      h3,
      h4 {
        margin: 1.15em 0 0.4em;
        line-height: 1.2;
        break-after: avoid-page;
        page-break-after: avoid;
      }

      h1 {
        margin-top: 0;
        font-size: 1.65rem;
      }

      h2 {
        padding-top: 0.3rem;
        border-top: 1px solid #e5e7eb;
        font-size: 1.2rem;
        margin-top: 1.4rem;
      }

      h3 {
        font-size: 1.02rem;
        margin-top: 1.2rem;
      }

      h4 {
        font-size: 0.92rem;
      }

      p,
      ul,
      ol,
      table,
      blockquote {
        margin: 0 0 0.72rem;
      }

      ul,
      ol {
        padding-left: 1.1rem;
      }

      li + li {
        margin-top: 0.18rem;
      }

      hr {
        border: 0;
        border-top: 1px solid #e5e7eb;
        margin: 1rem 0;
      }

      code {
        background: var(--surface-2);
        border: 1px solid #e5e7eb;
        border-radius: 4px;
        padding: 0.04rem 0.22rem;
        font-size: 0.88em;
      }

      pre {
        background: #0f172a;
        color: #e2e8f0;
        border-radius: 8px;
        padding: 10px 12px;
        overflow: auto;
      }

      pre code {
        background: transparent;
        border: 0;
        color: inherit;
        padding: 0;
      }

      a {
        color: var(--accent);
        text-decoration: none;
      }

      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.8rem;
        table-layout: fixed;
      }

      thead {
        background: var(--surface-2);
      }

      th,
      td {
        border: 1px solid #e5e7eb;
        text-align: left;
        vertical-align: top;
        padding: 5px 6px;
        word-wrap: break-word;
        overflow-wrap: anywhere;
      }

      th {
        font-size: 0.76rem;
        letter-spacing: 0.01em;
      }

      tbody tr:nth-child(even) {
        background: #fbfcfd;
      }

      table,
      tr,
      img,
      blockquote,
      pre {
        break-inside: avoid-page;
        page-break-inside: avoid;
      }

      blockquote {
        margin-left: 0;
        padding: 0.55rem 0.8rem;
        border-left: 4px solid #99f6e4;
        background: #f0fdfa;
        color: #134e4a;
      }

      h3 + p,
      h3 + ul,
      h3 + table,
      h4 + p,
      h4 + ul,
      h4 + table {
        break-before: avoid-page;
        page-break-before: avoid;
      }

      .markdown-body > :first-child {
        margin-top: 0;
      }

      .markdown-body > :last-child {
        margin-bottom: 0;
      }

      @page {
        size: A4;
        margin: 9mm 8mm 10mm;
      }

      @media print {
        body {
          background: #ffffff;
          font-size: 11.2px;
          line-height: 1.34;
        }

        main {
          max-width: none;
          padding: 0;
        }

        article {
          border: 0;
          border-radius: 0;
          box-shadow: none;
          padding: 0;
        }

        a {
          color: inherit;
        }
      }
    </style>
  </head>
  <body>
    <main>
      <article class="markdown-body">
        ${bodyHtml}
      </article>
    </main>
  </body>
</html>`;
}

async function main() {
  const input = process.argv[2];
  if (!input) {
    usage();
  }

  const inputPath = path.resolve(input);
  const outputPath = path.resolve(
    process.argv[3] || inputPath.replace(/\.md$/i, ".pdf")
  );

  const markdown = await fs.readFile(inputPath, "utf8");
  const title = path.basename(inputPath, path.extname(inputPath));
  const bodyHtml = marked.parse(markdown);
  const html = buildHtml(title, bodyHtml);

  let executablePath;
  for (const candidate of CHROME_CANDIDATES) {
    try {
      await fs.access(candidate);
      executablePath = candidate;
      break;
    } catch {
      // Try the next browser candidate.
    }
  }

  const browser = await chromium.launch({
    headless: true,
    executablePath,
  });
  try {
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: "load" });
    await page.pdf({
      path: outputPath,
      format: "A4",
      printBackground: true,
      preferCSSPageSize: true,
    });
  } finally {
    await browser.close();
  }

  console.log(outputPath);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
