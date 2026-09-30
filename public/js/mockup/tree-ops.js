// Operations on a mockup tree (the editor's working copy). They change the tree in
// place; ids never change, so criteria keep pointing at the same components.
// The server re-checks every rule on save; these only keep the editor sensible.

export const CONTAINERS = new Set(["header", "card", "grid", "price_card", "form", "footer", "section"]);
const GRID_CHILDREN = new Set(["card", "price_card", "image"]);

/** { node, list, index, parent } for an id, or null. `list` is the array holding it. */
export function locate(tree, id, list = tree.components, parent = null) {
  for (let index = 0; index < list.length; index++) {
    const node = list[index];
    if (node.id === id) return { node, list, index, parent };
    const inner = node.children ? locate(tree, id, node.children, node) : null;
    if (inner) return inner;
  }
  return null;
}

function contains(node, id) {
  return (node.children ?? []).some((c) => c.id === id || contains(c, id));
}

/** Whether `node` may sit directly inside `parent` (null: top level). */
export function fits(node, parent) {
  if (!parent) return true;
  if (!CONTAINERS.has(parent.type)) return false;
  return parent.type !== "grid" || GRID_CHILDREN.has(node.type);
}

export function remove(tree, id) {
  const at = locate(tree, id);
  if (!at) return null;
  at.list.splice(at.index, 1);
  if (at.parent && !at.parent.children.length) at.parent.children = null;
  return at.node;
}

/**
 * Put `node` next to or into the component `targetId`: into it when it is a
 * container that accepts the node and `into` is asked for, otherwise right after it
 * (or at the end of the page when there is no target). Returns false when the move
 * would put a component inside itself.
 */
export function place(tree, node, targetId, { into = false } = {}) {
  if (targetId && (targetId === node.id || contains(node, targetId))) return false;
  const target = targetId ? locate(tree, targetId) : null;
  if (!target) {
    tree.components.push(node);
    return true;
  }
  if (into && fits(node, target.node)) {
    target.node.children = [...(target.node.children ?? []), node];
    return true;
  }
  // After the target; if its parent does not accept the node, after the parent instead.
  if (!fits(node, target.parent)) {
    return target.parent ? place(tree, node, target.parent.id) : false;
  }
  target.list.splice(target.index + 1, 0, node);
  return true;
}

/** Move an existing component (see place). */
export function move(tree, id, targetId, options) {
  const found = locate(tree, id);
  if (!found || (targetId && (targetId === id || contains(found.node, targetId)))) return false;
  const node = remove(tree, id);
  return place(tree, node, targetId, options);
}

/** Move a component one step up or down among its siblings. */
export function shift(tree, id, delta) {
  const at = locate(tree, id);
  if (!at) return false;
  const to = at.index + delta;
  if (to < 0 || to >= at.list.length) return false;
  at.list.splice(at.index, 1);
  at.list.splice(to, 0, at.node);
  return true;
}

export function allIds(tree) {
  const ids = new Set();
  const walk = (node) => { ids.add(node.id); (node.children ?? []).forEach(walk); };
  tree.components.forEach(walk);
  return ids;
}

/** A fresh id for a new component of `type`, unique in the tree and not in `also`. */
export function newId(tree, type, also = new Set()) {
  const taken = allIds(tree);
  const stem = type.replace(/_/g, "-");
  let n = 1;
  while (taken.has(`${stem}-${n}`) || also.has(`${stem}-${n}`)) n++;
  return `${stem}-${n}`;
}

/** A deep copy with every id made unique again (for "duplicate"). */
export function copyWithNewIds(tree, node) {
  const copy = structuredClone(node);
  const given = new Set();
  const renumber = (n) => {
    n.id = newId(tree, n.type, given);
    given.add(n.id);
    (n.children ?? []).forEach(renumber);
  };
  renumber(copy);
  return copy;
}
