/* CS Studio — frontend. Vanilla JS, no build step, works offline. */
"use strict";

const TOKEN = document.querySelector('meta[name="cs-token"]').content;
const BT = document.querySelector('meta[name="cs-bt"]').content;
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rid = () => Math.random().toString(36).slice(2, 12);
const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

async function api(path, { method = "GET", body, signal } = {}) {
  const o = { method, headers: { "X-CS-Token": TOKEN }, signal };
  if (body !== undefined) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
  const r = await fetch(path, o);
  let data = {};
  try { data = await r.json(); } catch (e) { data = {}; }
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function toast(msg, bad = false) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, bad ? 5200 : 2600);
  setTimeout(() => t.remove(), bad ? 5600 : 3000);
}

/* ─────────────────────────── icons ─────────────────────────── */
const ICONS = {
  plus: '<path d="M12 5v14M5 12h14"/>',
  clip: '<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
  layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  plug: '<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a6 6 0 0 1-12 0V8z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  sliders: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
  up: '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" stroke="none"/>',
  down: '<polyline points="6 9 12 15 18 9"/>',
  right: '<polyline points="9 18 15 12 9 6"/>',
  left: '<polyline points="15 18 9 12 15 6"/>',
  x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  check: '<polyline points="20 6 9 17 4 12"/>',
  refresh: '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
  panel: '<rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
  terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
  ext: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
  play: '<polygon points="6 4 20 12 6 20 6 4"/>',
  trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  book: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
  camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="M21 2l-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
  bulb: '<path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.74V17h8v-2.26A7 7 0 0 0 12 2z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
  palette: '<circle cx="13.5" cy="6.5" r="1"/><circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/><circle cx="6.5" cy="12.5" r="1"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.93 0 1.65-.75 1.65-1.69 0-.44-.18-.84-.44-1.13-.29-.29-.44-.65-.44-1.13a1.64 1.64 0 0 1 1.67-1.67h2c3.05 0 5.55-2.5 5.55-5.55C21.97 6.01 17.46 2 12 2z"/>',
  info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
  pointer: '<path d="M3 3l7.07 16.97 2.51-7.39 7.39-2.51L3 3z"/>',
  save: '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  bolt: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
  cloud: '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
};
const icon = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[n] || ""}</svg>`;
const mark = (cls = "") => `<svg class="mark ${cls}" viewBox="-80 -90 160 178" aria-hidden="true"><path class="t" d="M0,-82.7 L66.9,-44 L0,-5.3 L-66.9,-44Z"/><path class="l" d="M-71.4,-36.1 L-4.6,2.6 L-4.6,80.1 L-71.4,41.4Z"/><path class="r" d="M71.4,-36.1 L71.4,41.4 L4.6,80.1 L4.6,2.6Z"/></svg>`;

/* ─────────────────────────── state ─────────────────────────── */
const LS = {
  get(k, d) { try { const v = localStorage.getItem("cs." + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("cs." + k, JSON.stringify(v)); } catch (e) {} },
};
const S = {
  st: null,                       // /api/state
  view: "chat",
  chats: [],
  chat: newChatObj("chat"),
  codeChat: null,
  project: null,
  model: null,
  tools: LS.get("tools", { chat: { code: false, web: false, computer: false, mcp: [] },
                            code: { code: true, web: false, computer: false, mcp: [] } }),
  att: { chat: [], code: [] },
  stream: { chat: null, code: null },
  jobs: {},
  browser: { url: "", hist: [], idx: -1, reader: false, title: "" },
  artKey: null,
  chipOpen: null,
  settingsTab: "general",
  search: "",
};
const ART = new Map();

function newChatObj(kind) { return { id: null, title: "", kind, messages: [], created: Date.now() }; }

/* ─────────────────────────── markdown ─────────────────────────── */
const LANG_ALIAS = { javascript: "js", jsx: "js", ts: "js", typescript: "js", tsx: "js", mjs: "js", json: "js",
  python: "py", py: "py", python3: "py", bash: "sh", sh: "sh", shell: "sh", zsh: "sh", console: "sh",
  powershell: "sh", ps1: "sh", html: "html", htm: "html", xml: "html", svg: "html", vue: "html",
  css: "css", scss: "css", less: "css", sql: "sql", yaml: "yaml", yml: "yaml", toml: "yaml", ini: "yaml" };
const C_FAMILY = ["c", "h", "cpp", "cc", "hpp", "cxx", "java", "kt", "kts", "go", "rs", "rust", "cs", "csharp", "php",
  "rb", "ruby", "swift", "scala", "dart", "lua", "zig", "m", "mm", "groovy", "gradle"];
const KW = {
  js: "break case catch class const continue debugger default delete do else export extends finally for function if import in instanceof let new return super switch this throw try typeof var void while with yield async await of null true false undefined from as static get set",
  py: "and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield None True False self print match case",
  sh: "if then else elif fi for while do done case esac in function return export local echo cd exit set unset source sudo",
  sql: "select from where and or not insert into values update set delete create table index view drop alter join left right inner outer on group by order having limit as distinct union null primary key foreign references",
  c: "if else for while do switch case default break continue return function fn func def class struct enum interface impl trait pub public private protected static final const let var mut new delete try catch throw throws finally import package use using namespace from export extends implements async await yield true false null nil void int float double char bool boolean string long short unsigned self this super match type where in is as go defer chan map range select",
  css: "important media keyframes from to root",
  yaml: "true false null yes no on off",
};
function highlight(code, lang) {
  const lk = (lang || "").toLowerCase();
  const l = LANG_ALIAS[lk] || (C_FAMILY.includes(lk) ? "c" : "");
  if (!l) return esc(code);
  if (l === "html") return hlMarkup(code);
  const kw = (KW[l] || KW.c).split(" ").join("|");
  const com = (l === "py" || l === "sh" || l === "yaml") ? "#[^\\n]*" : l === "sql" ? "--[^\\n]*" : "\\/\\/[^\\n]*|\\/\\*[\\s\\S]*?\\*\\/";
  const str = (l === "py" ? '"""[\\s\\S]*?"""|\'\'\'[\\s\\S]*?\'\'\'|' : "") + '"(?:\\\\.|[^"\\\\\\n])*"|\'(?:\\\\.|[^\'\\\\\\n])*\'' + (l === "js" ? "|`(?:\\\\.|[^`\\\\])*`" : "");
  const re = new RegExp(`(${com})|(${str})|\\b(${kw})\\b|\\b(\\d[\\d_]*(?:\\.\\d+)?(?:e[+-]?\\d+)?)\\b|\\b([A-Za-z_$][\\w$]*)(?=\\s*\\()|\\b([A-Z][A-Za-z0-9_]*)\\b`, "g" + (l === "sql" ? "i" : ""));
  let out = "", last = 0, m;
  while ((m = re.exec(code))) {
    if (!m[0]) { re.lastIndex++; continue; }
    out += esc(code.slice(last, m.index));
    const c = m[1] ? "c" : m[2] ? "s" : m[3] ? "k" : m[4] ? "n" : m[5] ? "f" : "t";
    out += `<span class="tk-${c}">${esc(m[0])}</span>`;
    last = re.lastIndex;
  }
  return out + esc(code.slice(last));
}
function hlMarkup(code) {
  const re = /(<!--[\s\S]*?-->)|(<\/?)([\w:-]+)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)(\s*\/?>)/g;
  let out = "", last = 0, m;
  while ((m = re.exec(code))) {
    out += esc(code.slice(last, m.index));
    if (m[1]) out += `<span class="tk-c">${esc(m[1])}</span>`;
    else {
      const attrs = esc(m[4]).replace(/([^\s=]+)(\s*=\s*)((?:&quot;|&#39;)[\s\S]*?(?:&quot;|&#39;)|[^\s]+)?/g,
        (a, n, eq, v) => `<span class="tk-a">${n}</span>${eq || ""}${v ? `<span class="tk-s">${v}</span>` : ""}`);
      out += `${esc(m[2])}<span class="tk-g">${esc(m[3])}</span>${attrs}${esc(m[5])}`;
    }
    last = re.lastIndex;
  }
  return out + esc(code.slice(last));
}

function inline(t) {
  t = esc(t);
  const codes = [];
  t = t.replace(/`([^`\n]+)`/g, (m, c) => { codes.push(c); return `\u0001${codes.length - 1}\u0001`; });
  t = t.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
  t = t.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>").replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
  t = t.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
  t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" data-link="1">$1</a>');
  t = t.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" data-link="1">$2</a>');
  return t.replace(/\u0001(\d+)\u0001/g, (m, i) => `<code>${codes[+i]}</code>`);
}

const PREVIEW = ["html", "htm", "svg", "xml"];
function artTitle(lang, code) {
  const t = code.match(/<title[^>]*>([\s\S]*?)<\/title>/i) || code.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i);
  if (t) return t[1].replace(/<[^>]+>/g, "").trim().slice(0, 60);
  if (lang === "svg") return "SVG graphic";
  const first = (code.split("\n").find((l) => l.trim()) || "").trim();
  const fm = first.match(/^(?:#|\/\/|--)\s*(\S.*)$/);
  if (fm) return fm[1].slice(0, 60);
  const names = { py: "Python", js: "JavaScript", sh: "Shell script", css: "Stylesheet", sql: "SQL" };
  return (names[LANG_ALIAS[lang]] || (lang ? lang.toUpperCase() : "Code")) + " snippet";
}

function md(src, keyBase, streaming, autoOpen) {
  const blocks = [];
  src = src.replace(/```([\w.+-]*)[^\n]*\n([\s\S]*?)(```|$)/g, (m, lang, code, close) => {
    blocks.push({ lang: (lang || "").toLowerCase(), code: code.replace(/\n$/, ""), closed: !!close });
    return `\n\u0000${blocks.length - 1}\u0000\n`;
  });
  const lines = src.split("\n");
  const out = [];
  let i = 0;
  const isBlockStart = (l) => /^\u0000\d+\u0000$/.test(l) || /^#{1,4}\s/.test(l) || /^\s*([-*+]|\d+\.)\s+/.test(l) || /^>\s?/.test(l) || /^\s*(---|\*\*\*|___)\s*$/.test(l);
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if ((m = line.match(/^\u0000(\d+)\u0000$/))) { out.push(codeBlock(blocks[+m[1]], `${keyBase}:${m[1]}`, streaming, autoOpen)); i++; continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)$/))) { const n = m[1].length; out.push(`<h${n}>${inline(m[2])}</h${n}>`); i++; continue; }
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) { out.push("<hr>"); i++; continue; }
    if (/^>\s?/.test(line)) {
      const q = []; while (i < lines.length && /^>\s?/.test(lines[i])) q.push(lines[i++].replace(/^>\s?/, ""));
      out.push(`<blockquote>${md(q.join("\n"), keyBase + "q" + i, streaming)}</blockquote>`); continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && (/^\s*([-*+]|\d+\.)\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        const l = lines[i++];
        const mm = l.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
        if (mm) items.push({ ind: mm[1].length, text: mm[3] });
        else items[items.length - 1].text += " " + l.trim();
      }
      out.push(renderList(items, ordered)); continue;
    }
    if (line.includes("|") && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(lines[i + 1])) {
      const row = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = row(line); i += 2;
      const body = []; while (i < lines.length && lines[i].includes("|") && lines[i].trim()) body.push(row(lines[i++]));
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) para.push(lines[i++]);
    if (!para.length) { para.push(lines[i++]); }
    out.push(`<p>${para.map(inline).join("<br>")}</p>`);
  }
  return out.join("");
}
function renderList(items, ordered) {
  const tag = ordered ? "ol" : "ul";
  let html = `<${tag}>`, base = items.length ? items[0].ind : 0, k = 0;
  while (k < items.length) {
    const it = items[k];
    if (it.ind > base + 1) {
      const sub = []; while (k < items.length && items[k].ind > base + 1) sub.push(items[k++]);
      html = html.replace(/<\/li>$/, "") + renderList(sub, false) + "</li>"; continue;
    }
    html += `<li>${inline(it.text)}</li>`; k++;
  }
  return html + `</${tag}>`;
}
function codeBlock(b, key, streaming, autoOpen) {
  const lang = b.lang || "text";
  const lines = b.code.split("\n").length;
  const isArt = PREVIEW.includes(lang) || lines >= 18;
  ART.set(key, { lang, code: b.code, title: artTitle(lang, b.code), lines });
  if (isArt) {
    if (!b.closed && streaming) {
      return `<div class="art-card"><div class="ico"><div class="spin"></div></div><div><b>${esc(artTitle(lang, b.code))}</b><small>Writing ${esc(lang)} · ${plural(lines, "line")}</small></div></div>`;
    }
    if (autoOpen && PREVIEW.includes(lang)) autoOpen(key);
    const ic = lang === "svg" ? "image" : PREVIEW.includes(lang) ? "globe" : "code";
    return `<div class="art-card" data-act="open-art" data-k="${esc(key)}"><div class="ico">${icon(ic, "lg")}</div><div><b>${esc(artTitle(lang, b.code))}</b><small>${PREVIEW.includes(lang) ? "Click to open preview" : "Click to open"} · ${esc(lang)} · ${plural(lines, "line")}</small></div></div>`;
  }
  return `<div class="code"><div class="code-head"><span class="lang">${esc(lang)}</span><button data-act="copy-art" data-k="${esc(key)}">${icon("copy", "sm")}Copy</button></div><pre>${highlight(b.code, lang)}</pre></div>`;
}

/* ─────────────────────────── layout ─────────────────────────── */
const NAV = [
  ["chat", "chat", "Chats"], ["code", "code", "Code"], ["browser", "globe", "Browser"],
  ["artifacts", "layers", "Artifacts"], ["routines", "clock", "Routines"], ["connectors", "plug", "Connectors"],
];
function renderSide() {
  const user = (S.st && S.st.user) || "you";
  const list = S.chats.filter((c) => c.kind !== "code" && (!S.search || c.title.toLowerCase().includes(S.search.toLowerCase())));
  $("#side").innerHTML = `
    <div class="side-head"><div class="brand">${mark()}<span>CS</span></div>
      <button class="icon-btn" data-act="toggle-side" title="Close sidebar (Ctrl+B)">${icon("panel")}</button></div>
    <button class="new-chat" data-act="new-chat"><span class="plus">${icon("plus")}</span>New chat</button>
    <nav class="nav">${NAV.map(([v, ic, lbl]) => `<button class="nav-item ${S.view === v ? "active" : ""}" data-act="go" data-v="${v}">${icon(ic)}<span>${lbl}</span>${v === "routines" && S.routinesOn ? `<span class="badge">${S.routinesOn}</span>` : ""}</button>`).join("")}</nav>
    <div class="side-label">Recents</div>
    <div class="side-search">${icon("search", "sm")}<input id="side-q" placeholder="Search chats" value="${esc(S.search)}"></div>
    <div class="recents">${list.length ? list.map((c) => `<div class="chat-link ${S.view === "chat" && S.chat.id === c.id ? "active" : ""}" data-act="open-chat" data-id="${esc(c.id)}"><span>${esc(c.title || "Untitled")}</span><button class="del" data-act="del-chat" data-id="${esc(c.id)}" title="Delete">${icon("x", "sm")}</button></div>`).join("") : `<div class="side-empty">${S.search ? "No matches" : "Your chats will appear here"}</div>`}</div>
    <div class="side-foot"><div class="avatar">${esc(user.slice(0, 1))}</div><div class="who"><b>${esc(user)}</b><small>CS Framework ${esc(S.st ? S.st.version : "")}</small></div>
      <button class="icon-btn" data-act="go" data-v="settings" title="Settings (Ctrl+,)">${icon("gear")}</button></div>`;
  const q = $("#side-q");
  q.addEventListener("input", () => { S.search = q.value; const pos = q.selectionStart; renderSide(); const n = $("#side-q"); n.focus(); n.setSelectionRange(pos, pos); });
}

function renderTop() {
  const hidden = $("#app").classList.contains("side-hidden");
  let title = "";
  if (S.view === "chat") title = S.chat.messages.length ? `<div class="title editable" data-act="rename" title="Rename">${esc(S.chat.title || "New chat")}</div>` : "";
  else if (S.view === "code") title = `<div class="title">${S.project ? esc(S.project.name) : "Code"}</div>`;
  else if (S.view === "browser") title = `<div class="title">${esc(S.browser.title || "Browser")}</div>`;
  const running = Object.values(S.jobs).filter((j) => j.status === "running");
  $("#top").innerHTML = `
    ${hidden ? `<button class="icon-btn" data-act="toggle-side" title="Open sidebar">${icon("panel")}</button><button class="icon-btn" data-act="new-chat" title="New chat">${icon("plus")}</button>` : ""}
    ${title}<div class="grow"></div>
    ${running.length ? `<button class="jobs-pill" data-act="go" data-v="settings" data-tab="models"><div class="spin"></div>${esc(running[0].title)}${running.length > 1 ? ` +${running.length - 1}` : ""}</button>` : ""}`;
}

function render() { renderSide(); renderTop(); renderView(); }

function renderView() {
  const v = $("#views");
  const fns = { chat: viewChat, code: viewCode, browser: viewBrowser, artifacts: viewArtifacts,
                routines: viewRoutines, connectors: viewConnectors, settings: viewSettings };
  v.innerHTML = `<div class="view" id="view-${S.view}"></div>`;
  (fns[S.view] || viewChat)($(`#view-${S.view}`));
}

/* ─────────────────────────── routing ─────────────────────────── */
function go(view, extra) {
  const h = "#/" + view + (extra ? "/" + extra : "");
  if (location.hash !== h) location.hash = h; else route();
}
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  const view = parts[0] || "chat";
  S.view = ["chat", "code", "browser", "artifacts", "routines", "connectors", "settings"].includes(view) ? view : "chat";
  if (S.view === "chat" && parts[1] && parts[1] !== S.chat.id) {
    try { const c = await api("/api/chats/" + encodeURIComponent(parts[1])); normalizeChat(c); S.chat = c; } catch (e) { S.chat = newChatObj("chat"); }
  }
  if (S.view === "settings" && parts[1]) S.settingsTab = parts[1];
  render();
  if (S.view === "chat") focusComposer("chat");
}
function normalizeChat(c) {
  c.messages = c.messages || [];
  for (const m of c.messages) if (m.role === "assistant" && !m.segs) m.segs = [{ t: "text", v: m.content || "" }];
}

/* ─────────────────────────── models ─────────────────────────── */
function models() { return (S.st && S.st.models) || []; }
function modelById(id) { return models().find((m) => m.id === id); }
function pickDefaultModel() {
  const ms = models();
  const saved = LS.get("model", null);
  if (saved && ms.find((m) => m.id === saved)) return saved;
  const pref = S.st.prefs && S.st.prefs.default_model;
  if (pref && ms.find((m) => m.id === pref)) return pref;
  const local = ms.find((m) => m.local && m.kind !== "demo" && m.ready);
  if (local) return local.id;
  const api_ = ms.find((m) => m.kind === "api");
  return api_ ? api_.id : (S.st.demo_model || "cs-echo");
}
function modelLabel(id) {
  const m = modelById(id);
  if (!m) return id || "Choose a model";
  return m.kind === "api" ? `${m.name}` : m.name;
}
function setModel(id) { S.model = id; LS.set("model", id); api("/api/prefs", { method: "POST", body: { prefs: { default_model: id } } }).catch(() => {}); refreshComposers(); }

/* ─────────────────────────── chat view ─────────────────────────── */
const CHIPS = [
  { k: "Write", i: "pen", s: ["Draft a warm, short email declining a meeting invite", "Write the opening paragraph of a mystery set in a lighthouse", "Turn these notes into a clear project update: "] },
  { k: "Code", i: "code", s: ["Build a single-file HTML page with an elegant live clock", "Write a Python script that renames photos by the date they were taken", "Explain the difference between threads and processes"] },
  { k: "Learn", i: "bulb", s: ["Explain how a transformer language model works, simply", "What actually causes the seasons on Earth?", "Teach me SQL joins with a tiny example"] },
  { k: "Browse", i: "globe", s: ["Read news.ycombinator.com and summarize the top stories", "Open en.wikipedia.org and tell me today's featured article"], tools: "web" },
  { k: "Automate", i: "clock", s: ["Every morning at 9:00, give me one focused tip for the day", "Every hour, remind me to stand up and stretch"], routine: true },
];
function greeting() {
  const h = new Date().getHours();
  const part = h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  const n = (S.st && S.st.user) || "";
  return `${part}${n ? ", " + n.charAt(0).toUpperCase() + n.slice(1) : ""}`;
}
function viewChat(el) {
  if (!S.chat.messages.length) {
    const demo = S.model === (S.st && S.st.demo_model) && !models().some((m) => m.kind !== "demo");
    el.innerHTML = `<div class="hello-wrap">
      <div class="hello">${mark()}<h1>${esc(greeting())}</h1></div>
      <div id="composer-chat" class="composer-dock"></div>
      <div class="chips">${CHIPS.map((c, i) => `<button class="${S.chipOpen === i ? "on" : ""}" data-act="chip" data-i="${i}">${icon(c.i, "sm")}${c.k}</button>`).join("")}</div>
      ${S.chipOpen !== null ? `<div class="suggest">${CHIPS[S.chipOpen].s.map((s, j) => `<button data-act="suggest" data-i="${S.chipOpen}" data-j="${j}">${esc(s)}</button>`).join("")}</div>` : ""}
      ${demo ? `<div class="demo-note">You're using the built-in demo model. <a data-act="go" data-v="settings" data-tab="providers">Connect a free provider</a> or <a data-act="go" data-v="code">set up a local model</a> for real answers.</div>` : ""}
    </div>`;
  } else {
    el.innerHTML = `<div class="thread" id="thread-chat"><div class="msgs" id="msgs-chat"></div></div><div id="composer-chat" class="composer-dock"></div>`;
    renderThread("chat");
  }
  renderComposer("chat");
}

function chatFor(scope) { return scope === "code" ? S.codeChat : S.chat; }

function renderThread(scope, keepScroll) {
  const box = $(`#msgs-${scope}`);
  if (!box) return;
  const th = $(`#thread-${scope}`);
  const atBottom = th ? th.scrollHeight - th.scrollTop - th.clientHeight < 80 : true;
  const chat = chatFor(scope);
  const live = S.stream[scope];
  box.innerHTML = chat.messages.map((m, i) => msgHTML(m, i, scope, live && i === chat.messages.length - 1)).join("");
  if (th && (atBottom || !keepScroll)) th.scrollTop = th.scrollHeight;
}
function msgHTML(m, i, scope, streaming) {
  if (m.role === "user") {
    const atts = (m.attachments || []).map((a) => `<div class="att">${a.type === "image" ? `<img src="${esc(a.data_url)}" alt="">` : icon("file", "sm")}<span>${esc(a.name)}</span></div>`).join("");
    return `<div class="msg user"><div class="col">${atts ? `<div class="atts">${atts}</div>` : ""}<div class="bubble">${esc(m.content)}</div></div></div>`;
  }
  const chat = chatFor(scope);
  const keyBase = `${chat.id || "new"}:${i}`;
  let html = "", visible = false;
  (m.segs || []).forEach((s, si) => {
    if (s.t === "text") {
      const txt = cleanText(s.v, streaming);
      if (txt.trim()) { visible = true; html += md(txt, `${keyBase}:${si}`, streaming, streaming ? (k) => autoOpenArt(m, k) : null); }
    } else { visible = true; html += toolHTML(s, scope); }
  });
  if (m.error) html += `<div class="err">${esc(m.error)}</div>`;
  if (streaming) html += `<span class="cursor-mark">${mark("busy")}</span>`;
  const meta = m.model ? esc(modelLabel(m.model)) : "";
  const foot = streaming ? "" : `<div class="msg-foot">
      <button class="icon-btn" data-act="copy-msg" data-scope="${scope}" data-i="${i}" title="Copy">${icon("copy", "sm")}</button>
      ${i === chat.messages.length - 1 ? `<button class="icon-btn" data-act="retry" data-scope="${scope}" title="Retry">${icon("refresh", "sm")}</button>` : ""}
      <span class="meta">${meta}${m.stopped ? " · stopped" : ""}</span></div>`;
  return `<div class="msg assistant"><div class="prose">${html || (streaming ? "" : "<p></p>")}</div>${foot}</div>`;
}
function cleanText(v, streaming) {
  v = (v || "").replace(/<tool>[\s\S]*?<\/tool>/g, "").replace(/<tool_result[\s\S]*?<\/tool_result>/g, "");
  if (streaming) {
    const i = v.lastIndexOf("<tool");
    if (i >= 0 && v.indexOf("</tool>", i) < 0) v = v.slice(0, i);
    v = v.replace(/<(t|to|too|tool)?$/, "");
  }
  return v;
}
function autoOpenArt(m, key) {
  m._opened = m._opened || [];
  if (m._opened.includes(key)) return;
  m._opened.push(key);
  setTimeout(() => openArt(key, "preview"), 60);
}

// [wants to …, …ing, done]
const TOOL_TXT = {
  bash: ["run a command", "Running a command", "Ran a command"], python: ["run Python", "Running Python", "Ran Python"],
  read: ["read a file", "Reading a file", "Read a file"], write: ["write a file", "Writing a file", "Wrote a file"],
  edit: ["edit a file", "Editing a file", "Edited a file"], append: ["append to a file", "Appending to a file", "Appended to a file"],
  ls: ["list a folder", "Listing a folder", "Listed a folder"], tree: ["view the folder tree", "Viewing the tree", "Viewed the folder tree"],
  glob: ["find files", "Finding files", "Found files"], find: ["find files", "Finding files", "Found files"],
  grep: ["search files", "Searching files", "Searched files"], diff: ["compare files", "Comparing files", "Compared files"],
  wc: ["count lines", "Counting lines", "Counted lines"], browse: ["read a web page", "Reading a web page", "Read a web page"],
  web_fetch: ["fetch a URL", "Fetching a URL", "Fetched a URL"], http: ["make an HTTP request", "Making a request", "Made an HTTP request"],
  download: ["download a file", "Downloading", "Downloaded a file"], screen: ["take a screenshot", "Taking a screenshot", "Took a screenshot"],
  screen_size: ["check the screen size", "Checking the screen", "Checked the screen size"], mouse_move: ["move the mouse", "Moving the mouse", "Moved the mouse"],
  mouse_click: ["click", "Clicking", "Clicked"], mouse_drag: ["drag", "Dragging", "Dragged"], scroll: ["scroll", "Scrolling", "Scrolled"],
  key: ["press keys", "Pressing keys", "Pressed keys"], type: ["type text", "Typing", "Typed text"],
  window_list: ["list windows", "Listing windows", "Listed windows"], window_focus: ["focus a window", "Focusing a window", "Focused a window"],
  app_start: ["open an app", "Opening an app", "Opened an app"], sleep: ["wait", "Waiting", "Waited"],
  ocr: ["read text on screen", "Reading the screen", "Read text on screen"], clip_read: ["read the clipboard", "Reading the clipboard", "Read the clipboard"],
  clip_write: ["write to the clipboard", "Writing the clipboard", "Wrote to the clipboard"] };
function toolLabel(s) {
  const nm = s.name.includes("__") ? s.name.split("__").pop() : s.name;
  const t = TOOL_TXT[s.name] || [`use ${nm}`, `Using ${nm}`, `Used ${nm}`];
  if (s.status === "waiting") return "Wants to " + t[0];
  if (s.status === "running") return t[1] + "…";
  if (s.status === "denied") return "Declined: " + t[0];
  return t[2];
}
function toolIcon(n) {
  if (n.includes("__")) return "plug";
  if (["bash", "python"].includes(n)) return "terminal";
  if (["read", "write", "edit", "append", "wc", "diff"].includes(n)) return "file";
  if (["ls", "tree", "glob", "grep", "find"].includes(n)) return "search";
  if (["browse", "web_fetch", "http", "download"].includes(n)) return "globe";
  return "monitor";
}
function toolArg(a) {
  if (!a || typeof a !== "object") return "";
  return String(a.cmd ?? a.path ?? a.url ?? a.pattern ?? a.query ?? a.text ?? a.keys ?? a.title ?? a.name ?? (a.x != null ? `${a.x}, ${a.y}` : "") ?? "") || JSON.stringify(a).slice(0, 90);
}
function toolHTML(s, scope) {
  const label = toolLabel(s);
  const st = s.status === "running" ? '<div class="spin"></div>' : s.status === "waiting" ? icon("key", "sm")
    : s.status === "denied" || (s.result || "").startsWith("[tool error") ? '<span class="dot-bad"></span>' : '<span class="dot-ok"></span>';
  const approval = s.status === "waiting" && s.approval ? `<div class="approve"><p>Allow <b>${esc(s.name)}</b> to run${s.name === "bash" ? ` <code>${esc(String(s.args.cmd || "").slice(0, 140))}</code>` : ""}?</p>
    <div class="row"><button class="btn ghost sm" data-act="approve" data-id="${s.approval}" data-allow="0">Deny</button>
    <button class="btn secondary sm" data-act="approve" data-id="${s.approval}" data-allow="1" data-always="1">Always allow</button>
    <button class="btn primary sm" data-act="approve" data-id="${s.approval}" data-allow="1">Allow once</button></div></div>` : "";
  const open = s.open || s.status === "waiting";
  return `<div class="tool ${open ? "open" : ""}" data-tid="${esc(s.id)}">
    <div class="tool-row" data-act="toggle-tool" data-scope="${scope}" data-id="${esc(s.id)}">${st}${icon(toolIcon(s.name), "sm")}<span class="name">${esc(label)}</span><span class="arg">${esc(toolArg(s.args))}</span>${icon("right", "sm chev")}</div>
    <div class="tool-body"><div class="lbl">Input</div><pre>${esc(JSON.stringify(s.args || {}, null, 2))}</pre>
    ${s.result != null ? `<div class="lbl">Result</div><pre>${esc(s.result)}</pre>` : ""}
    ${s.image ? `<img src="${esc(s.image)}" alt="screenshot">` : ""}</div>${approval}</div>`;
}

/* ─────────────────────────── composer ─────────────────────────── */
function renderComposer(scope) {
  const host = $(`#composer-${scope}`);
  if (!host) return;
  const prev = $(`#ta-${scope}`);
  const value = prev ? prev.value : (S.draft && S.draft[scope]) || "";
  const t = S.tools[scope];
  const chips = [];
  if (scope === "chat" && t.code) chips.push(["terminal", "Files"]);
  if (t.web) chips.push(["globe", "Web"]);
  if (t.computer) chips.push(["monitor", "Computer"]);
  if (t.mcp && t.mcp.length) chips.push(["plug", `${t.mcp.length} connector${t.mcp.length > 1 ? "s" : ""}`]);
  const live = !!S.stream[scope];
  const atts = S.att[scope].map((a, i) => `<div class="att">${a.type === "image" ? `<img src="${esc(a.data_url)}" alt="">` : icon("file", "sm")}<span>${esc(a.name)}</span><button data-act="rm-att" data-scope="${scope}" data-i="${i}">${icon("x", "sm")}</button></div>`).join("");
  host.innerHTML = `<div class="inner"><div class="composer">
    ${atts ? `<div class="att-row">${atts}</div>` : ""}
    <textarea id="ta-${scope}" rows="1" placeholder="${scope === "code" ? "Ask CS to build, fix or explain…" : "How can I help you today?"}"></textarea>
    <div class="composer-bar">
      <button class="icon-btn" data-act="attach" data-scope="${scope}" title="Add files, a screenshot or a web page">${icon("plus")}</button>
      <button class="icon-btn ${chips.length ? "on" : ""}" data-act="tools-menu" data-scope="${scope}" title="Tools">${icon("sliders")}</button>
      ${chips.map(([ic, l]) => `<span class="chip-tool">${icon(ic, "sm")}${esc(l)}</span>`).join("")}
      <button class="model-btn" data-act="model-menu" data-scope="${scope}" title="Choose model"><span>${esc(modelLabel(S.model))}</span>${icon("down", "sm")}</button>
      <button class="send ${live ? "stop" : ""}" id="send-${scope}" data-act="${live ? "stop" : "send"}" data-scope="${scope}" title="${live ? "Stop" : "Send"}">${icon(live ? "stop" : "up")}</button>
    </div></div>${scope === "chat" && S.chat.messages.length ? `<div class="hint">CS can make mistakes. Check important information.</div>` : ""}</div>`;
  const ta = $(`#ta-${scope}`);
  ta.value = value;
  const size = () => { ta.style.height = "auto"; ta.style.height = Math.min(280, ta.scrollHeight) + "px"; syncSend(scope); };
  ta.addEventListener("input", size);
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!S.stream[scope]) send(scope); }
  });
  ta.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData && e.clipboardData.files || [])];
    if (files.length) { e.preventDefault(); addFiles(scope, files); }
  });
  size();
}
function syncSend(scope) {
  const b = $(`#send-${scope}`), ta = $(`#ta-${scope}`);
  if (!b || !ta || S.stream[scope]) return;
  b.disabled = !ta.value.trim() && !S.att[scope].length;
}
function refreshComposers() { ["chat", "code"].forEach((s) => renderComposer(s)); }
function focusComposer(scope) { const ta = $(`#ta-${scope}`); if (ta) setTimeout(() => ta.focus(), 30); }

