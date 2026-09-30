// Plausible stand-ins for /api/code, /api/timeline and /api/catalog.

const TEXT_LIKE = new Set(['text', 'tex', 'title', 'quote', 'bullets', 'matrix']);

export function defaultRunTime(step, objects) {
  if (typeof step.run_time === 'number') return step.run_time;
  const kinds = (Array.isArray(step.target) ? step.target : [step.target]).map((t) => objects.get(t)?.type);
  switch (step.do) {
    case 'show':
      return kinds.some((k) => TEXT_LIKE.has(k)) ? 2 : 1;
    case 'hide':
      return 1;
    case 'add':
    case 'remove':
      return 0.1;
    case 'clear':
      return 1;
    case 'transform':
      return 1.5;
    case 'change':
    case 'move':
    case 'highlight':
      return 1;
    case 'wait':
      return typeof step.duration === 'number' ? step.duration : 1;
    case 'camera':
    case 'apply_matrix':
      return 2;
    case 'together': {
      const inner = (step.steps ?? []).map((s) => defaultRunTime(s, objects));
      const lag = typeof step.lag === 'number' ? step.lag : 0;
      return Math.max(0, ...inner) + lag * Math.max(0, inner.length - 1);
    }
    default:
      return 1;
  }
}

export function timeline(scene) {
  const objects = new Map((scene.objects ?? []).map((o) => [o.id, o]));
  let t = 0;
  const steps = (scene.steps ?? []).map((step, index) => {
    const duration = defaultRunTime(step, objects);
    const entry = { step_id: step.id, index, start: Math.round(t * 1000) / 1000, duration };
    t += duration;
    return entry;
  });
  return { steps, duration: Math.round(t * 1000) / 1000 };
}

function className(id) {
  return id.split('_').filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join('') || 'Scene';
}

