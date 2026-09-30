#!/usr/bin/env node
// A stand-in for the editor server (docs/editor/server-api.md), in memory, with no
// dependencies. Stills are SVG sketches of where objects would be; clips and exports are a
// tiny placeholder video; export jobs make progress over a few seconds.
//
//   node mock/server.mjs [--port 8790] [--static ../manim_verbose/editor/static] [--fixture demo|empty|eola|broken]
//
// Each browser session (cookie `mock_session`) gets its own document, so tests running in
// parallel don't see each other's edits. Test hooks live under /__mock/.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { FIXTURES, DEFAULT_FIXTURE } from './fixtures.mjs';
import { Validator, latexProblems, iterSteps } from './validate.mjs';
import { renderStill } from './layout.mjs';
import { layoutProblems } from './layoutcheck.mjs';
import { catalog, documentCode, timeline } from './codegen.mjs';
import { loadTemplates } from './templates.mjs';
import { savePicture } from './assets.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const schemaPath = path.resolve(here, '../../manim_verbose/scenefile/schema.json');
const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));
const validator = new Validator(schema);
const clipBytes = fs.readFileSync(path.join(here, 'assets/clip.mp4'));

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  if (i >= 0 && process.argv[i + 1]) return process.argv[i + 1];
  const eq = process.argv.find((a) => a.startsWith(`--${name}=`));
  return eq ? eq.split('=').slice(1).join('=') : fallback;
}

const PORT = Number(arg('port', process.env.MOCK_PORT ?? 8790));
const STATIC_ARG = arg('static', process.env.MOCK_STATIC ?? '');
const STATIC_DIR = STATIC_ARG ? path.resolve(STATIC_ARG) : null;
const START_FIXTURE = arg('fixture', process.env.MOCK_FIXTURE ?? DEFAULT_FIXTURE);
const DEFAULT_LATENCY = Number(arg('latency', process.env.MOCK_LATENCY_MS ?? 120));
const DEFAULT_EXPORT_MS = Number(process.env.MOCK_EXPORT_MS ?? 4000);
const QUIET = process.argv.includes('--quiet') || process.env.MOCK_QUIET === '1';
const MAX_PENDING_EXPORTS = 10;
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

const sessions = new Map();

function requestProblem(message, loc = [], sceneId = null) {
  return { message, severity: 'error', loc, path: loc.join('.'), scene_id: sceneId, item_id: null };
}

function newSession(fixture = START_FIXTURE, document = undefined) {
  const broken = fixture === 'broken';
  const doc = document !== undefined ? document : broken ? null : (FIXTURES[fixture] ?? FIXTURES[DEFAULT_FIXTURE])();
  return {
    doc: doc ? assignStepIds(doc) : null,
    // For a file which can't be read at all, as the real server reports it
    loadProblems: broken ? [requestProblem("This isn't valid YAML: found character '\\t' that cannot start any token (line 4, column 1)")] : [],
    revision: 1,
    path: `/home/you/videos/${fixture === 'empty' ? 'untitled' : 'lesson'}.yaml`,
    stills: new Map(),
    stillSeq: 0,
    jobs: new Map(),
    /** Pictures uploaded, by the path the document uses: { bytes, type }. */
    assets: new Map(),
    config: {
      latency: DEFAULT_LATENCY,
      exportMs: DEFAULT_EXPORT_MS,
      failNext: null,
      maxAssetBytes: 10 * 1024 * 1024,
      // Endpoints other work adds to the real server, which the editor has to do without
      layout: true,
      templates: true,
    },
    stats: { stills: 0, saves: 0, superseded: 0, puts: 0, layouts: 0 },
  };
}

const TEMPLATES = loadTemplates(path.join(here, 'templates'));

