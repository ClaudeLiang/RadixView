// Page wiring: poll the tree, handle pan/zoom/select/search, fill the panel.

import { fetchPages, fetchTree, searchText } from "./api.mjs";
import { clip, hitsLine, nodeTitle, pageMeta, statsLine } from "./format.mjs";
import { layoutTree, pathTo } from "./layout.mjs";
import { drawScene } from "./render.mjs";
import { centerOn, fitView, hitTest, initialView, panBy, zoomAt } from "./viewport.mjs";

const POLL_MS = 1000;
const SEARCH_DELAY_MS = 200;
const PATH_CHARS = 12;

const $ = (id) => document.getElementById(id);
const canvas = $("canvas");
const ctx = canvas.getContext("2d");

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

function applyTree(payload) {
  if (payload.unchanged) return;
  state.version = payload.version;
  state.nodes = payload.nodes;
  state.byId = new Map(payload.nodes.map((node) => [node.id, node]));
  state.layout = layoutTree(payload.nodes);
  $("stats").textContent = statsLine(payload.stats);
  $("empty").style.display = payload.nodes.length ? "none" : "grid";
  if (!state.fitted && payload.nodes.length) {
    state.fitted = true;
    state.view = initialView(state.layout, screen());
  }
  if (state.selected && !state.byId.has(state.selected)) closeDetail();
  if (state.query) runSearch();
  state.dirty = true;
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
  renderPages(state.byId.get(id));
}

function closeDetail() {
  state.selected = null;
  state.path = null;
  $("detail").classList.remove("open");
  resize();
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

async function renderPages(node) {
  const box = $("pages");
  if (node.missing) {
    box.replaceChildren(paragraph(
      "This page was stored before RadixView subscribed, so the stream has no text for it."));
    return;
  }
  const pages = await fetchPages(node.id);
  if (state.selected !== node.id) return;
  box.replaceChildren(...pages.map(pageBlock));
}

function pageBlock(page) {
  const block = document.createElement("div");
  block.className = "page";
  const meta = document.createElement("div");
  meta.className = "meta";
  meta.textContent = pageMeta(page);
  block.append(meta, document.createTextNode(page.text || "(empty)"));
  return block;
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

function onQuery() {
  state.query = $("query").value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(runSearch, SEARCH_DELAY_MS);
}

function onQueryKey(event) {
  const hit = event.key === "Enter" ? firstHit() : null;
  if (hit) focus(hit.id);
}

canvas.addEventListener("pointerdown", onPointerDown);
canvas.addEventListener("wheel", onWheel, { passive: false });
window.addEventListener("pointermove", onPointerMove);
window.addEventListener("pointerup", onPointerUp);
window.addEventListener("resize", resize);
window.addEventListener("keydown", onKey);
$("query").addEventListener("input", onQuery);
$("query").addEventListener("keydown", onQueryKey);
$("fit").addEventListener("click", fit);

resize();
requestAnimationFrame(frame);
poll();