function py(value) {
  if (typeof value === 'string') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(py).join(', ')}]`;
  if (value === true) return 'True';
  if (value === false) return 'False';
  if (value === null) return 'None';
  if (typeof value === 'object') return `{${Object.entries(value).map(([k, v]) => `${JSON.stringify(k)}: ${py(v)}`).join(', ')}}`;
  return String(value);
}

const CLASSES = {
  text: 'Text', tex: 'Tex', title: 'Title', quote: 'Quote', bullets: 'BulletedList', matrix: 'Matrix',
  number_plane: 'NumberPlane', axes: 'Axes', axes_3d: 'ThreeDAxes', number_line: 'NumberLine', graph: 'FunctionGraph',
  dot: 'Dot', vector: 'Vector', line: 'Line', polygon: 'Polygon', circle: 'Circle', rectangle: 'Rectangle',
  square: 'Square', brace: 'Brace', box: 'SurroundingRectangle', image: 'ImageMobject', svg: 'SVGMobject', group: 'VGroup',
};

function objectLine(obj) {
  const { id, type, place, color, ...rest } = obj;
  const args = Object.entries(rest)
    .filter(([k]) => !['shown', 'z', 'opacity', 'scale', 'rotate', 'colors'].includes(k))
    .map(([k, v]) => (type === 'tex' && k === 'tex' ? `R${JSON.stringify(v)}` : `${k}=${py(v)}`));
  let expr = `${CLASSES[type] ?? 'Mobject'}(${args.join(', ')})`;
  if (color) expr += `.set_color(${/^#/.test(color) ? JSON.stringify(color) : color})`;
  if (place) {
    const p = typeof place === 'string' ? { edge: place } : Array.isArray(place) ? { at: place } : place;
    const kw = Object.entries(p).map(([k, v]) => (k === 'next_to' ? `next_to=${v}` : `${k}=${py(v)}`));
    expr = `place(${expr}, ${kw.join(', ')})`;
  }
  return `        ${id} = self.obj(${JSON.stringify(id)}, ${expr})`;
}

const ANIMATIONS = { show: 'Write', hide: 'FadeOut', add: 'self.add', remove: 'self.remove', transform: 'TransformMatchingTex' };

function stepLines(step, objects, indent = '            ') {
  const targets = Array.isArray(step.target) ? step.target : step.target ? [step.target] : [];
  const rt = defaultRunTime(step, objects);
  switch (step.do) {
    case 'show':
      return [`${indent}self.play(${targets.map((t) => `${TEXT_LIKE.has(objects.get(t)?.type) ? 'Write' : 'ShowCreation'}(${t})`).join(', ')}, run_time=${rt})`];
    case 'hide':
      return [`${indent}self.play(${targets.map((t) => `FadeOut(${t})`).join(', ')}, run_time=${rt})`];
    case 'add':
      return [`${indent}self.add(${targets.join(', ')})`];
    case 'remove':
      return [`${indent}self.remove(${targets.join(', ')})`];
    case 'clear':
      return [`${indent}self.play(*map(FadeOut, self.mobjects), run_time=${rt})`];
    case 'transform':
      return [`${indent}self.play(${step.keep ? 'TransformFromCopy' : ANIMATIONS.transform}(${step.target}, ${step.into}), run_time=${rt})`];
    case 'change':
      return [`${indent}self.play(${step.target}.animate.set(${Object.entries(step.set ?? {}).map(([k, v]) => `${k}=${py(v)}`).join(', ')}), run_time=${rt})`];
    case 'move':
      return [`${indent}self.play(${targets.map((t) => (step.by ? `${t}.animate.shift(${py(step.by)})` : `${t}.animate.move_to(${py(step.to)})`)).join(', ')}, run_time=${rt})`];
    case 'highlight':
      return [`${indent}self.play(Indicate(${step.target}${step.part ? `[${JSON.stringify(step.part)}]` : ''}), run_time=${rt})`];
    case 'wait':
      return [`${indent}self.wait(${rt})`];
    case 'camera':
      return [`${indent}self.play(self.frame.animate${step.zoom ? `.scale(1 / ${step.zoom})` : ''}${step.focus ? `.move_to(${step.focus})` : ''}, run_time=${rt})`];
    case 'apply_matrix':
      return [`${indent}self.play(ApplyMatrix(${py(step.matrix)}, VGroup(${targets.join(', ')})), run_time=${rt})`];
    case 'together':
      return [`${indent}self.play(`, ...(step.steps ?? []).map((s) => `${indent}    # ${s.do} ${Array.isArray(s.target) ? s.target.join(', ') : s.target ?? ''}`), `${indent})`];
    default:
      return [`${indent}pass`];
  }
}

export function documentCode(doc, sceneId) {
  const scenes = sceneId ? doc.scenes.filter((s) => s.id === sceneId) : doc.scenes;
  const lines = ['from manimlib import *', 'from manim_verbose.scenefile.runtime import *', ''];
  for (const scene of scenes) {
    const objects = new Map((scene.objects ?? []).map((o) => [o.id, o]));
    lines.push('', `class ${className(scene.id)}(DocScene):`);
    if (scene.title) lines.push(`    """${scene.title}"""`, '');
    lines.push('    def construct(self):');
    for (const obj of scene.objects ?? []) lines.push(objectLine(obj));
    if (!(scene.objects ?? []).length && !(scene.steps ?? []).length) lines.push('        pass');
    for (const step of scene.steps ?? []) {
      const caption = step.caption != null ? `, caption=${JSON.stringify(step.caption)}` : '';
      lines.push(`        with self.step(${JSON.stringify(step.id)}${caption}):`);
      lines.push(...stepLines(step, objects));
    }
  }
  return `${lines.join('\n')}\n`;
}

const OBJECT_TEMPLATES = {
  text: { text: 'Hello' },
  tex: { tex: 'e^{i\\pi} + 1 = 0' },
  title: { text: 'A title' },
  quote: { text: 'Mathematics is the art of giving the same name to different things.', author: 'Henri Poincaré' },
  bullets: { items: ['First point', 'Second point'] },
  matrix: { entries: [[1, 0], [0, 1]] },
  number_plane: {},
  axes: {},
  axes_3d: {},
  number_line: {},
  graph: { on: '', function: 'sin(x)' },
  dot: { point: [0, 0] },
  vector: { tip: [2, 1] },
  line: { start: [-2, 0], end: [2, 0] },
  polygon: { points: [[-1, -1], [1, -1], [0, 1]] },
  circle: { radius: 1 },
  rectangle: { width: 3, height: 2 },
  square: { side: 2 },
  brace: { target: '' },
  box: { target: '' },
  image: { path: 'picture.png' },
  svg: { path: 'drawing.svg' },
  group: { members: [] },
};

const STEP_TEMPLATES = {
  show: { target: '' },
  hide: { target: '' },
  add: { target: '' },
  remove: { target: '' },
  clear: {},
  transform: { target: '', into: '' },
  change: { target: '', set: { color: 'YELLOW' } },
  move: { target: '', by: [1, 0] },
  highlight: { target: '' },
  wait: { duration: 1 },
  camera: { zoom: 1.5 },
  apply_matrix: { target: '', matrix: [[1, 1], [0, 1]] },
  together: { steps: [{ do: 'show', target: '' }, { do: 'show', target: '' }] },
};

function firstParagraph(text) {
  return String(text ?? '').split(/\n\s*\n/)[0].replace(/\s*\n\s*/g, ' ').trim();
}

export function catalog(schema) {
  const defs = schema.$defs;
  const scene = defs.SceneSpec.properties;
  const objects = Object.entries(scene.objects.items.discriminator.mapping).map(([type, ref]) => {
    const def = defs[ref.replace('#/$defs/', '')];
    return {
      type,
      label: def['x-label'] ?? type,
      category: def['x-category'] ?? 'Other',
      description: firstParagraph(def.description),
      template: { type, ...(OBJECT_TEMPLATES[type] ?? {}) },
    };
  });
  const steps = Object.entries(scene.steps.items.discriminator.mapping).map(([name, ref]) => {
    const def = defs[ref.replace('#/$defs/', '')];
    return {
      do: name,
      label: def['x-label'] ?? name,
      description: firstParagraph(def.description),
      template: { do: name, ...(STEP_TEMPLATES[name] ?? {}) },
    };
  });
  return { objects, steps };
}