async function addFiles(scope, files) {
  for (const f of files) {
    if (f.size > 12 * 1024 * 1024) { toast(`${f.name} is too large`, true); continue; }
    if (f.type.startsWith("image/")) {
      const data_url = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f); });
      S.att[scope].push({ name: f.name, type: "image", data_url });
    } else {
      const text = await f.text();
      if (/[\u0000-\u0008\u000E-\u001F]/.test(text.slice(0, 2000))) { toast(`${f.name} looks binary — only text and images are supported`, true); continue; }
      S.att[scope].push({ name: f.name, type: "text", content: text.slice(0, 400000) });
    }
  }
  renderComposer(scope); focusComposer(scope);
}

/* ─────────────────────────── streaming ─────────────────────────── */
async function send(scope, textOverride) {
  const ta = $(`#ta-${scope}`);
  const text = (textOverride ?? (ta ? ta.value : "")).trim();
  if ((!text && !S.att[scope].length) || S.stream[scope]) return;
  if (scope === "code" && !S.project) return;
  const chat = chatFor(scope);
  chat.messages.push({ role: "user", content: text, attachments: S.att[scope].slice(), ts: Date.now() });
  S.att[scope] = [];
  if (ta) ta.value = "";
  if (!chat.title) chat.title = (text || "Attachment").replace(/\s+/g, " ").slice(0, 60);
  if (scope === "chat" && chat.messages.length === 1) { S.chipOpen = null; renderView(); renderTop(); }
  await runStream(scope);
}
async function runStream(scope) {
  const chat = chatFor(scope);
  const m = { role: "assistant", content: "", segs: [{ t: "text", v: "" }], model: S.model, ts: Date.now() };
  chat.messages.push(m);
  const sid = rid();
  const ctrl = new AbortController();
  S.stream[scope] = { sid, ctrl };
  renderComposer(scope);
  let pending = false;
  const paint = () => { if (pending) return; pending = true; requestAnimationFrame(() => { pending = false; renderThread(scope, true); }); };
  paint();
  const t = S.tools[scope];
  const body = {
    model: S.model, stream_id: sid, mode: scope,
    cwd: scope === "code" && S.project ? S.project.root : undefined,
    tools: { code: scope === "code" ? true : !!t.code, web: !!t.web, computer: !!t.computer, mcp: t.mcp || [] },
    messages: chat.messages.slice(0, -1).map((x) => ({ role: x.role, content: x.content, attachments: x.attachments })),
  };
  let changedFiles = false;
  try {
    const res = await fetch("/api/chat", { method: "POST", signal: ctrl.signal,
      headers: { "Content-Type": "application/json", "X-CS-Token": TOKEN }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `HTTP ${res.status}`);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "", done = false;
    while (!done) {
      const r = await reader.read();
      if (r.done) break;
      buf += dec.decode(r.value, { stream: true });
      let k;
      while ((k = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, k); buf = buf.slice(k + 2);
        if (!line.startsWith("data:")) continue;
        let ev; try { ev = JSON.parse(line.slice(5)); } catch (e) { continue; }
        if (ev.type === "token") {
          m.content += ev.text;
          const last = m.segs[m.segs.length - 1];
          if (last.t === "text") last.v += ev.text; else m.segs.push({ t: "text", v: ev.text });
        } else if (ev.type === "tool_call") {
          m.segs.push({ t: "tool", id: ev.id, name: ev.name, args: ev.args || {}, status: "running" });
          m.segs.push({ t: "text", v: "" });
        } else if (ev.type === "approval") {
          const s = lastTool(m); if (s) { s.status = "waiting"; s.approval = ev.id; }
        } else if (ev.type === "approval_done") {
          const s = lastTool(m); if (s) { s.status = ev.allow ? "running" : "denied"; s.approval = null; }
        } else if (ev.type === "tool_result") {
          const s = m.segs.find((x) => x.t === "tool" && x.id === ev.id);
          if (s) { s.result = ev.result; s.image = ev.image; if (s.status !== "denied") s.status = "done"; }
          if (["write", "edit", "append", "bash", "python", "download"].includes(ev.name)) changedFiles = true;
        } else if (ev.type === "error") { m.error = ev.error; }
        else if (ev.type === "done") { m.stopped = !!ev.stopped; done = true; }
        paint();
      }
    }
  } catch (e) {
    if (e.name !== "AbortError") m.error = String(e.message || e);
    else m.stopped = true;
  }
  S.stream[scope] = null;
  renderThread(scope, true);
  renderComposer(scope);
  if (scope === "code" && changedFiles) refreshProject();
  if (chat.messages.length) saveChat(chat);
}
function lastTool(m) { for (let i = m.segs.length - 1; i >= 0; i--) if (m.segs[i].t === "tool") return m.segs[i]; return null; }
async function stopStream(scope) {
  const st = S.stream[scope];
  if (!st) return;
  api("/api/chat/stop", { method: "POST", body: { stream_id: st.sid } }).catch(() => {});
  setTimeout(() => { if (S.stream[scope] === st) st.ctrl.abort(); }, 400);
}
async function saveChat(chat) {
  const clean = { ...chat, messages: chat.messages.map((m) => {
    const c = { ...m }; delete c._opened;
    if (c.segs) c.segs = c.segs.map((s) => { const x = { ...s }; delete x.open; return x; });
    return c; }) };
  try {
    const r = await api("/api/chats", { method: "POST", body: { chat: clean } });
    const isNew = !chat.id;
    chat.id = r.id;
    if (isNew && chat === S.chat) history.replaceState(null, "", "#/chat/" + r.id);
    await loadChats();
  } catch (e) { toast("Couldn't save chat: " + e.message, true); }
}
async function loadChats() { try { S.chats = (await api("/api/chats")).chats; } catch (e) { S.chats = []; } renderSide(); }

/* ─────────────────────────── popovers & modals ─────────────────────────── */
function closePop() { $$(".pop").forEach((p) => p.remove()); }
function pop(anchor, html, { width, onMount } = {}) {
  closePop();
  const p = document.createElement("div");
  p.className = "pop";
  if (width) p.style.width = width + "px";
  p.innerHTML = html;
  $("#layer").appendChild(p);
  const r = anchor.getBoundingClientRect(), pr = p.getBoundingClientRect();
  const below = r.bottom + 6 + pr.height < innerHeight;
  p.style.top = (below ? r.bottom + 6 : Math.max(8, r.top - pr.height - 6)) + "px";
  p.style.left = clamp(r.right - pr.width, 8, innerWidth - pr.width - 8) + "px";
  if (r.left + pr.width < innerWidth - 8 && anchor.dataset.align === "left") p.style.left = r.left + "px";
  if (onMount) onMount(p);
  return p;
}
function modal(title, body, foot, { width } = {}) {
  closeModal();
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal" ${width ? `style="width:min(${width}px,100%)"` : ""}><div class="modal-head"><h3>${title}</h3><button class="icon-btn" data-act="close-modal">${icon("x")}</button></div><div class="modal-body">${body}</div>${foot ? `<div class="modal-foot">${foot}</div>` : ""}</div>`;
  back.addEventListener("mousedown", (e) => { if (e.target === back) closeModal(); });
  $("#layer").appendChild(back);
  const f = back.querySelector("input,textarea,select"); if (f) setTimeout(() => f.focus(), 40);
  return back;
}
function closeModal() { $$(".modal-back").forEach((m) => m.remove()); }

function modelMenu(anchor, scope) {
  const ms = models();
  const groups = {};
  for (const m of ms) (groups[m.group || "Other"] = groups[m.group || "Other"] || []).push(m);
  const order = ["Local", ...Object.keys(groups).filter((g) => g !== "Local" && g !== "Built-in"), "Built-in"].filter((g) => groups[g]);
  const item = (m) => `<button class="mi" data-act="pick-model" data-id="${esc(m.id)}" data-scope="${scope}">
      <div class="lbl">${esc(m.name)}${(() => { const sub = m.kind === "api" ? "" : m.kind === "demo" ? "Echoes back — for trying the app" : [m.runtime, m.size, m.arch].filter(Boolean).join(" · "); return sub ? `<span class="sub">${esc(sub)}</span>` : ""; })()}</div>
      ${m.free ? '<span class="badge free">free</span>' : ""}${m.vision ? '<span class="badge">vision</span>' : ""}${m.kind !== "api" && m.kind !== "demo" && !m.ready ? '<span class="badge warn">no runtime</span>' : ""}
      ${m.id === S.model ? `<span class="check">${icon("check", "sm")}</span>` : ""}</button>`;
  const list = (q) => order.map((g) => {
    const items = groups[g].filter((m) => !q || (m.name + " " + g).toLowerCase().includes(q));
    return items.length ? `<div class="grp">${esc(g)}</div>${items.slice(0, q ? 200 : 60).map(item).join("")}` : "";
  }).join("") || `<div class="grp">No models match</div>`;
  const p = pop(anchor, `<div class="search"><input placeholder="Search models" id="mq"></div><div class="scroll" id="ml">${list("")}</div>
    <div class="sep"></div>
    <button class="mi" data-act="go" data-v="settings" data-tab="providers">${icon("cloud", "sm")}<div class="lbl">Add free cloud models</div></button>
    <button class="mi" data-act="go" data-v="code">${icon("download", "sm")}<div class="lbl">Set up a local model</div></button>`, { width: 360 });
  const q = $("#mq", p);
  q.addEventListener("input", () => { $("#ml", p).innerHTML = list(q.value.toLowerCase().trim()); });
  setTimeout(() => q.focus(), 20);
}

function toolsMenu(anchor, scope) {
  const t = S.tools[scope];
  const comp = S.st.computer || {};
  const servers = (S.mcpServers || []).filter((s) => s.enabled !== false);
  const row = (key, ic, lbl, sub, on, disabled) => `<button class="mi ${disabled ? "disabled" : ""}" data-act="${disabled ? "" : "toggle-toolset"}" data-k="${key}" data-scope="${scope}">${icon(ic, "sm")}<div class="lbl">${lbl}<span class="sub">${sub}</span></div><span class="switch ${on ? "on" : ""}"></span></button>`;
  pop(anchor, `
    ${row("code", "terminal", "Files & terminal", scope === "code" ? "Always on in Code" : "Read, write and run commands", scope === "code" || t.code, scope === "code")}
    ${row("web", "globe", "Web browsing", "Open pages and read them", t.web)}
    ${row("computer", "pointer", "Computer use", comp.available ? "See the screen, move the mouse, type" : "Needs setup — see Settings", t.computer, !comp.available)}
    <div class="sep"></div><div class="grp">Connectors</div>
    ${servers.length ? servers.map((s) => `<button class="mi" data-act="toggle-mcp" data-id="${esc(s.id)}" data-scope="${scope}">${icon("plug", "sm")}<div class="lbl">${esc(s.name || s.id)}</div><span class="switch ${(t.mcp || []).includes(s.id) ? "on" : ""}"></span></button>`).join("") : `<div class="mi disabled"><div class="lbl"><span class="sub">No connectors yet</span></div></div>`}
    <div class="sep"></div><button class="mi" data-act="go" data-v="connectors">${icon("plug", "sm")}<div class="lbl">Manage connectors</div></button>`, { width: 320 });
}

function attachMenu(anchor, scope) {
  const comp = S.st.computer || {};
  pop(anchor, `
    <button class="mi" data-act="upload" data-scope="${scope}">${icon("clip", "sm")}<div class="lbl">Upload files<span class="sub">Text, code or images</span></div></button>
    <button class="mi ${comp.available ? "" : "disabled"}" data-act="${comp.available ? "shot" : ""}" data-scope="${scope}">${icon("camera", "sm")}<div class="lbl">Take a screenshot<span class="sub">${comp.available ? "Attach your screen" : "Needs computer-use support"}</span></div></button>
    <button class="mi" data-act="add-url" data-scope="${scope}">${icon("link", "sm")}<div class="lbl">Add a web page<span class="sub">Attach its readable text</span></div></button>`, { width: 290 });
}

/* ─────────────────────────── artifacts panel ─────────────────────────── */
function openArt(key, tab) {
  const a = ART.get(key);
  if (!a) return;
  S.artKey = key;
  const pv = PREVIEW.includes(a.lang);
  tab = pv ? (tab || "preview") : "code";
  const panel = $("#art");
  panel.innerHTML = `<div class="art-head"><div class="t"><b>${esc(a.title)}</b><small>${esc(a.lang)} · ${plural(a.lines, "line")}</small></div>
    ${pv ? `<div class="seg"><button class="${tab === "preview" ? "on" : ""}" data-act="art-tab" data-t="preview">Preview</button><button class="${tab === "code" ? "on" : ""}" data-act="art-tab" data-t="code">Code</button></div>` : ""}
    <button class="icon-btn" data-act="copy-art" data-k="${esc(key)}" title="Copy">${icon("copy")}</button>
    <button class="icon-btn" data-act="dl-art" data-k="${esc(key)}" title="Download">${icon("download")}</button>
    <button class="icon-btn" data-act="close-art" title="Close">${icon("x")}</button></div>
    <div class="art-body" id="art-body"></div>`;
  const body = $("#art-body");
  if (tab === "preview") {
    const f = document.createElement("iframe");
    f.setAttribute("sandbox", "allow-scripts allow-forms allow-modals allow-popups");
    f.srcdoc = a.lang === "svg" || a.lang === "xml"
      ? `<!doctype html><body style="margin:0;display:grid;place-items:center;min-height:100vh;background:#fff">${a.code}</body>` : a.code;
    body.appendChild(f);
  } else {
    body.innerHTML = `<pre>${highlight(a.code, a.lang)}</pre>`;
  }
  panel.classList.add("open");
  document.body.classList.add("with-art");
}
function closeArt() { $("#art").classList.remove("open"); document.body.classList.remove("with-art"); S.artKey = null; }

/* ─────────────────────────── code workspace ─────────────────────────── */
function viewCode(el) {
  if (!S.project) {
    const st = S.st, jobsHtml = coderJobsHTML();
    const recents = (st.recent_projects || []);
    const presets = st.coder_presets || {};
    el.innerHTML = `<div class="page"><div class="page-in">
      <div class="page-head"><h2>Code</h2></div>
      <div class="page-sub">Open a folder and work with CS like a pair programmer — it can read, edit and run code in that project, asking before anything risky.</div>
      <div class="card card-row"><div class="grow"><h4>${icon("folder", "sm")}Open a project folder</h4><div class="muted">CS only reads and writes inside the folder you choose.</div></div>
        <button class="btn primary" data-act="pick-project">${icon("folder", "sm")}Open folder</button></div>
      ${recents.length ? `<div class="section-title">Recent</div>${recents.map((r) => `<div class="card card-row" style="padding:10px 14px;cursor:pointer" data-act="open-project" data-root="${esc(r)}">${icon("folder", "sm")}<div class="grow"><b style="font-weight:500">${esc(r.split(/[\\/]/).filter(Boolean).pop() || r)}</b><div class="kv">${esc(r)}</div></div>${icon("right", "sm")}</div>`).join("")}` : ""}
      <div class="section-title">Local coding model</div>
      <div class="card"><h4>${icon("cpu", "sm")}Run a coding model on this computer ${st.local_server ? '<span class="badge free">runtime ready</span>' : ""}</h4>
        <div class="muted" style="margin-bottom:12px">Free, private and unlimited. Downloads llama.cpp (if needed) and a Qwen2.5-Coder model, then it appears in the model menu.</div>
        <div class="grid2">${Object.entries(presets).map(([k, p]) => `<div class="card" style="margin:0"><h4>${esc(p.label)}</h4><div class="muted">${esc(p.size)} · ${esc(p.hint)}</div>
          <button class="btn secondary sm" style="margin-top:10px" data-act="setup-coder" data-p="${k}">${icon("download", "sm")}Download & set up</button></div>`).join("")}</div>
        ${jobsHtml}</div>
      <div class="card card-row"><div class="grow"><h4>${icon("cloud", "sm")}Or use a free cloud coder</h4><div class="muted">Groq, Mistral (Codestral) and OpenRouter's free Qwen3-Coder work great here.</div></div>
        <button class="btn secondary" data-act="go" data-v="settings" data-tab="providers">Connect</button></div>
    </div></div>`;
    return;
  }
  const P = S.project;
  el.innerHTML = `<div class="code-ws ${P.file ? "" : "no-file"}">
    <div class="tree" id="tree"></div>
    ${P.file ? `<div class="viewer" id="viewer"></div>` : ""}
    <div class="agent"><div class="thread" id="thread-code"><div class="msgs" id="msgs-code"></div></div><div id="composer-code" class="composer-dock"></div></div>
  </div>`;
  renderTree();
  if (P.file) renderViewer();
  if (!S.codeChat.messages.length) {
    $("#msgs-code").innerHTML = `<div class="empty-state" style="padding:40px 10px"><div>${mark()}</div><h3>What are we building?</h3><div>Try “Explain this project”, “Add tests for utils.py” or “Fix the failing build”.</div></div>`;
  } else renderThread("code");
  renderComposer("code");
}
function renderTree() {
  const P = S.project, t = $("#tree");
  if (!t) return;
  const rows = [];
  const walk = (rel, depth) => {
    for (const e of P.tree[rel] || []) {
      const open = P.expanded.has(e.path);
      rows.push(`<div class="tn ${P.file && P.file.path === e.path ? "active" : ""}" style="padding-left:${6 + depth * 14}px" data-act="${e.dir ? "tree-dir" : "tree-file"}" data-p="${esc(e.path)}">
        <span class="caret">${e.dir ? icon(open ? "down" : "right", "sm") : ""}</span>${icon(e.dir ? "folder" : "file", "sm")}<span>${esc(e.name)}</span></div>`);
      if (e.dir && open) walk(e.path, depth + 1);
    }
  };
  walk("", 0);
  t.innerHTML = `<div class="tree-head">${icon("folder", "sm")}<b title="${esc(P.root)}">${esc(P.name)}</b>
    <button class="icon-btn" style="width:26px;height:26px" data-act="refresh-project" title="Refresh">${icon("refresh", "sm")}</button>
    <button class="icon-btn" style="width:26px;height:26px" data-act="close-project" title="Close project">${icon("x", "sm")}</button></div>${rows.join("")}`;
}
function renderViewer() {
  const P = S.project, v = $("#viewer");
  if (!v || !P.file) return;
  const f = P.file;
  const ext = (f.path.split(".").pop() || "").toLowerCase();
  const head = `<div class="viewer-head"><span class="path">${esc(f.path)}${f.dirty ? " •" : ""}</span>
    ${f.editing ? `<button class="btn ghost sm" data-act="edit-cancel">Cancel</button><button class="btn primary sm" data-act="edit-save">${icon("save", "sm")}Save</button>`
      : `<button class="btn ghost sm" data-act="ask-file">${icon("chat", "sm")}Ask</button><button class="btn ghost sm" data-act="edit-file" ${f.binary ? "disabled" : ""}>${icon("pen", "sm")}Edit</button>`}
    <button class="icon-btn" style="width:28px;height:28px" data-act="close-file">${icon("x", "sm")}</button></div>`;
  let body;
  if (f.binary) body = `<div class="empty-state">${f.too_big ? "This file is too large to display." : "Binary file — no preview."}</div>`;
  else if (f.editing) body = `<textarea class="editor" id="editor" spellcheck="false"></textarea>`;
  else {
    const lines = f.content.split("\n");
    body = `<div class="lines"><div class="ln">${lines.map((_, i) => i + 1).join("<br>")}</div><pre>${highlight(f.content, ext)}</pre></div>`;
  }
  v.innerHTML = head + `<div class="viewer-body">${body}</div>`;
  if (f.editing) { const ed = $("#editor"); ed.value = f.content; ed.addEventListener("input", () => { f.dirty = true; }); ed.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); saveFile(); } if (e.key === "Tab") { e.preventDefault(); const s = ed.selectionStart; ed.setRangeText("    ", s, ed.selectionEnd, "end"); } }); ed.focus(); }
}
async function openProject(root) {
  try {
    const r = await api("/api/project/open", { method: "POST", body: { root } });
    S.project = { root: r.root, name: r.root.split(/[\\/]/).filter(Boolean).pop() || r.root, tree: { "": r.entries }, expanded: new Set(), file: null };
    S.codeChat = newChatObj("code"); S.codeChat.project = r.root; S.codeChat.title = "Code · " + S.project.name;
    S.st.recent_projects = [r.root, ...(S.st.recent_projects || []).filter((x) => x !== r.root)].slice(0, 8);
    go("code"); renderView(); renderTop();
  } catch (e) { toast(e.message, true); }
}
async function refreshProject() {
  const P = S.project; if (!P) return;
  try {
    const keys = ["", ...P.expanded];
    for (const k of keys) P.tree[k] = (await api(`/api/fs/list?root=${encodeURIComponent(P.root)}&path=${encodeURIComponent(k)}`)).entries;
    if (P.file && !P.file.editing) { const r = await api(`/api/fs/read?root=${encodeURIComponent(P.root)}&path=${encodeURIComponent(P.file.path)}`); Object.assign(P.file, r); }
  } catch (e) {}
  renderTree(); renderViewer();
}
async function openFile(path) {
  const P = S.project;
  try {
    const r = await api(`/api/fs/read?root=${encodeURIComponent(P.root)}&path=${encodeURIComponent(path)}`);
    const had = !!P.file;
    P.file = { path, ...r, editing: false, dirty: false };
    if (!had) renderView(); else { renderTree(); renderViewer(); }
  } catch (e) { toast(e.message, true); }
}
async function saveFile() {
  const P = S.project, ed = $("#editor");
  if (!P || !P.file || !ed) return;
  try {
    await api("/api/fs/write", { method: "POST", body: { root: P.root, path: P.file.path, content: ed.value } });
    P.file.content = ed.value; P.file.editing = false; P.file.dirty = false; renderViewer(); toast("Saved");
  } catch (e) { toast(e.message, true); }
}
function folderPicker(onPick, start) {
  let cur = start || "";
  const draw = async () => {
    let d; try { d = await api("/api/fs/dirs?path=" + encodeURIComponent(cur)); } catch (e) { toast(e.message, true); return; }
    cur = d.path;
    const back = modal("Choose a folder",
      `<div class="row" style="margin-bottom:8px"><input class="input mono" id="fp-in" value="${esc(d.path)}" placeholder="Paste a folder path"><button class="btn secondary" data-act="fp-go">Go</button></div>
       <div class="fp-list">${d.parent ? `<button class="mi" data-act="fp-nav" data-p="${esc(d.parent)}">${icon("left", "sm")}<div class="lbl">..</div></button>` : ""}
       ${d.dirs.map((x) => `<button class="mi" data-act="fp-nav" data-p="${esc(x.path)}">${icon("folder", "sm")}<div class="lbl">${esc(x.name)}</div>${icon("right", "sm")}</button>`).join("") || `<div class="mi disabled"><div class="lbl"><span class="sub">No sub-folders</span></div></div>`}</div>`,
      `<button class="btn ghost" data-act="close-modal">Cancel</button><button class="btn primary" data-act="fp-pick" ${d.path ? "" : "disabled"}>Open this folder</button>`, { width: 600 });
    back.fpNav = (p) => { cur = p; draw(); };
    back.fpPick = () => { closeModal(); onPick(cur); };
    back.fpGo = () => { cur = $("#fp-in").value.trim(); draw(); };
    $("#fp-in").addEventListener("keydown", (e) => { if (e.key === "Enter") back.fpGo(); });
  };
  draw();
}
function jobsFor(filter) {
  const re = filter ? new RegExp(filter, "i") : null;
  return Object.values(S.jobs).filter((j) => !re || re.test(j.title)).map(jobHTML).join("");
}
function coderJobsHTML() { return `<div id="jobs-box" data-filter="coder|Download|Install">${jobsFor("coder|Download|Install")}</div>`; }
function jobHTML(j) {
  const pct = j.bytes && j.expect ? clamp(j.bytes / j.expect * 100, 0, 99) : null;
  return `<div class="card" style="margin:12px 0 0"><h4>${j.status === "running" ? '<div class="spin"></div>' : j.status === "done" ? '<span class="dot-ok"></span>' : '<span class="dot-bad"></span>'}${esc(j.title)}</h4>
    <div class="muted">${j.status === "running" ? `Step ${j.step} of ${j.steps}${j.bytes ? ` · ${(j.bytes / 1e9).toFixed(2)} GB` : ""}` : j.status === "done" ? "Finished — the model is in the model menu." : esc(j.error || "Failed")}</div>
    ${j.status === "running" ? `<div class="bar ${pct === null ? "indet" : ""}"><i style="${pct !== null ? `width:${pct}%` : ""}"></i></div>` : ""}
    ${j.log && j.log.length ? `<div class="out">${esc(j.log.slice(-6).join("\n"))}</div>` : ""}</div>`;
}
async function startJob(path, body) {
  try {
    const j = await api(path, { method: "POST", body });
    S.jobs[j.id] = j; toast("Started: " + j.title); pollJobs(); renderTop(); renderView();
  } catch (e) { toast(e.message, true); }
}
let jobTimer = null;
function pollJobs() {
  if (jobTimer) return;
  jobTimer = setInterval(async () => {
    const running = Object.values(S.jobs).filter((j) => j.status === "running");
    if (!running.length) { clearInterval(jobTimer); jobTimer = null; return; }
    for (const j of running) {
      try {
        const n = await api("/api/jobs/" + j.id);
        S.jobs[j.id] = { ...j, ...n };
        if (n.status !== "running") {
          toast(n.status === "done" ? `Done: ${n.title}` : `Failed: ${n.title}`, n.status !== "done");
          await refreshState();
        }
      } catch (e) {}
    }
    renderTop();
    const jb = $("#jobs-box");
    if (jb) jb.innerHTML = jobsFor(jb.dataset.filter);
  }, 1200);
}

