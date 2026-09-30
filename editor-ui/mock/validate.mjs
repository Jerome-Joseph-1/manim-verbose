// A small stand-in for manim_verbose/scenefile/validate.py: reads the json schema and checks
// a document against it, then makes the whole document checks the models can't, wording
// problems the way the real validator does. Good enough to exercise the editor.

const ID_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
const HEX = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;
export const COLOR_NAMES = new Set([
  ...['BLUE', 'TEAL', 'GREEN', 'YELLOW', 'GOLD', 'RED', 'MAROON', 'PURPLE', 'GREY', 'GRAY'].flatMap((c) => [c, ...'ABCDE'.split('').map((l) => `${c}_${l}`)]),
  'WHITE', 'BLACK', 'PINK', 'LIGHT_PINK', 'ORANGE', 'GREY_BROWN', 'GRAY_BROWN', 'DARK_BROWN', 'LIGHT_BROWN',
  'PURE_RED', 'PURE_GREEN', 'PURE_BLUE',
]);

export function formatLoc(loc) {
  let out = '';
  for (const part of loc) {
    if (typeof part === 'number') out += `[${part}]`;
    else out += out ? `.${part}` : part;
  }
  return out;
}

function idsAt(loc, data) {
  let sceneId = null;
  let itemId = null;
  let node = data;
  for (const part of loc) {
    if (node === null || typeof node !== 'object' || !(part in node)) break;
    node = node[part];
    if (node && typeof node === 'object' && !Array.isArray(node) && typeof node.id === 'string') {
      if (sceneId === null && ('objects' in node || 'steps' in node || loc[0] === 'scenes' && loc.indexOf(part) === 1)) sceneId = node.id;
      else itemId = node.id;
    }
  }
  return { sceneId, itemId };
}

export function problem(message, loc, data, severity = 'error', ids = null) {
  const found = ids ?? idsAt(loc, data);
  return { message, severity, loc, path: formatLoc(loc), scene_id: found.sceneId, item_id: found.itemId };
}

function similarity(a, b) {
  const m = a.length;
  const n = b.length;
  if (!m && !n) return 1;
  const d = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)]);
  for (let j = 1; j <= n; j += 1) d[0][j] = j;
  for (let i = 1; i <= m; i += 1) {
    for (let j = 1; j <= n; j += 1) {
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
  }
  return 1 - d[m][n] / Math.max(m, n);
}

export function didYouMean(word, options) {
  let best = null;
  let score = 0.6;
  for (const option of options) {
    const s = similarity(String(word), String(option));
    if (s >= score) {
      score = s;
      best = option;
    }
  }
  return best ? ` (did you mean '${best}'?)` : '';
}

