// JSON endpoints served by radixview/server.py.

export async function fetchTree(since) {
  const query = since === null ? "" : "?since=" + since;
  return getJson("/api/tree" + query);
}

export async function fetchBlocks(id) {
  const payload = await getJson("/api/run?id=" + encodeURIComponent(id));
  return payload.blocks;
}

export async function searchText(query) {
  const payload = await getJson("/api/search?q=" + encodeURIComponent(query));
  return payload.ids;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(url + " " + response.status);
  return response.json();
}