/* ─────────────────────────── browser ─────────────────────────── */
const QUICK = [["Wikipedia", "en.wikipedia.org", "The free encyclopedia"], ["Hacker News", "news.ycombinator.com", "Tech news"],
  ["GitHub", "github.com/trending", "Trending repositories"], ["MDN", "developer.mozilla.org", "Web docs"],
  ["Python docs", "docs.python.org/3/", "Language reference"], ["arXiv", "arxiv.org", "Research papers"]];
function toUrl(input) {
  input = input.trim();
  if (/^[a-z][\w+.-]*:\/\//i.test(input)) return input;
  if (/^(localhost|[\w-]+(\.[\w-]+)+)(:\d+)?(\/.*)?$/i.test(input)) return "https://" + input;
  return "https://duckduckgo.com/html/?q=" + encodeURIComponent(input);
}
function viewBrowser(el) {
  const B = S.browser;
  el.innerHTML = `<div class="browser">
    <div class="bbar">
      <button class="icon-btn" data-act="b-back" ${B.idx > 0 ? "" : "disabled"} title="Back">${icon("left")}</button>
      <button class="icon-btn" data-act="b-fwd" ${B.idx < B.hist.length - 1 ? "" : "disabled"} title="Forward">${icon("right")}</button>
      <button class="icon-btn" data-act="b-reload" title="Reload">${icon("refresh")}</button>
      <div class="url">${icon("search", "sm")}<input id="b-url" value="${esc(B.url)}" placeholder="Search or enter an address" spellcheck="false"></div>
      <button class="icon-btn ${B.reader ? "active" : ""}" data-act="b-reader" title="Reader view" ${B.url ? "" : "disabled"}>${icon("book")}</button>
      <button class="btn secondary sm" data-act="b-ask" ${B.url ? "" : "disabled"}>${icon("chat", "sm")}Ask CS about this page</button>
      <button class="icon-btn" data-act="b-ext" title="Open in your browser" ${B.url ? "" : "disabled"}>${icon("ext")}</button>
    </div>
    <div class="bframe" id="bframe"></div></div>`;
  const inp = $("#b-url");
  inp.addEventListener("keydown", (e) => { if (e.key === "Enter") bNav(inp.value); });
  inp.addEventListener("focus", () => inp.select());
  drawFrame();
}
async function drawFrame() {
  const B = S.browser, f = $("#bframe");
  if (!f) return;
  if (!B.url) {
    f.innerHTML = `<div class="start"><h1>Where to?</h1><div class="url">${icon("search", "sm")}<input id="b-start" placeholder="Search the web or type an address"></div>
      <div class="quick">${QUICK.map(([n, u, d]) => `<button data-act="b-go" data-u="${esc(u)}"><b>${esc(n)}</b><small>${esc(d)}</small></button>`).join("")}</div></div>`;
    const s = $("#b-start"); s.addEventListener("keydown", (e) => { if (e.key === "Enter") bNav(s.value); }); setTimeout(() => s.focus(), 40);
    return;
  }
  if (B.reader) {
    f.innerHTML = `<div class="reader"><div class="empty-state"><div class="spin" style="margin:0 auto"></div></div></div>`;
    try {
      const r = await api("/api/reader?url=" + encodeURIComponent(B.url));
      f.innerHTML = `<div class="reader"><article><h1>${esc(r.title || r.url)}</h1><div class="kv" style="margin-bottom:24px">${esc(r.url)}</div>${esc(r.text)}</article></div>`;
    } catch (e) { f.innerHTML = `<div class="empty-state">Couldn't load reader view: ${esc(e.message)}</div>`; }
    return;
  }
  f.innerHTML = `<iframe sandbox="allow-scripts allow-forms allow-popups" referrerpolicy="no-referrer" src="/api/browse?bt=${encodeURIComponent(BT)}&url=${encodeURIComponent(B.url)}"></iframe>`;
}
function bNav(input, push = true) {
  if (!input || !input.trim()) return;
  const B = S.browser, url = toUrl(input);
  if (push) { B.hist = B.hist.slice(0, B.idx + 1); B.hist.push(url); B.idx = B.hist.length - 1; }
  B.url = url; B.title = "";
  if (S.view !== "browser") go("browser"); else { const v = $("#view-browser"); viewBrowser(v); renderTop(); }
}
window.addEventListener("message", (e) => {
  const d = e.data;
  if (!d || typeof d !== "object" || !d.cs) return;
  if (d.cs === "nav" && typeof d.url === "string" && /^https?:/i.test(d.url)) bNav(d.url);
  else if (d.cs === "loaded" && S.view === "browser") {
    S.browser.title = String(d.title || "").slice(0, 120);
    const i = $("#b-url"); if (i && typeof d.url === "string" && /^https?:/i.test(d.url) && document.activeElement !== i) i.value = d.url;
    renderTop();
  }
});

/* ─────────────────────────── artifacts gallery ─────────────────────────── */
async function viewArtifacts(el) {
  el.innerHTML = `<div class="page"><div class="page-in"><div class="page-head"><h2>Artifacts</h2></div>
    <div class="page-sub">Everything CS has made for you — pages, graphics and programs from your chats.</div><div id="arts"><div class="spin"></div></div></div></div>`;
  let arts = [];
  try { arts = (await api("/api/artifacts")).artifacts; } catch (e) {}
  const box = $("#arts"); if (!box) return;
  if (!arts.length) { box.innerHTML = `<div class="empty-state">${mark()}<h3>No artifacts yet</h3><div>Ask CS for a web page, an SVG or a script and it will show up here.</div></div>`; return; }
  box.innerHTML = `<div class="art-grid">${arts.map((a, i) => {
    const key = "gallery:" + a.key; ART.set(key, { lang: a.lang, code: a.code, title: a.title, lines: a.lines });
    const thumb = PREVIEW.includes(a.lang)
      ? `<iframe sandbox="" loading="lazy" srcdoc="${esc(a.lang === "svg" ? `<body style='margin:0;display:grid;place-items:center;height:100vh;background:#fff'>${a.code}</body>` : a.code)}"></iframe>`
      : `<pre>${esc(a.code.split("\n").slice(0, 10).join("\n"))}</pre>`;
    return `<div class="art-tile" data-act="open-art" data-k="${esc(key)}"><div class="thumb">${thumb}</div><div class="meta"><b>${esc(a.title)}</b><small>${esc(a.lang)} · from “${esc(a.chat_title)}”</small></div></div>`;
  }).join("")}</div>`;
}

/* ─────────────────────────── routines ─────────────────────────── */
async function viewRoutines(el) {
  el.innerHTML = `<div class="page"><div class="page-in"><div class="page-head"><h2>Routines</h2><button class="btn primary" data-act="new-routine">${icon("plus", "sm")}New routine</button></div>
    <div class="page-sub">Prompts that run on a schedule while CS Studio is open. Results are kept here.</div><div id="rl"><div class="spin"></div></div></div></div>`;
  let rs = [];
  try { rs = (await api("/api/routines")).routines; } catch (e) {}
  S.routines = rs;
  const box = $("#rl"); if (!box) return;
  if (!rs.length) { box.innerHTML = `<div class="empty-state">${mark()}<h3>No routines yet</h3><div>For example: “Every morning at 9, summarize my priorities.”</div></div>`; return; }
  box.innerHTML = rs.map((r) => `<div class="card">
    <div class="card-row"><div class="grow"><h4>${esc(r.name || "Routine")}</h4>
      <div class="muted">${esc(sched(r))} · ${esc(modelLabel(r.model))}${r.last_run ? " · last ran " + esc(ago(r.last_run)) : ""}</div></div>
      <span class="switch ${r.enabled !== false ? "on" : ""}" data-act="toggle-routine" data-id="${esc(r.id)}" role="switch"></span></div>
    <div class="out">${esc(r.prompt || "")}</div>
    ${r.last_output ? `<div class="section-title" style="margin:14px 0 4px">Latest result</div><div class="prose" style="font-size:15px">${md(r.last_output, "rt:" + r.id, false)}</div>` : ""}
    <div class="row" style="margin-top:12px"><button class="btn secondary sm" data-act="run-routine" data-id="${esc(r.id)}">${icon("play", "sm")}Run now</button>
      <button class="btn ghost sm" data-act="edit-routine" data-id="${esc(r.id)}">${icon("pen", "sm")}Edit</button>
      <button class="btn ghost sm" data-act="del-routine" data-id="${esc(r.id)}">${icon("trash", "sm")}Delete</button></div></div>`).join("");
}
function sched(r) { return r.every_minutes ? `Every ${r.every_minutes} min` : r.at_time ? `Daily at ${r.at_time}` : "Manual"; }
function ago(ts) {
  const s = (Date.now() / 1000) - ts;
  if (s < 60) return "just now"; if (s < 3600) return Math.floor(s / 60) + "m ago"; if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return new Date(ts * 1000).toLocaleDateString();
}
function routineModal(r) {
  r = r || { name: "", prompt: "", model: S.model, enabled: true, at_time: "09:00" };
  const daily = !r.every_minutes;
  const back = modal(r.id ? "Edit routine" : "New routine", `
    <div class="field"><label>Name</label><input class="input" id="r-name" value="${esc(r.name)}" placeholder="Morning briefing"></div>
    <div class="field"><label>What should CS do?</label><textarea class="textarea" id="r-prompt" placeholder="Give me three priorities for today…">${esc(r.prompt)}</textarea></div>
    <div class="field"><label>Model</label><select class="select" id="r-model">${models().map((m) => `<option value="${esc(m.id)}" ${m.id === r.model ? "selected" : ""}>${esc(m.group)} · ${esc(m.name)}</option>`).join("")}</select></div>
    <div class="field"><label>Schedule</label><div class="row"><div class="seg"><button class="${daily ? "on" : ""}" data-act="r-mode" data-m="daily">Daily</button><button class="${daily ? "" : "on"}" data-act="r-mode" data-m="every">Interval</button></div>
      <input class="input" id="r-at" style="width:120px;${daily ? "" : "display:none"}" value="${esc(r.at_time || "09:00")}" placeholder="09:00">
      <input class="input" id="r-every" type="number" min="1" style="width:120px;${daily ? "display:none" : ""}" value="${esc(r.every_minutes || 60)}"><span class="muted" id="r-unit" style="${daily ? "display:none" : ""}">minutes</span></div></div>`,
    `<button class="btn ghost" data-act="close-modal">Cancel</button><button class="btn primary" data-act="save-routine">Save routine</button>`);
  back.routine = r; back.daily = daily;
}

/* ─────────────────────────── connectors (MCP) ─────────────────────────── */
async function loadMcp() { try { S.mcpServers = (await api("/api/mcp")).servers || []; } catch (e) { S.mcpServers = []; } }
async function viewConnectors(el) {
  await loadMcp();
  const servers = S.mcpServers, gal = (S.st.mcp_gallery || []).filter((g) => !servers.some((s) => s.id === g.id));
  el.innerHTML = `<div class="page"><div class="page-in">
    <div class="page-head"><h2>Connectors</h2><button class="btn secondary" data-act="mcp-import">${icon("download", "sm")}Import from Claude Desktop</button><button class="btn primary" data-act="mcp-add">${icon("plus", "sm")}Add custom</button></div>
    <div class="page-sub">Connect Model Context Protocol servers to give models new tools. Most need Node.js (<code>npx</code>) or uv (<code>uvx</code>) installed.</div>
    ${servers.length ? `<div class="section-title">Your connectors</div>${servers.map((s) => `<div class="card">
      <div class="card-row">${icon("plug")}<div class="grow"><h4>${esc(s.name || s.id)}</h4><div class="kv">${esc([s.command, ...(s.args || [])].join(" "))}</div></div>
        <span class="switch ${s.enabled !== false ? "on" : ""}" data-act="mcp-toggle" data-id="${esc(s.id)}"></span></div>
      <div id="mt-${esc(s.id)}"></div>
      <div class="row" style="margin-top:10px"><button class="btn secondary sm" data-act="mcp-tools" data-id="${esc(s.id)}">${icon("wrench", "sm")}Show tools</button>
      <button class="btn ghost sm" data-act="mcp-del" data-id="${esc(s.id)}">${icon("trash", "sm")}Remove</button></div></div>`).join("")}` : ""}
    ${gal.length ? `<div class="section-title">Suggested</div><div class="grid2">${gal.map((g) => `<div class="card" style="margin:0"><h4>${esc(g.name)}</h4><div class="muted" style="min-height:38px">${esc(g.desc)}</div>
      <button class="btn secondary sm" style="margin-top:10px" data-act="mcp-gallery" data-id="${esc(g.id)}">${icon("plus", "sm")}Add</button></div>`).join("")}</div>` : ""}
  </div></div>`;
}

/* ─────────────────────────── settings ─────────────────────────── */
const TABS = [["general", "palette", "General"], ["providers", "cloud", "Providers"], ["models", "box", "Models"],
  ["context", "sliders", "Model context"], ["computer", "pointer", "Computer use"], ["about", "info", "About"]];
const ACCENTS = [["#c9794f", "Clay"], ["#b8956a", "Sand"], ["#7f9c7d", "Sage"], ["#7d8ca8", "Slate"], ["#b07c89", "Rose"]];
function viewSettings(el) {
  el.innerHTML = `<div class="page"><div class="settings"><nav class="settings-nav">${TABS.map(([k, ic, l]) => `<button class="nav-item ${S.settingsTab === k ? "active" : ""}" data-act="stab" data-t="${k}">${icon(ic)}<span>${l}</span></button>`).join("")}</nav><div id="stab"></div></div></div>`;
  ({ general: tabGeneral, providers: tabProviders, models: tabModels, context: tabContext, computer: tabComputer, about: tabAbout }[S.settingsTab] || tabGeneral)($("#stab"));
}
function tabGeneral(el) {
  const p = S.st.prefs || {};
  const theme = LS.get("theme_raw", "dark");
  el.innerHTML = `<div class="page-head"><h2>General</h2></div>
    <div class="card"><div class="field"><label>Theme</label><div class="seg">${["dark", "light", "system"].map((t) => `<button class="${theme === t ? "on" : ""}" data-act="set-theme" data-t="${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}</div></div>
      <div class="field"><label>Accent</label><div class="swatches">${ACCENTS.map(([c, n]) => `<button class="swatch ${cssVar("--accent") === c ? "on" : ""}" style="background:${c}" title="${n}" data-act="set-accent" data-c="${c}"></button>`).join("")}</div></div>
      <div class="field" style="margin:0"><label>Response font</label><div class="seg">${[["serif", "Serif"], ["sans", "Sans"]].map(([k, l]) => `<button class="${(LS.get("font", "serif")) === k ? "on" : ""}" data-act="set-font" data-f="${k}">${l}</button>`).join("")}</div></div></div>
    <div class="section-title">Permissions</div>
    <div class="card"><div class="card-row"><div class="grow"><h4>${icon("shield", "sm")}Tool approvals</h4><div class="muted">When a model wants to run commands, change files, use connectors or control the computer.</div></div>
      <div class="seg">${[["ask", "Ask first"], ["auto", "Allow all"]].map(([k, l]) => `<button class="${(p.tool_approval || "ask") === k ? "on" : ""}" data-act="set-approval" data-v="${k}">${l}</button>`).join("")}</div></div>
      ${(p.tool_approval || "ask") === "auto" ? `<div class="err" style="margin:12px 0 0">Tools run without asking. Only use this with models you trust.</div>` : ""}</div>
    <div class="section-title">Artifacts</div>
    <div class="card card-row"><div class="grow"><h4>${icon("layers", "sm")}Encourage artifacts</h4><div class="muted">Ask models to deliver pages, graphics and programs as openable artifacts.</div></div>
      <span class="switch ${p.artifacts !== false ? "on" : ""}" data-act="toggle-pref" data-k="artifacts"></span></div>`;
}
function cssVar(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
function tabProviders(el) {
  const ps = S.st.providers || [];
  const card = (p) => {
    const badges = `${p.free ? '<span class="badge free">free</span>' : ""}${p.local ? '<span class="badge">local</span>' : ""}${p.no_key && !p.local ? '<span class="badge acc">no signup</span>' : ""}`;
    let right;
    if (p.connected) right = `<span class="badge free">connected · ${p.models.length} model${p.models.length === 1 ? "" : "s"}</span>
        <button class="btn ghost sm" data-act="prov-refresh" data-id="${esc(p.id)}">${icon("refresh", "sm")}</button>
        <button class="btn ghost sm" data-act="prov-off" data-id="${esc(p.id)}">Disconnect</button>`;
    else if (p.local) right = `<span class="muted">Not running</span><a class="btn ghost sm" href="${esc(p.key_url)}" target="_blank" rel="noopener">Get ${esc(p.name)} ${icon("ext", "sm")}</a><button class="btn secondary sm" data-act="prov-check">Check again</button>`;
    else if (p.no_key) right = `<button class="btn secondary sm" data-act="prov-connect" data-id="${esc(p.id)}">Enable</button>`;
    else right = `<a class="btn ghost sm" href="${esc(p.key_url)}" target="_blank" rel="noopener">Get key ${icon("ext", "sm")}</a>
        <input class="input" style="width:190px" type="password" id="k-${esc(p.id)}" placeholder="Paste API key" autocomplete="off">
        <button class="btn primary sm" data-act="prov-connect" data-id="${esc(p.id)}">Connect</button>`;
    return `<div class="card"><div class="card-row"><div class="grow"><h4>${esc(p.name)} ${badges}</h4><div class="muted">${esc(p.note || "")}</div>${p.error ? `<div class="muted" style="color:var(--warn)">${esc(p.error)}</div>` : ""}</div>
      <div class="row">${right}</div></div></div>`;
  };
  const cloud = ps.filter((p) => !p.local && !p.custom);
  const free = cloud.filter((p) => p.free), paid = cloud.filter((p) => !p.free), local = ps.filter((p) => p.local), custom = ps.filter((p) => p.custom);
  el.innerHTML = `<div class="page-head"><h2>Providers</h2></div>
    <div class="page-sub">Use cloud models alongside local ones. Keys stay on this computer, in your CS data folder.</div>
    <div class="card"><h4>${icon("bolt", "sm")}Free models in about a minute</h4><div class="muted">Groq, Google Gemini and OpenRouter all offer free tiers. Click <b>Get key</b>, sign in, create a key and paste it here — every model on that account appears in the model menu.</div></div>
    <div class="section-title">Free tiers</div>${free.map(card).join("")}
    <div class="section-title">On this computer</div>${local.map(card).join("")}
    <div class="section-title">Paid</div>${paid.map(card).join("")}
    ${custom.length ? `<div class="section-title">Custom</div>${custom.map(card).join("")}` : ""}
    <div class="section-title">Custom OpenAI-compatible endpoint</div>
    <div class="card"><div class="row" style="flex-wrap:wrap"><input class="input" id="c-name" style="width:150px" placeholder="Name"><input class="input" id="c-url" style="flex:1;min-width:220px" placeholder="https://host/v1">
      <input class="input" id="c-key" style="width:180px" type="password" placeholder="API key (optional)"><button class="btn primary" data-act="prov-custom">Connect</button></div>
      <div class="muted" style="margin-top:8px">vLLM, llama.cpp server, text-generation-webui, LiteLLM and most gateways work here.</div></div>`;
}
function tabModels(el) {
  const loc = models().filter((m) => m.local && m.kind !== "demo");
  const rts = S.st.runtimes || [];
  const frozen = S.st.frozen;
  const inst = [["llamacpp-bin", "llama.cpp", "Fast GGUF inference, no Python needed"], ["llama-cpp", "llama-cpp-python", "In-process GGUF runtime"],
    ["transformers", "Transformers", "Safetensors / Hugging Face models"], ["onnx", "ONNX Runtime", "ONNX models"]];
  el.innerHTML = `<div class="page-head"><h2>Models</h2><button class="btn secondary" data-act="rescan">${icon("refresh", "sm")}Rescan</button></div>
    <div class="section-title">On this computer</div>
    ${loc.length ? loc.map((m) => `<div class="card card-row" style="padding:12px 16px">${icon("box")}<div class="grow"><h4>${esc(m.name)}</h4><div class="muted">${esc([m.size, m.arch, m.kind].filter(Boolean).join(" · "))}</div></div>
      ${m.ready ? `<span class="badge free">${esc(m.runtime)}</span>` : '<span class="badge warn">needs a runtime</span>'}</div>`).join("")
      : `<div class="card muted">No local models found yet. Download one below, drop <code>.gguf</code> files into your CS data <code>models</code> folder, or use the one-click coder in Code.</div>`}
    <div class="section-title">Download from Hugging Face</div>
    <div class="card"><div class="row" style="flex-wrap:wrap"><input class="input mono" id="hf-repo" style="flex:1;min-width:240px" placeholder="owner/repo  e.g. bartowski/Qwen2.5-7B-Instruct-GGUF">
      <input class="input mono" id="hf-only" style="width:190px" placeholder="*Q4_K_M.gguf"><button class="btn primary" data-act="hf-pull">${icon("download", "sm")}Download</button></div>
      <div class="muted" style="margin-top:8px">Tip: for GGUF repos, pick one quantization with a pattern like <code>*Q4_K_M.gguf</code>.</div></div>
    <div class="section-title">Runtimes</div>
    <div class="card">${rts.map((r) => `<div class="card-row" style="padding:6px 0">${r.ok ? '<span class="dot-ok"></span>' : '<span class="dot-bad"></span>'}<div class="grow"><b style="font-weight:500">${esc(r.id)}</b> <span class="muted">${esc(r.ok ? "ready" : r.detail)}</span></div></div>`).join("")}</div>
    <div class="grid2" style="margin-top:12px">${inst.map(([t, n, d]) => `<div class="card" style="margin:0"><h4>${esc(n)}</h4><div class="muted" style="min-height:38px">${esc(d)}${frozen && t !== "llamacpp-bin" ? " · needs Python installed" : ""}</div>
      <button class="btn secondary sm" style="margin-top:10px" data-act="install" data-t="${t}">${icon("download", "sm")}Install</button></div>`).join("")}</div>
    <div id="jobs-box" data-filter="">${jobsFor("")}</div>`;
}
async function tabContext(el) {
  const ms = models().filter((m) => m.kind !== "demo");
  if (!ms.length) { el.innerHTML = `<div class="page-head"><h2>Model context</h2></div><div class="card muted">Add a model first.</div>`; return; }
  const sel = S.ctxModel && ms.find((m) => m.id === S.ctxModel) ? S.ctxModel : (ms.find((m) => m.id === S.model) || ms[0]).id;
  S.ctxModel = sel;
  el.innerHTML = `<div class="page-head"><h2>Model context</h2></div><div class="page-sub">Per-model system prompt and sampling settings.</div>
    <div class="card"><div class="field"><label>Model</label><select class="select" id="ctx-m">${ms.map((m) => `<option value="${esc(m.id)}" ${m.id === sel ? "selected" : ""}>${esc(m.group)} · ${esc(m.name)}</option>`).join("")}</select></div><div id="ctx-f"><div class="spin"></div></div></div>`;
  $("#ctx-m").addEventListener("change", (e) => { S.ctxModel = e.target.value; tabContext(el); });
  try {
    const c = (await api("/api/context?model=" + encodeURIComponent(sel))).context;
    const num = (k, l, step, help) => `<div class="field"><label>${l}</label><input class="input" id="c-${k}" type="number" step="${step}" value="${esc(c[k] ?? "")}"><div class="help">${help}</div></div>`;
    $("#ctx-f").innerHTML = `<div class="field"><label>System prompt</label><textarea class="textarea" id="c-system">${esc(c.system || "")}</textarea></div>
      <div class="grid2">${num("temperature", "Temperature", "0.05", "Higher is more creative")}${num("top_p", "Top-p", "0.05", "Nucleus sampling")}
      ${num("max_new_tokens", "Max response tokens", "1", "Longest reply length")}${num("n_ctx", "Context window", "1", "Local models only")}
      ${num("n_gpu_layers", "GPU layers", "1", "-1 = all on GPU (local)")}${num("repeat_penalty", "Repeat penalty", "0.05", "Local models only")}</div>
      <button class="btn primary" data-act="save-ctx">Save</button>`;
  } catch (e) { $("#ctx-f").innerHTML = `<div class="muted">${esc(e.message)}</div>`; }
}
function tabComputer(el) {
  const c = S.st.computer || {};
  el.innerHTML = `<div class="page-head"><h2>Computer use</h2></div>
    <div class="page-sub">Let a model see your screen and use the mouse and keyboard to get things done. Every action asks for your approval unless you allow all tools.</div>
    <div class="card"><div class="card-row"><div class="grow"><h4>${c.available ? '<span class="dot-ok"></span>Ready' : '<span class="dot-bad"></span>Not set up'}</h4>
      <div class="muted">${c.available ? "Turn on Computer use from the tools menu in any chat." : c.frozen ? "This build doesn't include the screen-control libraries." : `Missing: ${esc((c.missing || []).join(", "))}`}</div></div>
      ${!c.available && !c.frozen ? `<button class="btn primary" data-act="install" data-t="computer">${icon("download", "sm")}Install support</button>` : ""}</div></div>
    <div class="card"><h4>${icon("camera", "sm")}Screenshots</h4><div class="muted">Vision-capable cloud models (Gemini, GPT-4o/4.1, Llama 4, Pixtral…) receive screenshots directly; other models get the file path${c.ocr ? " and OCR text" : ""}.</div>
      ${c.available ? `<button class="btn secondary sm" style="margin-top:10px" data-act="test-shot">Take a test screenshot</button><div id="shot-out"></div>` : ""}</div>
    <div id="jobs-box" data-filter="computer">${jobsFor("computer")}</div>`;
}
function tabAbout(el) {
  el.innerHTML = `<div class="page-head"><h2>About</h2></div>
    <div class="card" style="display:flex;gap:22px;align-items:center"><img src="/static/icon.png" width="96" height="96" alt="">
      <div><h4 style="font-family:var(--serif);font-weight:400;font-size:24px">CS Framework</h4>
      <div class="muted">Version ${esc(S.st.version)} · ${esc(S.st.codename)}${S.st.frozen ? " · packaged app" : ""}</div>
      <div class="muted" style="margin-top:6px">Local models, free cloud providers, artifacts, code, browser, connectors and routines — in one app that runs on your machine.</div>
      <div class="row" style="margin-top:12px"><a class="btn secondary sm" href="https://github.com/qulyttvv-beep/cs-framework-v4" target="_blank" rel="noopener">GitHub ${icon("ext", "sm")}</a></div></div></div>
    <div class="section-title">Keyboard</div>
    <div class="card">${[["New chat", "Ctrl/⌘ Shift O"], ["Toggle sidebar", "Ctrl/⌘ B"], ["Settings", "Ctrl/⌘ ,"], ["Send", "Enter"], ["New line", "Shift Enter"], ["Close panel", "Esc"]]
      .map(([a, k]) => `<div class="card-row" style="padding:5px 0"><div class="grow">${a}</div><span class="badge">${k}</span></div>`).join("")}</div>`;
}

/* ─────────────────────────── actions ─────────────────────────── */
const ACT = {
  "go": (el) => { closePop(); closeModal(); if (el.dataset.tab) S.settingsTab = el.dataset.tab; go(el.dataset.v, el.dataset.v === "settings" ? S.settingsTab : undefined); },
  "new-chat": () => { closeArt(); S.chat = newChatObj("chat"); S.chipOpen = null; go("chat"); history.replaceState(null, "", "#/chat"); route(); },
  "toggle-side": () => { $("#app").classList.toggle("side-hidden"); LS.set("side", $("#app").classList.contains("side-hidden")); renderTop(); },
  "open-chat": (el, e) => { if (e.target.closest(".del")) return; closeArt(); go("chat", el.dataset.id); },
  "del-chat": async (el) => { await api("/api/chats/delete", { method: "POST", body: { id: el.dataset.id } }); if (S.chat.id === el.dataset.id) { S.chat = newChatObj("chat"); go("chat"); } loadChats(); },
  "rename": (el) => {
    const inp = document.createElement("input"); inp.className = "title-input"; inp.value = S.chat.title || "";
    el.replaceWith(inp); inp.focus(); inp.select();
    const done = (save) => { if (save && inp.value.trim()) { S.chat.title = inp.value.trim().slice(0, 80); saveChat(S.chat); } renderTop(); };
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") done(true); if (e.key === "Escape") done(false); });
    inp.addEventListener("blur", () => done(true));
  },
  "chip": (el) => {
    const c = CHIPS[+el.dataset.i];
    S.chipOpen = S.chipOpen === +el.dataset.i ? null : +el.dataset.i;
    const ta = $("#ta-chat"); S.draft = { chat: ta ? ta.value : "" };
    viewChat($("#view-chat")); if (c) focusComposer("chat");
  },
  "suggest": (el) => {
    const c = CHIPS[+el.dataset.i], s = c.s[+el.dataset.j];
    if (c.routine) { const every = /hour/i.test(s); routineModal({ name: s.split(",")[0], prompt: s.replace(/^[^,]+,\s*/, ""), model: S.model, enabled: true, ...(every ? { every_minutes: 60 } : { at_time: "09:00" }) }); return; }
    if (c.tools) { S.tools.chat[c.tools] = true; LS.set("tools", S.tools); }
    S.chipOpen = null; send("chat", s);
  },
  "send": (el) => send(el.dataset.scope),
  "stop": (el) => stopStream(el.dataset.scope),
  "retry": (el) => {
    const sc = el.dataset.scope, chat = chatFor(sc);
    if (S.stream[sc]) return;
    if (chat.messages.length && chat.messages[chat.messages.length - 1].role === "assistant") chat.messages.pop();
    runStream(sc);
  },
  "copy-msg": (el) => { const m = chatFor(el.dataset.scope).messages[+el.dataset.i]; copy(cleanText(m.content, false).trim()); },
  "copy-art": (el) => { const a = ART.get(el.dataset.k); if (a) copy(a.code); },
  "open-art": (el) => openArt(el.dataset.k),
  "close-art": () => closeArt(),
  "art-tab": (el) => openArt(S.artKey, el.dataset.t),
  "dl-art": (el) => {
    const a = ART.get(el.dataset.k); if (!a) return;
    const ext = { html: "html", htm: "html", svg: "svg", xml: "xml", py: "py", python: "py", js: "js", javascript: "js", ts: "ts", css: "css", json: "json", sh: "sh", bash: "sh", sql: "sql", md: "md" }[a.lang] || "txt";
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([a.code], { type: "text/plain" }));
    link.download = (a.title || "artifact").replace(/[^\w.-]+/g, "-").slice(0, 50) + "." + ext; link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 2000);
  },
  "toggle-tool": (el) => {
    const chat = chatFor(el.dataset.scope);
    for (const m of chat.messages) for (const s of m.segs || []) if (s.id === el.dataset.id) s.open = !s.open;
    const box = el.closest(".tool"); if (box) box.classList.toggle("open");
  },
  "approve": async (el) => {
    const id = el.dataset.id;
    await api("/api/approve", { method: "POST", body: { id, allow: el.dataset.allow === "1", always: el.dataset.always === "1" } }).catch((e) => toast(e.message, true));
  },
  "model-menu": (el) => modelMenu(el, el.dataset.scope),
  "pick-model": (el) => { setModel(el.dataset.id); closePop(); focusComposer(el.dataset.scope); },
  "tools-menu": (el) => toolsMenu(el, el.dataset.scope),
  "toggle-toolset": (el) => {
    const t = S.tools[el.dataset.scope]; t[el.dataset.k] = !t[el.dataset.k]; LS.set("tools", S.tools);
    el.querySelector(".switch").classList.toggle("on", t[el.dataset.k]); renderComposer(el.dataset.scope);
  },
  "toggle-mcp": (el) => {
    const t = S.tools[el.dataset.scope]; t.mcp = t.mcp || [];
    const i = t.mcp.indexOf(el.dataset.id); if (i >= 0) t.mcp.splice(i, 1); else t.mcp.push(el.dataset.id);
    LS.set("tools", S.tools); el.querySelector(".switch").classList.toggle("on", i < 0); renderComposer(el.dataset.scope);
  },
  "attach": (el) => attachMenu(el, el.dataset.scope),
  "upload": (el) => { closePop(); const f = $("#file-in"); f.onchange = () => { addFiles(el.dataset.scope, [...f.files]); f.value = ""; }; f.click(); },
  "shot": async (el) => {
    closePop();
    try {
      const r = await api("/api/computer/screenshot", { method: "POST", body: {} });
      const blob = await (await fetch(r.url)).blob();
      const data_url = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });
      S.att[el.dataset.scope].push({ name: "screenshot.png", type: "image", data_url }); renderComposer(el.dataset.scope);
    } catch (e) { toast(e.message, true); }
  },
  "add-url": (el) => {
    closePop();
    const back = modal("Add a web page", `<div class="field"><label>Address</label><input class="input" id="au" placeholder="https://…"></div>`,
      `<button class="btn ghost" data-act="close-modal">Cancel</button><button class="btn primary" data-act="add-url-go">Add</button>`);
    back.scope = el.dataset.scope;
    $("#au").addEventListener("keydown", (e) => { if (e.key === "Enter") ACT["add-url-go"](); });
  },
  "add-url-go": async () => {
    const back = $(".modal-back"), url = $("#au").value.trim(); if (!url) return;
    try {
      const r = await api("/api/reader?url=" + encodeURIComponent(toUrl(url)));
      S.att[back.scope].push({ name: r.title || r.url, type: "text", content: `${r.url}\n\n${r.text}` }); closeModal(); renderComposer(back.scope);
    } catch (e) { toast(e.message, true); }
  },
  "rm-att": (el) => { S.att[el.dataset.scope].splice(+el.dataset.i, 1); renderComposer(el.dataset.scope); },
  "close-modal": () => closeModal(),
  // code
  "pick-project": () => folderPicker((p) => openProject(p), (S.st && S.st.home) || ""),
  "open-project": (el) => openProject(el.dataset.root),
  "close-project": () => { S.project = null; S.codeChat = null; renderView(); renderTop(); },
  "refresh-project": () => refreshProject(),
  "tree-dir": async (el) => {
    const P = S.project, p = el.dataset.p;
    if (P.expanded.has(p)) P.expanded.delete(p);
    else {
      P.expanded.add(p);
      if (!P.tree[p]) { try { P.tree[p] = (await api(`/api/fs/list?root=${encodeURIComponent(P.root)}&path=${encodeURIComponent(p)}`)).entries; } catch (e) { toast(e.message, true); } }
    }
    renderTree();
  },
  "tree-file": (el) => openFile(el.dataset.p),
  "close-file": () => { S.project.file = null; renderView(); },
  "edit-file": () => { S.project.file.editing = true; renderViewer(); },
  "edit-cancel": () => { S.project.file.editing = false; S.project.file.dirty = false; renderViewer(); },
  "edit-save": () => saveFile(),
  "ask-file": () => { const ta = $("#ta-code"); if (ta) { ta.value = `In ${S.project.file.path}: ` + ta.value; ta.focus(); ta.dispatchEvent(new Event("input")); } },
  "fp-nav": (el) => $(".modal-back").fpNav(el.dataset.p),
  "fp-pick": () => $(".modal-back").fpPick(),
  "fp-go": () => $(".modal-back").fpGo(),
  "setup-coder": (el) => startJob("/api/setup/coder", { preset: el.dataset.p }),
  // browser
  "b-go": (el) => bNav(el.dataset.u),
  "b-back": () => { const B = S.browser; if (B.idx > 0) { B.idx--; bNav(B.hist[B.idx], false); } },
  "b-fwd": () => { const B = S.browser; if (B.idx < B.hist.length - 1) { B.idx++; bNav(B.hist[B.idx], false); } },
  "b-reload": () => drawFrame(),
  "b-reader": () => { S.browser.reader = !S.browser.reader; viewBrowser($("#view-browser")); },
  "b-ext": () => window.open(S.browser.url, "_blank", "noopener"),
  "b-ask": async () => {
    try {
      const r = await api("/api/reader?url=" + encodeURIComponent(S.browser.url));
      S.chat = newChatObj("chat"); S.att.chat = [{ name: r.title || r.url, type: "text", content: `${r.url}\n\n${r.text}` }];
      go("chat"); setTimeout(() => { const ta = $("#ta-chat"); if (ta) { ta.value = "Summarize this page and pull out anything important."; ta.dispatchEvent(new Event("input")); ta.focus(); } }, 80);
    } catch (e) { toast(e.message, true); }
  },
  // routines
  "new-routine": () => routineModal(),
  "edit-routine": (el) => routineModal((S.routines || []).find((r) => r.id === el.dataset.id)),
  "r-mode": (el) => {
    const back = $(".modal-back"); back.daily = el.dataset.m === "daily";
    $$(".seg button", back).forEach((b) => b.classList.toggle("on", b === el));
    $("#r-at").style.display = back.daily ? "" : "none"; $("#r-every").style.display = back.daily ? "none" : ""; $("#r-unit").style.display = back.daily ? "none" : "";
  },
  "save-routine": async () => {
    const back = $(".modal-back"), r = { ...back.routine };
    r.name = $("#r-name").value.trim() || "Routine"; r.prompt = $("#r-prompt").value.trim(); r.model = $("#r-model").value;
    if (!r.prompt) { toast("Describe what the routine should do", true); return; }
    if (back.daily) { r.at_time = $("#r-at").value.trim() || "09:00"; delete r.every_minutes; } else { r.every_minutes = Math.max(1, parseInt($("#r-every").value) || 60); delete r.at_time; }
    await api("/api/routines", { method: "POST", body: { routine: r } }); closeModal(); toast("Routine saved"); go("routines"); if (S.view === "routines") viewRoutines($("#view-routines"));
  },
  "toggle-routine": async (el) => { const r = S.routines.find((x) => x.id === el.dataset.id); r.enabled = r.enabled === false; await api("/api/routines", { method: "POST", body: { routine: r } }); el.classList.toggle("on", r.enabled); },
  "run-routine": async (el) => { el.disabled = true; el.innerHTML = '<div class="spin"></div>Running…'; try { await api("/api/routines/run", { method: "POST", body: { id: el.dataset.id } }); } catch (e) { toast(e.message, true); } viewRoutines($("#view-routines")); },
  "del-routine": async (el) => { await api("/api/routines/delete", { method: "POST", body: { id: el.dataset.id } }); viewRoutines($("#view-routines")); },
  // connectors
  "mcp-toggle": async (el) => { const s = S.mcpServers.find((x) => x.id === el.dataset.id); s.enabled = s.enabled === false; await api("/api/mcp", { method: "POST", body: { server: s } }); el.classList.toggle("on", s.enabled); },
  "mcp-del": async (el) => { await api("/api/mcp/delete", { method: "POST", body: { id: el.dataset.id } }); viewConnectors($("#view-connectors")); },
  "mcp-tools": async (el) => {
    const box = $("#mt-" + CSS.escape(el.dataset.id)); box.innerHTML = '<div class="muted" style="margin-top:10px"><span class="spin" style="display:inline-block;vertical-align:-2px"></span> Starting server…</div>';
    const r = await api("/api/mcp/tools", { method: "POST", body: { ids: [el.dataset.id] } }).catch((e) => ({ tools: [], error: e.message }));
    box.innerHTML = r.tools && r.tools.length ? `<div style="margin-top:10px">${r.tools.map((t) => `<span class="badge" title="${esc(t.description)}" style="margin:0 6px 6px 0;display:inline-block">${esc(t.name)}</span>`).join("")}</div>`
      : `<div class="muted" style="margin-top:10px;color:var(--warn)">Couldn't start it${r.error ? ": " + esc(r.error) : ""}. Check the command is installed.</div>`;
  },
  "mcp-import": async () => {
    try { const r = await api("/api/mcp/import", { method: "POST", body: {} }); toast(r.added.length ? `Imported ${r.added.length} connector(s)` : "Nothing new to import"); viewConnectors($("#view-connectors")); }
    catch (e) { toast(e.message, true); }
  },
  "mcp-gallery": (el) => {
    const g = (S.st.mcp_gallery || []).find((x) => x.id === el.dataset.id); if (!g) return;
    const add = async (folder) => {
      const args = g.args.map((a) => a.replace("{folder}", folder || ""));
      await api("/api/mcp", { method: "POST", body: { server: { id: g.id, name: g.name, command: g.command, args, enabled: true } } }).catch((e) => toast(e.message, true));
      toast(`${g.name} added`); viewConnectors($("#view-connectors"));
    };
    if (g.needs === "folder") folderPicker(add, S.st.home); else add();
  },
  "mcp-add": () => {
    modal("Add a connector", `<div class="field"><label>Name</label><input class="input" id="m-name" placeholder="My server"></div>
      <div class="field"><label>Command</label><input class="input mono" id="m-cmd" placeholder="npx"></div>
      <div class="field"><label>Arguments</label><textarea class="textarea mono" id="m-args" placeholder="-y&#10;@modelcontextprotocol/server-memory"></textarea><div class="help">One per line.</div></div>
      <div class="field"><label>Environment</label><textarea class="textarea mono" id="m-env" placeholder="API_KEY=…"></textarea><div class="help">KEY=VALUE, one per line.</div></div>`,
      `<button class="btn ghost" data-act="close-modal">Cancel</button><button class="btn primary" data-act="mcp-add-go">Add</button>`);
  },
  "mcp-add-go": async () => {
    const env = {}; $("#m-env").value.split("\n").forEach((l) => { const i = l.indexOf("="); if (i > 0) env[l.slice(0, i).trim()] = l.slice(i + 1).trim(); });
    const s = { name: $("#m-name").value.trim() || "server", command: $("#m-cmd").value.trim(), args: $("#m-args").value.split("\n").map((x) => x.trim()).filter(Boolean), env, enabled: true };
    try { await api("/api/mcp", { method: "POST", body: { server: s } }); closeModal(); viewConnectors($("#view-connectors")); } catch (e) { toast(e.message, true); }
  },
  // settings
  "stab": (el) => { S.settingsTab = el.dataset.t; history.replaceState(null, "", "#/settings/" + el.dataset.t); viewSettings($("#view-settings")); },
  "set-theme": (el) => { applyTheme(el.dataset.t); api("/api/prefs", { method: "POST", body: { prefs: { theme: el.dataset.t } } }).catch(() => {}); viewSettings($("#view-settings")); },
  "set-accent": (el) => { document.documentElement.style.setProperty("--accent", el.dataset.c); LS.set("accent_raw", el.dataset.c); try { localStorage.setItem("cs.accent", el.dataset.c); } catch (e) {} viewSettings($("#view-settings")); renderSide(); },
  "set-font": (el) => { LS.set("font", el.dataset.f); applyFont(); viewSettings($("#view-settings")); },
  "set-approval": async (el) => { await savePrefs({ tool_approval: el.dataset.v }); viewSettings($("#view-settings")); },
  "toggle-pref": async (el) => { const k = el.dataset.k, cur = (S.st.prefs || {})[k] !== false; await savePrefs({ [k]: !cur }); el.classList.toggle("on", !cur); },
  "prov-connect": async (el) => {
    const id = el.dataset.id, inp = $("#k-" + CSS.escape(id));
    el.disabled = true; el.textContent = "Connecting…";
    try { const r = await api("/api/providers/connect", { method: "POST", body: { id, key: inp ? inp.value : "" } }); toast(`Connected — ${r.models.length} models${r.warning ? " (using defaults)" : ""}`); await refreshState(); }
    catch (e) { toast(e.message, true); }
    viewSettings($("#view-settings"));
  },
  "prov-custom": async () => {
    try { const r = await api("/api/providers/connect", { method: "POST", body: { id: "custom", name: $("#c-name").value, base_url: $("#c-url").value, key: $("#c-key").value } }); toast(`Connected ${r.id} — ${r.models.length} models`); await refreshState(); viewSettings($("#view-settings")); }
    catch (e) { toast(e.message, true); }
  },
  "prov-off": async (el) => { await api("/api/providers/disconnect", { method: "POST", body: { id: el.dataset.id } }); await refreshState(); viewSettings($("#view-settings")); },
  "prov-refresh": async (el) => { try { const r = await api("/api/providers/refresh", { method: "POST", body: { id: el.dataset.id } }); toast(`${r.models.length} models`); await refreshState(); viewSettings($("#view-settings")); } catch (e) { toast(e.message, true); } },
  "prov-check": async () => { await refreshState(); viewSettings($("#view-settings")); },
  "rescan": async () => { try { await api("/api/scan", { method: "POST", body: {} }); await refreshState(); toast("Rescanned"); viewSettings($("#view-settings")); } catch (e) { toast(e.message, true); } },
  "hf-pull": () => { const repo = $("#hf-repo").value.trim(); if (!repo) return; startJob("/api/pull", { repo, only: $("#hf-only").value.trim() || undefined }); },
  "install": (el) => startJob("/api/install", { target: el.dataset.t }),
  "save-ctx": async () => {
    const n = (k) => { const v = parseFloat($("#c-" + k).value); return isNaN(v) ? undefined : v; };
    const context = { system: $("#c-system").value, temperature: n("temperature"), top_p: n("top_p"), max_new_tokens: n("max_new_tokens"), n_ctx: n("n_ctx"), n_gpu_layers: n("n_gpu_layers"), repeat_penalty: n("repeat_penalty") };
    Object.keys(context).forEach((k) => context[k] === undefined && delete context[k]);
    try { await api("/api/context", { method: "POST", body: { model: S.ctxModel, context } }); toast("Saved"); } catch (e) { toast(e.message, true); }
  },
  "test-shot": async () => { try { const r = await api("/api/computer/screenshot", { method: "POST", body: {} }); $("#shot-out").innerHTML = `<img src="${esc(r.url)}" style="max-width:100%;border-radius:10px;margin-top:12px;border:1px solid var(--line)">`; } catch (e) { toast(e.message, true); } },
};
async function savePrefs(p) { try { const r = await api("/api/prefs", { method: "POST", body: { prefs: p } }); S.st.prefs = r.prefs; } catch (e) { toast(e.message, true); } }
function copy(text) { navigator.clipboard.writeText(text).then(() => toast("Copied"), () => toast("Copy failed", true)); }
async function refreshState() {
  try { S.st = await api("/api/state"); } catch (e) { return; }
  if (!modelById(S.model)) S.model = pickDefaultModel();
  refreshComposers();
}
function applyTheme(t) {
  LS.set("theme_raw", t);
  try { localStorage.setItem("cs.theme", t); } catch (e) {}
  const eff = t === "system" ? (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark") : t;
  document.documentElement.setAttribute("data-theme", eff);
}
function applyFont() { document.documentElement.style.setProperty("--reply", LS.get("font", "serif") === "sans" ? "var(--sans)" : "var(--serif)"); }

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (a) {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey || e.shiftKey) window.open(a.href, "_blank", "noopener"); else bNav(a.href);
    return;
  }
  const el = e.target.closest("[data-act]");
  if (el && el.dataset.act && ACT[el.dataset.act]) { if (el.tagName === "A") e.preventDefault(); ACT[el.dataset.act](el, e); return; }
  if (!e.target.closest(".pop")) closePop();
});
document.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  if (e.key === "Escape") { if ($(".pop")) closePop(); else if ($(".modal-back")) closeModal(); else if ($("#art").classList.contains("open")) closeArt(); else if (S.stream.chat) stopStream("chat"); }
  if (mod && e.shiftKey && e.key.toLowerCase() === "o") { e.preventDefault(); ACT["new-chat"](); }
  if (mod && e.key.toLowerCase() === "b") { e.preventDefault(); ACT["toggle-side"](); }
  if (mod && e.key === ",") { e.preventDefault(); go("settings", S.settingsTab); }
});
window.addEventListener("hashchange", route);
window.addEventListener("focus", () => { refreshState(); });
window.addEventListener("dragover", (e) => { e.preventDefault(); });
window.addEventListener("drop", (e) => {
  e.preventDefault();
  const files = [...(e.dataTransfer && e.dataTransfer.files || [])];
  if (files.length) addFiles(S.view === "code" && S.project ? "code" : "chat", files);
});

/* ─────────────────────────── boot ─────────────────────────── */
async function boot() {
  const t0 = performance.now();
  applyFont();
  if (LS.get("side", false)) $("#app").classList.add("side-hidden");
  try { S.st = await api("/api/state"); }
  catch (e) { $("#splash").innerHTML = `<div style="text-align:center;color:var(--text-2)">Couldn't reach CS Framework.<br><small>${esc(e.message)}</small></div>`; return; }
  S.model = pickDefaultModel();
  if (!S.tools.chat) S.tools.chat = { code: false, web: false, computer: false, mcp: [] };
  if (!S.tools.code) S.tools.code = { code: true, web: false, computer: false, mcp: [] };
  await Promise.all([loadChats(), loadMcp()]);
  await route();
  const wait = Math.max(0, 700 - (performance.now() - t0));
  setTimeout(() => $("#splash").classList.add("gone"), wait);
}
boot();