function a(kind) {
  if (kind === 'document') return 'the document';
  return (/^[aeiou]/.test(kind) ? 'an ' : 'a ') + kind;
}

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export class Validator {
  constructor(schema) {
    this.schema = schema;
    this.defs = schema.$defs ?? {};
    const scene = this.defs.SceneSpec;
    this.objectDefs = mapping(scene.properties.objects.items.discriminator.mapping, this.defs);
    this.stepDefs = mapping(scene.properties.steps.items.discriminator.mapping, this.defs);
  }

  deref(s) {
    let node = s ?? {};
    while (node.$ref) {
      const { $ref, ...rest } = node;
      node = { ...this.defs[$ref.replace('#/$defs/', '')], ...rest };
    }
    return node;
  }

  /** Model level problems: when there are any, the document can't be read at all. */
  structural(data) {
    if (!isObj(data)) return [problem('A scene file has to be a mapping, with `scenes` at the top level', [], data)];
    const out = [];
    this.model(data, this.schema, [], 'document', data, out);
    return out;
  }

  model(value, def, loc, kind, root, out) {
    def = this.deref(def);
    if (!isObj(value)) {
      out.push(problem(`'${loc.filter((p) => typeof p === 'string').at(-1) ?? 'value'}' has to be a mapping of names to values`, loc, root));
      return;
    }
    const props = def.properties ?? {};
    for (const name of def.required ?? []) {
      if (!(name in value)) out.push(problem(`${a(kind)} needs '${name}'`, [...loc, name], root));
    }
    for (const [key, v] of Object.entries(value)) {
      if (!(key in props)) {
        if (def.additionalProperties === false) {
          out.push(problem(`'${key}' isn't something ${a(kind)} has${didYouMean(key, Object.keys(props))}`, [...loc, key], root));
        }
        continue;
      }
      this.value(v, props[key], [...loc, key], key, root, out);
    }
    this.crossField(value, def, loc, kind, root, out);
  }

  crossField(value, def, loc, kind, root, out) {
    const title = def.title;
    const push = (message, where = loc) => out.push(problem(message, where, root));
    if (title === 'Placement') {
      const given = ['at', 'edge', 'next_to'].filter((n) => value[n] !== undefined && value[n] !== null);
      if (given.length > 1) push(`Give only one of at, edge or next_to, not ${given.join(' and ')}`);
    }
    if (title === 'MoveStep' && (value.to == null) === (value.by == null)) push('A move needs exactly one of `to` or `by`');
    if (title === 'WaitStep' && value.run_time != null) push('A wait takes `duration`, not `run_time`');
    if (title === 'CameraStep') {
      const any = value.reset === true || ['zoom', 'center', 'focus', 'orientation'].some((k) => value[k] != null);
      if (!any) push('A camera step needs at least one of zoom, center, focus, orientation or reset');
      if (value.center != null && value.focus != null) push('Give only one of center or focus');
    }
    if (title === 'MatrixObject' && Array.isArray(value.entries)) {
      const widths = new Set(value.entries.map((row) => (Array.isArray(row) ? row.length : -1)));
      if (widths.size !== 1 || widths.has(0)) push('Every row of a matrix needs the same number of entries');
    }
    if (title === 'ApplyMatrixStep' && Array.isArray(value.matrix)) {
      const n = value.matrix.length;
      if (![2, 3].includes(n) || value.matrix.some((row) => !Array.isArray(row) || row.length !== n)) {
        push('The matrix has to be 2x2 or 3x3', [...loc, 'matrix']);
      }
    }
    if (title === 'TogetherStep' && Array.isArray(value.steps)) {
      for (const inner of value.steps) {
        if (isObj(inner) && (inner.do === 'wait' || inner.do === 'together')) push(`A '${inner.do}' step can't go inside 'together'`, [...loc, 'steps']);
      }
    }
    void kind;
  }

  value(v, s, loc, name, root, out) {
    const outer = s;
    s = this.deref(s);
    if (name === 'place' || (name === 'to' && loc.length > 4)) {
      // Placement shorthands: `place: top` and `place: [1, 2]`
      if (typeof v === 'string') v = { edge: v };
      else if (Array.isArray(v)) v = { at: v };
    }
    if (s.anyOf) {
      if (v === null && s.anyOf.some((x) => x.type === 'null')) return;
      const variants = s.anyOf.filter((x) => x.type !== 'null');
      let best = null;
      for (const variant of variants) {
        const errs = [];
        this.value(v, { ...variant, 'x-widget': variant['x-widget'] ?? outer['x-widget'] }, loc, name, root, errs);
        if (errs.length === 0) return;
        const d = this.deref(variant);
        const typeMatches = (d.type === 'array' && Array.isArray(v)) || (d.type === 'object' && isObj(v)) || (d.$ref === undefined && typeof v === d.type) || (d.properties && isObj(v));
        if (!best || typeMatches) best = errs;
        if (typeMatches) break;
      }
      out.push(...(best ?? []));
      return;
    }
    if (s.oneOf && s.discriminator) {
      const tagName = s.discriminator.propertyName;
      if (!isObj(v)) {
        out.push(problem('Expected a mapping', loc, root));
        return;
      }
      const tag = v[tagName];
      const isStep = tagName === 'do';
      if (tag === undefined) {
        out.push(problem(isStep ? 'Every step needs `do`, saying what it does, such as `do: show`' : 'Every object needs `type`, saying what it is, such as `type: text`', loc, root));
        return;
      }
      const ref = s.discriminator.mapping[tag];
      if (!ref) {
        const names = Object.keys(s.discriminator.mapping);
        out.push(problem(
          isStep ? `There's no step called '${tag}'${didYouMean(tag, names)}. Steps are: ${names.join(', ')}` : `There's no kind of object called '${tag}'${didYouMean(tag, names)}. Kinds are: ${names.join(', ')}`,
          loc, root,
        ));
        return;
      }
      this.model(v, { $ref: ref }, loc, `${tag} ${isStep ? 'step' : 'object'}`, root, out);
      return;
    }
    if (s.const !== undefined) {
      if (v !== s.const) out.push(problem(`'${v}' isn't allowed here; use one of ${JSON.stringify(s.const)}`, loc, root));
      return;
    }
    if (s.enum) {
      if (!s.enum.includes(v)) out.push(problem(`'${v}' isn't allowed here; use one of ${s.enum.map((e) => `'${e}'`).join(', ')}`, loc, root));
      return;
    }
    const widget = s['x-widget'] ?? outer['x-widget'];
    switch (s.type) {
      case 'string':
        if (typeof v !== 'string') return void out.push(problem(`'${name}' has to be text`, loc, root));
        if (s.pattern && !new RegExp(s.pattern).test(v)) {
          out.push(problem(`'${v}' can't be a name: use letters, digits and _, not starting with a digit`, loc, root));
        }
        if (widget === 'color' && !HEX.test(v) && !COLOR_NAMES.has(v.toUpperCase())) {
          out.push(problem(`'${v}' isn't a color. Use a hex code like "#58C4DD" or a manim color name like BLUE or RED_E`, loc, root));
        }
        return;
      case 'number':
      case 'integer': {
        if (typeof v !== 'number' || Number.isNaN(v)) return void out.push(problem(`'${name}' has to be a number`, loc, root));
        if (s.type === 'integer' && !Number.isInteger(v)) return void out.push(problem(`'${name}' has to be a number with no decimal point`, loc, root));
        if (s.exclusiveMinimum !== undefined && !(v > s.exclusiveMinimum)) out.push(problem(`'${name}' has to be more than ${s.exclusiveMinimum}`, loc, root));
        if (s.minimum !== undefined && v < s.minimum) out.push(problem(`'${name}' has to be at least ${s.minimum}`, loc, root));
        if (s.maximum !== undefined && v > s.maximum) out.push(problem(`'${name}' has to be at most ${s.maximum}`, loc, root));
        return;
      }
      case 'boolean':
        if (typeof v !== 'boolean') out.push(problem(`'${name}' has to be true or false`, loc, root));
        return;
      case 'array': {
        if (!Array.isArray(v)) return void out.push(problem(`'${name}' has to be a list`, loc, root));
        const pointLike = ['point', 'tip', 'tail', 'start', 'end', 'center', 'at', 'shift', 'by'].includes(name);
        const rangeLike = ['x_range', 'y_range', 'z_range'].includes(name);
        if (s.minItems !== undefined && v.length < s.minItems) {
          out.push(problem(pointLike ? `'${name}' is a point, written [x, y] or [x, y, z]` : rangeLike ? `'${name}' is written [min, max] or [min, max, step]` : `'${name}' needs at least ${s.minItems} item(s)`, loc, root));
        }
        if (s.maxItems !== undefined && v.length > s.maxItems) {
          out.push(problem(pointLike ? `'${name}' is a point, written [x, y] or [x, y, z]` : rangeLike ? `'${name}' is written [min, max] or [min, max, step]` : `'${name}' can have at most ${s.maxItems} item(s)`, loc, root));
        }
        if (s.items) v.forEach((item, i) => this.value(item, s.items, [...loc, i], name, root, out));
        return;
      }
      case 'object': {
        if (s.properties) return void this.model(v, s, loc, name === 'settings' ? 'settings' : name === 'place' ? 'placement' : name, root, out);
        if (!isObj(v)) return void out.push(problem(`'${name}' has to be a mapping of names to values`, loc, root));
        if (s.minProperties && Object.keys(v).length < s.minProperties) out.push(problem(`'${name}' needs at least ${s.minProperties} item(s)`, loc, root));
        if (isObj(s.additionalProperties)) {
          for (const [k, item] of Object.entries(v)) this.value(item, s.additionalProperties, [...loc, k], name, root, out);
        }
        return;
      }
      default:
        return;
    }
  }

  /** Everything wrong with a document: structural problems, else the whole document checks. */
  check(data) {
    const structural = this.structural(data);
    if (structural.length) return { readable: false, problems: structural };
    return { readable: true, problems: wholeDocument(data, this) };
  }
}