function readRaw(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

function sessionId(req) {
  const header = req.headers['x-mock-session'];
  if (typeof header === 'string' && header) return header;
  const cookie = req.headers.cookie ?? '';
  const match = /(?:^|;\s*)mock_session=([^;]+)/.exec(cookie);
  return match ? decodeURIComponent(match[1]) : 'default';
}

function session(req) {
  const id = sessionId(req);
  if (!sessions.has(id)) sessions.set(id, newSession());
  return sessions.get(id);
}

function assignStepIds(doc) {
  if (!doc || !Array.isArray(doc.scenes)) return doc;
  const taken = new Set();
  for (const scene of doc.scenes) for (const step of iterSteps(scene.steps)) if (step?.id) taken.add(step.id);
  for (const scene of doc.scenes) {
    let n = 0;
    for (const step of iterSteps(scene.steps)) {
      if (step && !step.id) {
        let candidate;
        do {
          n += 1;
          candidate = `${scene.id}_${n}`;
        } while (taken.has(candidate));
        step.id = candidate;
        taken.add(candidate);
      }
    }
  }
  return doc;
}

function send(res, status, body, headers = {}) {
  const raw = typeof body === 'string' || Buffer.isBuffer(body);
  res.writeHead(status, {
    'Content-Type': raw ? headers['Content-Type'] ?? 'text/plain' : 'application/json',
    'Cache-Control': 'no-store',
    ...headers,
  });
  res.end(raw ? body : JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8');
      if (!text) return resolve({});
      try {
        resolve(JSON.parse(text));
      } catch {
        reject(Object.assign(new Error('bad json'), { status: 422 }));
      }
    });
    req.on('error', reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function hash(value) {
  return crypto.createHash('sha1').update(JSON.stringify(value)).digest('hex').slice(0, 16);
}

/**
 * Check a posted document. Unreadable: 422. For rendering one scene, errors in that scene
 * or in no scene refuse it; errors elsewhere come back with a 200. For the whole document,
 * an error anywhere refuses. Returns the problems when it can go ahead, null when answered.
 */
function usable(res, document, { sceneId = null, whole = false } = {}) {
  if (document === null || typeof document !== 'object' || Array.isArray(document)) {
    send(res, 422, { problems: [requestProblem("'document' has to be a JSON object", ['document'])] });
    return null;
  }
  const { readable, problems } = validator.check(document);
  if (!readable) {
    send(res, 422, { problems });
    return null;
  }
  const blocking = problems.filter((p) => p.severity === 'error' && (whole || p.scene_id === sceneId || p.scene_id === null));
  if (blocking.length) {
    send(res, 422, { problems });
    return null;
  }
  return problems;
}

function sceneIndexOr422(res, document, sceneId) {
  const index = document.scenes.findIndex((sc) => sc.id === sceneId);
  if (index < 0) {
    send(res, 422, { problems: [requestProblem(`There's no scene called '${sceneId}'`, ['scene_id'])] });
  }
  return index;
}

function integerOr422(res, value, name, fallback) {
  if (value === undefined || value === null) return fallback;
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    send(res, 422, { problems: [requestProblem(`'${name}' has to be a whole number`, [name])] });
    return undefined;
  }
  return value;
}

async function handleApi(req, res, url) {
  const s = session(req);
  const route = `${req.method} ${url.pathname}`;
  if (s.config.failNext && url.pathname.startsWith(s.config.failNext.path)) {
    const { status } = s.config.failNext;
    s.config.failNext = null;
    return send(res, status, { problems: [requestProblem('The mock was told to fail this request')] });
  }
  switch (route) {
    case 'GET /api/health':
      return send(res, 200, { ok: true, version: 'mock' });
    case 'GET /api/schema':
      return send(res, 200, schema);
    case 'GET /api/catalog':
      return send(res, 200, catalog(schema));
    case 'GET /api/document': {
      if (s.doc === null) return send(res, 200, { document: null, path: s.path, revision: s.revision, problems: s.loadProblems });
      const { problems } = validator.check(s.doc);
      return send(res, 200, { document: s.doc, path: s.path, revision: s.revision, problems });
    }
    case 'PUT /api/document': {
      const body = await readBody(req);
      s.stats.puts += 1;
      if (body.base_revision !== s.revision) {
        const problems = s.doc ? validator.check(s.doc).problems : s.loadProblems;
        return send(res, 409, { problems, document: s.doc, revision: s.revision });
      }
      const { readable, problems } = validator.check(body.document);
      if (!readable) return send(res, 422, { problems });
      const next = assignStepIds(structuredClone(body.document));
      if (JSON.stringify(next) !== JSON.stringify(s.doc)) {
        s.doc = next;
        s.loadProblems = [];
        s.revision += 1;
        s.stats.saves += 1;
      }
      return send(res, 200, { revision: s.revision, problems, document: s.doc });
    }
    case 'POST /api/validate': {
      const body = await readBody(req);
      return send(res, 200, { problems: validator.check(body.document).problems });
    }
    case 'POST /api/still': {
      const body = await readBody(req);
      const seq = (s.stillSeq += 1);
      s.stats.stills += 1;
      await sleep(s.config.latency);
      if (seq !== s.stillSeq) {
        s.stats.superseded += 1;
        return send(res, 409, { superseded: true });
      }
      const doc = body.document;
      const problems = usable(res, doc, { sceneId: body.scene_id });
      if (problems === null) return undefined;
      const sceneIndex = sceneIndexOr422(res, doc, body.scene_id);
      if (sceneIndex < 0) return undefined;
      const scene = doc.scenes[sceneIndex];
      const stepIndex = integerOr422(res, body.step_index, 'step_index', -1);
      if (stepIndex === undefined) return undefined;
      if (stepIndex < -1 || stepIndex >= (scene.steps ?? []).length) {
        return send(res, 422, { problems: [requestProblem(`Scene '${scene.id}' has no step ${stepIndex}`, ['step_index'], scene.id)] });
      }
      const width = integerOr422(res, body.width, 'width', 960);
      if (width === undefined) return undefined;
      if (width < 64 || width > 3840) return send(res, 422, { problems: [requestProblem("'width' has to be from 64 to 3840 pixels", ['width'])] });
      const texProblems = latexProblems(doc, sceneIndex);
      if (texProblems.length) return send(res, 422, { problems: texProblems });
      const still = renderStill(doc, scene, stepIndex, width, { assets: s.assets });
      const name = `${hash({ scenes: doc.scenes.slice(0, sceneIndex + 1), settings: doc.settings, stepIndex, width, assets: [...s.assets.keys()] })}.svg`;
      s.stills.set(name, still.svg);
      if (s.stills.size > 300) s.stills.delete(s.stills.keys().next().value);
      return send(res, 200, {
        image_url: `/files/stills/${name}`, width: still.width, height: still.height, objects: still.objects, coordinate_systems: still.coordinateSystems, problems,
      });
    }
    case 'POST /api/layout': {
      if (!s.config.layout) return send(res, 404, { problems: [requestProblem(`No such endpoint: ${route}`)] });
      const body = await readBody(req);
      s.stats.layouts += 1;
      await sleep(s.config.latency / 2);
      const problems = usable(res, body.document, { sceneId: body.scene_id });
      if (problems === null) return undefined;
      const sceneIndex = sceneIndexOr422(res, body.document, body.scene_id);
      if (sceneIndex < 0) return undefined;
      return send(res, 200, { problems: layoutProblems(body.document, sceneIndex) });
    }
    case 'POST /api/assets': {
      const raw = await readRaw(req);
      const result = await savePicture(raw, req.headers['content-type'] ?? '', s.assets, s.config.maxAssetBytes);
      return send(res, result.status, result.body);
    }
    case 'GET /api/templates':
      if (!s.config.templates) return send(res, 404, { problems: [requestProblem(`No such endpoint: ${route}`)] });
      return send(res, 200, { templates: TEMPLATES.map(({ document: _document, ...summary }) => summary) });
    case 'POST /api/clip': {
      const body = await readBody(req);
      const problems = usable(res, body.document, { sceneId: body.scene_id });
      if (problems === null) return undefined;
      const sceneIndex = sceneIndexOr422(res, body.document, body.scene_id);
      if (sceneIndex < 0) return undefined;
      const texProblems = latexProblems(body.document, sceneIndex);
      if (texProblems.length) return send(res, 422, { problems: texProblems });
      await sleep(s.config.latency * 3);
      return send(res, 200, { video_url: `/files/clips/${hash(body)}.mp4`, problems });
    }
    case 'POST /api/code': {
      const body = await readBody(req);
      const problems = usable(res, body.document, { sceneId: body.scene_id ?? null, whole: !body.scene_id });
      if (problems === null) return undefined;
      if (body.scene_id && sceneIndexOr422(res, body.document, body.scene_id) < 0) return undefined;
      return send(res, 200, { code: documentCode(body.document, body.scene_id) });
    }
    case 'GET /api/timeline': {
      const sceneId = url.searchParams.get('scene_id');
      if (!sceneId) return send(res, 422, { problems: [requestProblem("'scene_id' is required", ['scene_id'])] });
      const scene = s.doc?.scenes.find((sc) => sc.id === sceneId);
      if (!scene) return send(res, 422, { problems: [requestProblem(`There's no scene called '${sceneId}' in the saved document`, ['scene_id'])] });
      return send(res, 200, { ...timeline(scene), revision: s.revision });
    }
    case 'POST /api/export': {
      const body = await readBody(req);
      if (usable(res, body.document, { whole: true }) === null) return undefined;
      const pending = [...s.jobs.values()].filter((j) => j.status === 'queued' || j.status === 'running').length;
      if (pending >= MAX_PENDING_EXPORTS) return send(res, 429, { problems: [requestProblem('Too many exports are waiting already; try again when one has finished')] });
      const jobId = crypto.randomUUID();
      const job = { job_id: jobId, status: 'queued', progress: 0, message: 'Waiting to start', output_url: null, problems: [] };
      s.jobs.set(jobId, job);
      runJob(s, job, body.document);
      return send(res, 202, { job_id: jobId });
    }
    default:
      break;
  }
  const templateMatch = /^\/api\/templates\/([^/]+)(\/thumbnail\.svg|\/apply)?$/.exec(url.pathname);
  if (templateMatch && s.config.templates) {
    const template = TEMPLATES.find((t) => t.name === decodeURIComponent(templateMatch[1]));
    if (!template) return send(res, 404, { problems: [requestProblem(`There's no template called '${decodeURIComponent(templateMatch[1])}'`, ['name'])] });
    const [, , rest] = templateMatch;
    if (!rest && req.method === 'GET') {
      const { thumbnailSvg: _svg, ...detail } = template;
      return send(res, 200, { ...detail, document: assignStepIds(structuredClone(template.document)), problems: validator.check(template.document).problems });
    }
    if (rest === '/thumbnail.svg' && req.method === 'GET') {
      return send(res, 200, template.thumbnailSvg, { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'no-cache' });
    }
    if (rest === '/apply' && req.method === 'POST') {
      const body = await readBody(req);
      if (typeof body.base_revision !== 'number') return send(res, 422, { problems: [requestProblem("'base_revision' has to be a whole number", ['base_revision'])] });
      if (body.base_revision !== s.revision) return send(res, 409, { problems: [], document: s.doc, revision: s.revision });
      s.doc = assignStepIds(structuredClone(template.document));
      s.revision += 1;
      s.stats.saves += 1;
      return send(res, 200, { revision: s.revision, problems: validator.check(s.doc).problems, document: s.doc });
    }
    return send(res, 405, { problems: [requestProblem(`${req.method} isn't allowed here`)] });
  }
  const jobMatch = /^\/api\/jobs\/([^/]+)$/.exec(url.pathname);
  if (jobMatch) {
    const job = s.jobs.get(decodeURIComponent(jobMatch[1]));
    if (!job) return send(res, 404, { problems: [requestProblem('There is no export job with that id')] });
    if (req.method === 'DELETE') {
      if (job.status === 'queued' || job.status === 'running') {
        job.status = 'cancelled';
        job.message = 'Cancelled';
      }
      return send(res, 200, publicJob(job));
    }
    if (req.method === 'GET') return send(res, 200, publicJob(job));
    return send(res, 405, { problems: [requestProblem(`${req.method} isn't allowed here`)] });
  }
  return send(res, 404, { problems: [requestProblem(`No such endpoint: ${route}`)] });
}

function publicJob(job) {
  const { timer: _timer, ...visible } = job;
  return visible;
}

function runJob(s, job, document) {
  const scenes = document.scenes.length;
  const ticks = 10;
  let tick = 0;
  const interval = Math.max(20, s.config.exportMs / ticks);
  const advance = () => {
    if (job.status === 'cancelled') return;
    tick += 1;
    job.status = 'running';
    if (tick >= ticks) {
      job.status = 'done';
      job.progress = 1;
      job.message = 'Done';
      job.output_url = `/files/exports/lesson-hd-${job.job_id.slice(0, 8)}.mp4`;
      return;
    }
    job.progress = Math.min(0.99, tick / ticks);
    const scene = Math.min(scenes, Math.floor((tick / ticks) * scenes) + 1);
    job.message = tick === ticks - 1 ? 'Joining scenes' : `Rendering scene ${scene} of ${scenes}`;
    job.timer = setTimeout(advance, interval);
  };
  job.timer = setTimeout(advance, interval / 2);
}

async function handleMock(req, res, url) {
  const id = sessionId(req);
  const s = session(req);
  switch (`${req.method} ${url.pathname}`) {
    case 'POST /__mock/reset': {
      const body = await readBody(req);
      const next = newSession(body.fixture ?? START_FIXTURE, body.document);
      if (body.latency !== undefined) next.config.latency = body.latency;
      if (body.exportMs !== undefined) next.config.exportMs = body.exportMs;
      sessions.set(id, next);
      return send(res, 200, { ok: true, revision: next.revision });
    }
    case 'POST /__mock/external-edit': {
      // As if someone changed the file on disk, or saved from another tab
      const body = await readBody(req);
      if (s.doc) s.doc = { ...s.doc, title: body.title ?? `${s.doc.title ?? 'Untitled'} (edited elsewhere)` };
      s.revision += 1;
      return send(res, 200, { revision: s.revision });
    }
    case 'POST /__mock/config': {
      const body = await readBody(req);
      Object.assign(s.config, body);
      return send(res, 200, s.config);
    }
    case 'GET /__mock/state':
      return send(res, 200, { document: s.doc, revision: s.revision, stats: s.stats, assets: [...s.assets.keys()], problems: s.doc ? validator.check(s.doc).problems : s.loadProblems });
    default:
      return send(res, 404, { problems: [requestProblem('Unknown mock hook')] });
  }
}

function handleFiles(req, res, url) {
  const s = session(req);
  const [, , kind, name] = url.pathname.split('/');
  if (kind === 'stills' && name && s.stills.has(name)) {
    return send(res, 200, s.stills.get(name), { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'max-age=31536000, immutable' });
  }
  if ((kind === 'clips' || kind === 'exports') && name?.endsWith('.mp4')) {
    const headers = { 'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes' };
    if (kind === 'exports') headers['Content-Disposition'] = `attachment; filename="${name}"`;
    return send(res, 200, clipBytes, headers);
  }
  return send(res, 404, { problems: [requestProblem('No such file')] });
}

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.json': 'application/json', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

function handleStatic(req, res, url) {
  if (!STATIC_DIR) return send(res, 404, 'The mock serves only the API; run Vite for the editor (npm run dev:mock)');
  let file = path.normalize(path.join(STATIC_DIR, decodeURIComponent(url.pathname)));
  if (!file.startsWith(STATIC_DIR)) return send(res, 403, 'Forbidden');
  const hasExtension = path.extname(url.pathname) !== '';
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    if (hasExtension) return send(res, 404, 'Not found');
    file = path.join(STATIC_DIR, 'index.html');
  }
  if (!fs.existsSync(file)) return send(res, 404, 'Build the editor first: npm run build');
  const type = TYPES[path.extname(file)] ?? 'application/octet-stream';
  return send(res, 200, fs.readFileSync(file), { 'Content-Type': type, 'Cache-Control': 'no-cache' });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
  try {
    // Like the real server: only requests addressed to this computer, against DNS rebinding
    if (!LOCAL_HOSTS.has(url.hostname) && url.hostname !== '::1') {
      send(res, 400, { problems: [requestProblem(`Requests have to be addressed to localhost, not ${url.hostname}`)] });
    } else if (url.pathname.startsWith('/api/')) await handleApi(req, res, url);
    else if (url.pathname.startsWith('/__mock/')) await handleMock(req, res, url);
    else if (url.pathname.startsWith('/files/')) handleFiles(req, res, url);
    else handleStatic(req, res, url);
    if (!QUIET) console.log(`${req.method} ${url.pathname} ${res.statusCode}`);
  } catch (error) {
    if (!QUIET) console.error(error);
    if (!res.headersSent) {
      const status = error?.status === 422 ? 422 : 500;
      send(res, status, { problems: [requestProblem(status === 422 ? 'The request body is not valid JSON' : 'The mock server failed; see its log')] });
    }
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Mock editor server on http://127.0.0.1:${PORT}${STATIC_DIR ? ` (serving ${STATIC_DIR})` : ''}`);
});
