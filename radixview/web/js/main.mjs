// Page wiring: poll the tree, handle pan/zoom/select/search, fill the panel.

import { fetchBlocks, fetchNodeBlocks, fetchTree, locateNode, searchText } from "./api.mjs";
import { exportBody, exportFilename } from "./export.mjs";
import { blockMeta, clip, hitsLine, nodeTitle, poolOccupancy, statsLine } from "./format.mjs";
import { layoutTree, pathTo } from "./layout.mjs";
import { pagesByHash, releaseText, shownReleases, slotFields } from "./pool.mjs";
import { drawScene } from "./render.mjs";
import { centerOn, fitView, hitTest, initialView, panBy, zoomAt } from "./viewport.mjs";

const POLL_MS = 1000;
const SEARCH_DELAY_MS = 200;
const PATH_CHARS = 12;

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const ctx = canvas.getContext("2d");
const tierButtons = [...document.querySelectorAll("#tiers [data-tier]")];

const state = {
  version: null,
  nodes: [],
  byId: new Map(),
  layout: layoutTree([]),
  view: { x: 40, y: 40, z: 1 },
  fitted: false,
  selected: null,
  path: null,
  highlight: null,
  query: "",
  stats: null,
  panel: null,
  tiers: Object.fromEntries(
    tierButtons.map((button) => [button.dataset.tier, button.classList.contains("on")])),
  drag: null,
  dirty: true,
};

function theme() {
  const css = getComputedStyle(document.documentElement);
  const value = (name) => css.getPropertyValue("--" + name).trim();
  return {
    ratio: window.devicePixelRatio || 1,
    font: value("font"),
    text: value("text"),
    muted: value("muted"),
    accent: value("accent"),
    missing: value("missing"),
    node: value("node"),
    nodeLine: value("node-line"),
    edge: value("edge"),
    hit: value("hit"),
    gpu: value("gpu"),
    cpu: value("cpu"),
    mamba: value("mamba"),
    other: value("other"),
  };
}

let colors = theme();

function screen() {
  return { width: canvas.clientWidth, height: canvas.clientHeight };
}

function resize() {
  colors = theme();
  canvas.width = Math.max(1, Math.floor(canvas.clientWidth * colors.ratio));
  canvas.height = Math.max(1, Math.floor(canvas.clientHeight * colors.ratio));
  state.dirty = true;
}

function frame() {
  if (state.dirty) {
    state.dirty = false;
    drawScene(ctx, state, state.view, screen(), colors);
  }
  requestAnimationFrame(frame);
}

function fit() {
  state.view = fitView(state.layout.width, state.layout.height, screen());
  state.dirty = true;
}

function showStats() {
  $("stats").textContent = statsLine(state.stats);
  if (state.panel === "pool") renderPool();
}

function applyTree(payload) {
  if (payload.unchanged) {
    if (state.stats) showStats();
    return;
  }
  state.version = payload.version;
  state.nodes = payload.nodes;
  state.byId = new Map(payload.nodes.map((node) => [node.id, node]));
  state.layout = layoutTree(payload.nodes);
  state.stats = payload.stats;
  showStats();
  $("empty").style.display = payload.nodes.length ? "none" : "grid";
  if (!state.fitted && payload.nodes.length) {
    state.fitted = true;
    state.view = initialView(state.layout, screen());
  }
  if (state.selected && !state.byId.has(state.selected)) followSelection(state.selected);
  if (state.query) runSearch();
  state.dirty = true;
}

// A tier change splits or joins chains and renames their nodes. Keep the
// panel on whichever node now holds the first block of the old one.
async function followSelection(id) {
  let next = null;
  try {
    next = await locateNode(id);
  } catch (error) {
    next = null;
  }
  if (state.selected !== id) return;
  if (next !== null && state.byId.has(next)) select(next);
  else closeDetail();
}

async function poll() {
  try {
    applyTree(await fetchTree(state.version));
  } catch (error) {
    $("stats").textContent = "Cannot read the tree. Is RadixView still running?";
  }
  setTimeout(poll, POLL_MS);
}