function mapping(map, defs) {
  const out = {};
  for (const [name, ref] of Object.entries(map)) out[name] = defs[ref.replace('#/$defs/', '')];
  return out;
}

const asList = (t) => (Array.isArray(t) ? t : typeof t === 'string' ? [t] : []);

function objectRefs(obj) {
  const refs = [];
  const place = isObj(obj.place) ? obj.place : null;
  if (place && typeof place.next_to === 'string') refs.push([['place', 'next_to'], place.next_to, null]);
  if (typeof obj.on === 'string') refs.push([['on'], obj.on, obj.type === 'graph' ? ['axes', 'number_plane'] : ['number_plane', 'axes', 'axes_3d', 'number_line']]);
  if ((obj.type === 'brace' || obj.type === 'box') && typeof obj.target === 'string') refs.push([['target'], obj.target, null]);
  if (obj.type === 'group' && Array.isArray(obj.members)) obj.members.forEach((m, i) => refs.push([['members', i], m, null]));
  return refs;
}

function stepRefs(step) {
  const refs = [];
  if (typeof step.target === 'string') refs.push([['target'], step.target]);
  else if (Array.isArray(step.target)) step.target.forEach((t, i) => refs.push([['target', i], t]));
  if (step.do === 'transform' && typeof step.into === 'string') refs.push([['into'], step.into]);
  if (step.do === 'camera' && typeof step.focus === 'string') refs.push([['focus'], step.focus]);
  if (step.do === 'move' && isObj(step.to) && typeof step.to.next_to === 'string') refs.push([['to', 'next_to'], step.to.next_to]);
  return refs;
}

