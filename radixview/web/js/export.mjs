// Filename and JSON text for the node-blocks download. No DOM.

export function exportFilename(version) {
  return "radixview-node-blocks-v" + version + ".json";
}

export function exportBody(payload) {
  return JSON.stringify(payload, null, 2) + "\n";
}