async function select(id) {
  state.panel = "node";
  state.selected = id;
  const ids = pathTo(id, state.layout.parentOf);
  state.path = new Set(ids);
  state.dirty = true;
  const detail = $("detail");
  if (!detail.classList.contains("open")) {
    detail.classList.add("open");
    resize();
  }
  renderPath(ids, id);
  renderBlocks(state.byId.get(id));
}

function closeDetail() {
  state.panel = null;
  state.selected = null;
  state.path = null;
  $("detail").classList.remove("open");
  resize();
}

function openPool() {
  state.panel = state.panel === "pool" ? null : "pool";
  if (state.panel !== "pool") {
    closeDetail();
    return;
  }
  state.selected = null;
  state.path = null;
  state.dirty = true;
  const detail = $("detail");
  if (!detail.classList.contains("open")) {
    detail.classList.add("open");
    resize();
  }
  renderPool();
}

const SLOT_COLUMNS = ["pool", "slot", "role", "from", "page", "seqlen"];

function renderPool() {
  const mamba = (state.stats && state.stats.mamba) || { pools: {}, slots: [], releases: [] };
  $("path").replaceChildren(paragraph(poolHeading(mamba)));
  const box = $("blocks");
  box.replaceChildren(poolTable(mamba, pagesByHash(state.nodes)));
  const releases = shownReleases(mamba.releases);
  if (releases.length) box.append(releaseNote(), releaseList(releases));
}

function poolHeading(mamba) {
  const line = poolOccupancy(mamba);
  return line ? "Mamba pool · " + line : "Mamba pool";
}

function poolTable(mamba, pages) {
  const table = document.createElement("table");
  table.className = "pool";
  table.append(poolHead());
  for (const row of mamba.slots || []) {
    table.append(slotRow(row, pages.get(String(row.hash))));
  }
  return table;
}

function poolHead() {
  const head = document.createElement("tr");
  for (const name of SLOT_COLUMNS) head.append(headed(name));
  return head;
}

function headed(name) {
  const cell = document.createElement("th");
  cell.textContent = name;
  return cell;
}

function slotRow(row, page) {
  const fields = slotFields(row, page);
  const line = document.createElement("tr");
  for (const name of SLOT_COLUMNS) line.append(fieldCell(name, fields));
  if (fields.node) {
    line.className = "link";
    line.addEventListener("click", () => focus(fields.node));
  }
  return line;
}

function fieldCell(name, fields) {
  const cell = document.createElement("td");
  cell.textContent = fields[name] || "";
  const title = fields[name + "Title"];
  if (title) cell.title = title;
  if (name === "page" || name === "role") cell.className = name;
  return cell;
}

function releaseNote() {
  const note = paragraph("State dropped, page kept");
  note.className = "pool-note";
  return note;
}

function releaseList(rows) {
  const list = document.createElement("ul");
  list.className = "pool-releases";
  for (const row of rows) list.append(releaseItem(row));
  return list;
}

function releaseItem(row) {
  const item = document.createElement("li");
  item.textContent = releaseText(row);
  if (!row.node || !state.byId.has(row.node)) return item;
  item.classList.add("link");
  item.addEventListener("click", () => focus(row.node));
  return item;
}

function renderPath(ids, current) {
  const buttons = ids.map((id) => {
    const button = document.createElement("button");
    button.textContent = clip(nodeTitle(state.byId.get(id)), PATH_CHARS);
    button.className = id === current ? "current" : "";
    button.addEventListener("click", () => focus(id));
    return button;
  });
  $("path").replaceChildren(...buttons);
}

async function renderBlocks(node) {
  const box = $("blocks");
  if (node.missing) {
    box.replaceChildren(paragraph(
      "This block was stored before RadixView subscribed, so the stream has no text for it."));
    return;
  }
  const blocks = await fetchBlocks(node.id);
  if (state.selected !== node.id) return;
  box.replaceChildren(...blocks.map(blockCard));
}

function blockCard(block) {
  const card = document.createElement("div");
  card.className = "block-card";
  const body = document.createElement("div");
  body.className = "block-body";
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = blockMeta(block);
  body.append(meta, document.createTextNode(block.text || "(empty)"));
  card.append(residencyBar(block.media), body);
  return card;
}