const PART_FIELDS = { text: 'text', tex: 'tex', title: 'text', quote: 'text' };

export function* iterSteps(steps) {
  for (const step of steps ?? []) {
    yield step;
    if (step.do === 'together') yield* iterSteps(step.steps);
  }
}

function wholeDocument(doc, validator) {
  const out = [];
  const seenScenes = new Set();
  const seenSteps = new Set();
  doc.scenes.forEach((scene, s) => {
    const sloc = ['scenes', s];
    const ids = { sceneId: scene.id, itemId: null };
    const add = (message, loc, itemId, severity = 'error') => out.push(problem(message, loc, doc, severity, { sceneId: scene.id, itemId }));
    if (seenScenes.has(scene.id)) add(`Two scenes are called '${scene.id}'`, [...sloc, 'id'], null);
    seenScenes.add(scene.id);
    const objects = new Map();
    (scene.objects ?? []).forEach((obj, i) => {
      if (objects.has(obj.id)) add(`Two objects in this scene are called '${obj.id}'`, [...sloc, 'objects', i, 'id'], obj.id);
      objects.set(obj.id, obj);
    });
    const checkRef = (ref, types, loc, itemId) => {
      if (!objects.has(ref)) {
        add(`There's no object called '${ref}' in scene '${scene.id}'${didYouMean(ref, objects.keys())}`, loc, itemId);
        return false;
      }
      const kind = objects.get(ref).type;
      if (types && !types.includes(kind)) {
        add(`'${ref}' is a ${kind.replace(/_/g, ' ')}, but this needs a ${types.map((t) => t.replace(/_/g, ' ')).join(' or ')}`, loc, itemId);
        return false;
      }
      return true;
    };
    (scene.objects ?? []).forEach((obj, i) => {
      const loc = [...sloc, 'objects', i];
      for (const [where, ref, types] of objectRefs(obj)) {
        checkRef(ref, types, [...loc, ...where], obj.id);
        if (ref === obj.id) add(`'${obj.id}' can't refer to itself`, [...loc, ...where], obj.id);
      }
      if ((obj.type === 'image' || obj.type === 'svg') && typeof obj.path === 'string' && (obj.path.startsWith('/') || obj.path.split(/[\\/]/).includes('..'))) {
        add("Files have to be in the scene file's folder or below it, given as a relative path", [...loc, 'path'], obj.id);
      }
    });
    const checkStep = (step, loc) => {
      if (step.id) {
        if (seenSteps.has(step.id)) add(`Two steps are called '${step.id}'`, [...loc, 'id'], step.id);
        seenSteps.add(step.id);
      }
      for (const [where, ref] of stepRefs(step)) checkRef(ref, null, [...loc, ...where], step.id ?? null);
      if (step.do === 'highlight' && step.part != null && objects.has(step.target)) {
        const target = objects.get(step.target);
        const field = PART_FIELDS[target.type];
        if (!field) add(`Only parts of text, formulas, titles and quotes can be highlighted, and '${step.target}' is a ${target.type}`, [...loc, 'part'], step.id);
        else if (!String(target[field] ?? '').includes(step.part)) add(`'${step.part}' doesn't appear in '${step.target}'`, [...loc, 'part'], step.id);
      }
      if (step.do === 'change' && objects.has(step.target) && isObj(step.set)) {
        const target = objects.get(step.target);
        const def = validator.objectDefs[target.type];
        const fields = Object.keys(def?.properties ?? {});
        for (const key of Object.keys(step.set)) {
          if (key === 'id' || key === 'type') add(`A change can't alter '${key}'`, [...loc, 'set', key], step.id);
          else if (!fields.includes(key)) add(`'${key}' isn't something a ${target.type} has${didYouMean(key, fields)}`, [...loc, 'set', key], step.id);
          else {
            const errs = [];
            validator.value(step.set[key], def.properties[key], [...loc, 'set', key], key, doc, errs);
            for (const e of errs) add(e.message, [...loc, 'set', key], step.id);
          }
        }
      }
      if (step.do === 'together') (step.steps ?? []).forEach((inner, j) => checkStep(inner, [...loc, 'steps', j]));
    };
    (scene.steps ?? []).forEach((step, i) => checkStep(step, [...sloc, 'steps', i]));

    // What is on screen when: warnings, as in validate.py
    const members = (ref) => {
      const obj = objects.get(ref);
      const set = new Set([ref]);
      if (obj?.type === 'group') for (const m of obj.members ?? []) for (const x of members(m)) set.add(x);
      return set;
    };
    let onScreen = new Set((scene.objects ?? []).filter((o) => o.shown).map((o) => o.id));
    (scene.steps ?? []).forEach((step, i) => {
      const loc = [...sloc, 'steps', i];
      const warnAbsent = (ref) => {
        if (objects.has(ref) && !onScreen.has(ref)) add(`'${ref}' isn't on screen at this point`, [...loc, 'target'], step.id, 'warning');
      };
      const after = new Set(onScreen);
      if (step.do === 'show' || step.do === 'add') {
        for (const ref of asList(step.target)) {
          if (onScreen.has(ref)) add(`'${ref}' is already on screen`, [...loc, 'target'], step.id, 'warning');
          for (const m of members(ref)) after.add(m);
        }
      } else if (step.do === 'hide' || step.do === 'remove') {
        for (const ref of asList(step.target)) {
          warnAbsent(ref);
          for (const m of members(ref)) after.delete(m);
        }
      } else if (step.do === 'clear') {
        after.clear();
      } else if (step.do === 'transform') {
        warnAbsent(step.target);
        if (!step.keep) for (const m of members(step.target)) after.delete(m);
        for (const m of members(step.into)) after.add(m);
      } else if (step.do === 'change' || step.do === 'highlight') {
        warnAbsent(step.target);
      }
      onScreen = after;
    });
    void ids;
  });
  return out;
}

