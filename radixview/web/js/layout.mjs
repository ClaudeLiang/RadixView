// Tidy left-to-right layout, the way a prompt reads: depth runs along x,
// leaves are stacked evenly along y, and a parent sits level with the middle
// of its first and last child. A wide fan-out under the system prompt grows
// downward, where the page scrolls. Iterative, so a deep tree cannot
// overflow the call stack.

export const NODE_W = 240;
export const NODE_H = 64;
export const COL_GAP = 72;
export const ROW_GAP = 16;

export function layoutTree(nodes) {
  const { children, roots, parentOf } = links(nodes);
  const positions = new Map();
  let leaves = 0;
  let depth = 0;
  const stack = roots.map((id) => ({ id, depth: 0, open: false })).reverse();
  while (stack.length) {
    const item = stack.pop();
    const kids = children.get(item.id);
    if (kids.length && !item.open) {
      item.open = true;
      stack.push(item);
      for (let i = kids.length - 1; i >= 0; i -= 1) {
        stack.push({ id: kids[i], depth: item.depth + 1, open: false });
      }
      continue;
    }
    const x = item.depth * (NODE_W + COL_GAP);
    depth = Math.max(depth, item.depth);
    if (kids.length) {
      const first = positions.get(kids[0]).y;
      const last = positions.get(kids[kids.length - 1]).y;
      positions.set(item.id, { x, y: (first + last) / 2 });
    } else {
      positions.set(item.id, { x, y: leaves * (NODE_H + ROW_GAP) });
      leaves += 1;
    }
  }
  return {
    positions,
    children,
    parentOf,
    roots,
    width: positions.size ? (depth + 1) * (NODE_W + COL_GAP) - COL_GAP : 0,
    height: leaves ? leaves * (NODE_H + ROW_GAP) - ROW_GAP : 0,
  };
}

export function pathTo(id, parentOf) {
  const path = [];
  for (let cursor = id; cursor !== undefined; cursor = parentOf.get(cursor)) {
    path.push(cursor);
  }
  return path.reverse();
}

function links(nodes) {
  const children = new Map(nodes.map((node) => [node.id, []]));
  const parentOf = new Map();
  const roots = [];
  for (const node of nodes) {
    if (node.parent !== null && children.has(node.parent)) {
      children.get(node.parent).push(node.id);
      parentOf.set(node.id, node.parent);
    } else {
      roots.push(node.id);
    }
  }
  return { children, roots, parentOf };
}