function residencyBar(media) {
  const bar = document.createElement("div");
  bar.className = "residency";
  for (const name of media || []) {
    const slice = document.createElement("span");
    slice.dataset.tier = name;
    bar.append(slice);
  }
  return bar;
}

function paragraph(text) {
  const element = document.createElement("p");
  element.textContent = text;
  return element;
}

function focus(id) {
  const point = state.layout.positions.get(id);
  if (!point) return;
  state.view = centerOn(state.view, point, screen());
  select(id);
}

let searchTimer = 0;

async function runSearch() {
  const query = state.query;
  const ids = query ? await searchText(query) : [];
  if (query !== state.query) return;
  state.highlight = query ? new Set(ids) : null;
  $("hits").textContent = hitsLine(query, ids);
  state.dirty = true;
}

function firstHit() {
  if (!state.highlight) return null;
  return state.nodes.find((node) => state.highlight.has(node.id)) || null;
}

function onPointerDown(event) {
  const id = hitTest(state.layout.positions, state.view, event.offsetX, event.offsetY);
  if (id !== null) {
    select(id);
    return;
  }
  state.drag = { x: event.clientX, y: event.clientY, view: state.view };
  canvas.classList.add("drag");
}

function onPointerMove(event) {
  const drag = state.drag;
  if (!drag) return;
  state.view = {
    x: drag.view.x + event.clientX - drag.x,
    y: drag.view.y + event.clientY - drag.y,
    z: drag.view.z,
  };
  state.dirty = true;
}

function onPointerUp() {
  state.drag = null;
  canvas.classList.remove("drag");
}

// Trackpad pinch arrives as a wheel event with ctrlKey set.
function onWheel(event) {
  event.preventDefault();
  if (event.ctrlKey || event.metaKey) {
    const factor = Math.exp(-event.deltaY * 0.01);
    state.view = zoomAt(state.view, factor, event.offsetX, event.offsetY);
  } else {
    state.view = panBy(state.view, -event.deltaX, -event.deltaY);
  }
  state.dirty = true;
}

function onKey(event) {
  if (event.target === $("query")) return;
  if (event.key === "f") fit();
  if (event.key === "Escape") closeDetail();
}

function onTier(event) {
  const button = event.currentTarget;
  const tier = button.dataset.tier;
  state.tiers[tier] = !state.tiers[tier];
  button.classList.toggle("on", state.tiers[tier]);
  button.setAttribute("aria-pressed", String(state.tiers[tier]));
  state.dirty = true;
}

function onQuery() {
  state.query = $("query").value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, SEARCH_DELAY_MS);
}

function onQueryKey(event) {
  const hit = event.key === "Enter" ? firstHit() : null;
  if (hit) focus(hit.id);
}

async function onExport() {
  const button = $("export");
  button.disabled = true;
  $("export-error").textContent = "";
  try {
    const payload = await fetchNodeBlocks();
    download(exportFilename(payload.version), exportBody(payload));
    if (state.stats) showStats();
  } catch (error) {
    $("export-error").textContent = "Export failed";
  } finally {
    button.disabled = false;
  }
}

// Hold the URL until the next export. A save dialog can stay open longer
// than any short timer, and revoking early writes an empty file.
let downloadUrl = "";

function download(name, text) {
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
}

canvas.addEventListener("pointerdown", onPointerDown);
canvas.addEventListener("wheel", onWheel, { passive: false });
window.addEventListener("pointermove", onPointerMove);
window.addEventListener("pointerup", onPointerUp);
window.addEventListener("resize", resize);
window.addEventListener("keydown", onKey);
for (const button of tierButtons) button.addEventListener("click", onTier);
$("query").addEventListener("input", onQuery);
$("query").addEventListener("keydown", onQueryKey);
$("pool").addEventListener("click", openPool);
$("export").addEventListener("click", onExport);
$("fit").addEventListener("click", fit);

resize();
requestAnimationFrame(frame);
poll();