/** LaTeX which wouldn't compile, found the way a render would find it. */
export function latexProblems(doc, sceneIndex) {
  const scene = doc.scenes[sceneIndex];
  const out = [];
  const texFields = { tex: ['tex'], dot: ['label'], vector: ['label'], brace: ['label'], graph: ['label'], axes: ['x_label', 'y_label'] };
  (scene?.objects ?? []).forEach((obj, i) => {
    for (const field of texFields[obj.type] ?? []) {
      const tex = obj[field];
      if (typeof tex !== 'string') continue;
      const message = texError(tex);
      if (message) {
        out.push(problem(message, ['scenes', sceneIndex, 'objects', i, field], doc, 'error', { sceneId: scene.id, itemId: obj.id }));
      }
    }
  });
  return out;
}

function texError(tex) {
  let depth = 0;
  for (let i = 0; i < tex.length; i += 1) {
    const c = tex[i];
    if (c === '\\') {
      i += 1;
      continue;
    }
    if (c === '{') depth += 1;
    if (c === '}') {
      depth -= 1;
      if (depth < 0) return "LaTeX couldn't compile this formula: a } has no { to match it";
    }
  }
  if (depth > 0) return "LaTeX couldn't compile this formula: a { is never closed with }";
  if (tex.includes('$')) return "LaTeX couldn't compile this formula: leave out the $ signs, it is already math";
  const bad = /\\(undefinedcommand|badmacro|oops)\b/.exec(tex);
  if (bad) return `LaTeX couldn't compile this formula: it doesn't know the command \\${bad[1]}`;
  return null;
}
