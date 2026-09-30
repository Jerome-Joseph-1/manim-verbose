#!/usr/bin/env node
// A stand-in for the editor server (docs/editor/server-api.md), in memory, with no
// dependencies. Stills are SVG sketches of where objects would be; clips and exports are a
// tiny placeholder video; export jobs make progress over a few seconds.
//
//   node mock/server.mjs [--port 8790] [--static ../manim_verbose/editor/static] [--fixture demo|empty]
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
import { catalog, documentCode, timeline } from './codegen.mjs';

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
const STATIC_DIR = arg('static', process.env.MOCK_STATIC ?? '') ? path.resolve(arg('static', process.env.MOCK_STATIC)) : null;
const START_FIXTURE = arg('fixture', process.env.MOCK_FIXTURE ?? DEFAULT_FIXTURE);
const DEFAULT_LATENCY = Number(arg('latency', process.env.MOCK_LATENCY_MS ?? 120));
const DEFAULT_EXPORT_MS = Number(process.env.MOCK_EXPORT_MS ?? 4000);
const QUIET = process.argv.includes('--quiet') || process.env.MOCK_QUIET === '1';

const sessions = new Map();

function newSession(fixture = START_FIXTURE, document = null) {
  const doc = document ?? (FIXTURES[fixture] ?? FIXTURES[DEFAULT_FIXTURE])();
  return {
    doc: assignStepIds(doc),
    revision: 1,
    path: `/home/you/videos/${fixture === 'empty' ? 'untitled' : 'lesson'}.yaml`,
    stills: new Map(),
    stillSeq: 0,
    jobs: new Map(),
    config: { latency: DEFAULT_LATENCY, exportMs: DEFAULT_EXPORT_MS, failNext: null },
    stats: { stills: 0, saves: 0, superseded: 0 },
  };
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
  const data = typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': typeof body === 'string' || Buffer.isBuffer(body) ? headers['Content-Type'] ?? 'text/plain' : 'application/json',
    'Cache-Control': 'no-store',
    ...headers,
  });
  res.end(data);
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
        reject(new Error('bad json'));
      }
    });
    req.on('error', reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function hash(value) {
  return crypto.createHash('sha1').update(JSON.stringify(value)).digest('hex').slice(0, 16);
}

/** Validate a posted document; answers 422 itself and returns null when it can't be used. */
function usable(res, document, { forRender }) {
  const { readable, problems } = validator.check(document);
  if (!readable) {
    send(res, 422, { problems });
    return null;
  }
  if (forRender && problems.some((p) => p.severity === 'error')) {
    send(res, 422, { problems });
    return null;
  }
  return problems;
}

async function handleApi(req, res, url) {
  const s = session(req);
  const route = `${req.method} ${url.pathname}`;
  if (s.config.failNext && url.pathname.startsWith(s.config.failNext.path)) {
    const { status } = s.config.failNext;
    s.config.failNext = null;
    return send(res, status, { problems: [{ message: 'The mock was told to fail this request', severity: 'error', loc: [], path: '', scene_id: null, item_id: null }] });
  }
  switch (route) {
    case 'GET /api/health':
      return send(res, 200, { ok: true, version: 'mock' });
    case 'GET /api/schema':
      return send(res, 200, schema);
    case 'GET /api/catalog':
      return send(res, 200, catalog(schema));
    case 'GET /api/document': {
      const { problems } = validator.check(s.doc);
      return send(res, 200, { document: s.doc, path: s.path, revision: s.revision, problems });
    }
    case 'PUT /api/document': {
      const body = await readBody(req);
      if (body.base_revision !== s.revision) return send(res, 409, { document: s.doc, revision: s.revision });
      const { readable, problems } = validator.check(body.document);
      if (!readable) return send(res, 422, { problems });
      s.doc = assignStepIds(structuredClone(body.document));
      s.revision += 1;
      s.stats.saves += 1;
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
      if (usable(res, doc, { forRender: true }) === null) return undefined;
      const sceneIndex = doc.scenes.findIndex((sc) => sc.id === body.scene_id);
      if (sceneIndex < 0) {
        return send(res, 422, { problems: [{ message: `There's no scene called '${body.scene_id}'`, severity: 'error', loc: [], path: '', scene_id: null, item_id: null }] });
      }
      const texProblems = latexProblems(doc, sceneIndex);
      if (texProblems.length) return send(res, 422, { problems: texProblems });
      const scene = doc.scenes[sceneIndex];
      const width = Math.max(160, Math.min(3840, Math.round(Number(body.width) || 960)));
      const stepIndex = Number.isInteger(body.step_index) ? body.step_index : -1;
      const still = renderStill(doc, scene, stepIndex, width);
      const name = `${hash({ scene, settings: doc.settings, stepIndex, width })}.svg`;
      s.stills.set(name, still.svg);
      if (s.stills.size > 300) s.stills.delete(s.stills.keys().next().value);
      const { problems } = validator.check(doc);
      return send(res, 200, {
        image_url: `/files/stills/${name}`,
        width: still.width,
        height: still.height,
        objects: still.objects,
        problems: problems.filter((p) => p.scene_id === scene.id && p.severity === 'warning'),
      });
    }
    case 'POST /api/clip': {
      const body = await readBody(req);
      if (usable(res, body.document, { forRender: true }) === null) return undefined;
      await sleep(s.config.latency * 3);
      return send(res, 200, { video_url: `/files/clips/${hash(body)}.mp4` });
    }
    case 'POST /api/code': {
      const body = await readBody(req);
      if (usable(res, body.document, { forRender: false }) === null) return undefined;
      return send(res, 200, { code: documentCode(body.document, body.scene_id) });
    }
    case 'GET /api/timeline': {
      const scene = s.doc.scenes.find((sc) => sc.id === url.searchParams.get('scene_id'));
      if (!scene) return send(res, 404, { problems: [{ message: 'No such scene in the saved document', severity: 'error', loc: [], path: '', scene_id: null, item_id: null }] });
      return send(res, 200, timeline(scene));
    }
    case 'POST /api/export': {
      const body = await readBody(req);
      if (usable(res, body.document, { forRender: true }) === null) return undefined;
      const jobId = crypto.randomUUID();
      const job = { job_id: jobId, status: 'queued', progress: 0, message: 'Waiting to start', output_url: null, problems: [], started: Date.now() };
      s.jobs.set(jobId, job);
      runJob(s, job, body.document);
      return send(res, 202, { job_id: jobId });
    }
    default:
      break;
  }
  const jobMatch = /^\/api\/jobs\/([^/]+)$/.exec(url.pathname);
  if (jobMatch) {
    const job = s.jobs.get(decodeURIComponent(jobMatch[1]));
    if (!job) return send(res, 404, { problems: [{ message: 'No such job', severity: 'error', loc: [], path: '', scene_id: null, item_id: null }] });
    if (req.method === 'DELETE') {
      if (job.status === 'queued' || job.status === 'running') {
        job.status = 'cancelled';
        job.message = 'Cancelled';
      }
      return send(res, 200, { status: job.status });
    }
    const { started: _started, timer: _timer, ...visible } = job;
    return send(res, 200, visible);
  }
  return send(res, 404, { problems: [{ message: `No such endpoint: ${route}`, severity: 'error', loc: [], path: '', scene_id: null, item_id: null }] });
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
    job.progress = Math.min(1, tick / ticks);
    const scene = Math.min(scenes, Math.floor((tick / ticks) * scenes) + 1);
    job.message = tick >= ticks ? 'Joining scenes' : `Rendering scene ${scene} of ${scenes}`;
    if (tick >= ticks) {
      job.status = 'done';
      job.progress = 1;
      job.message = 'Done';
      job.output_url = `/files/exports/${job.job_id}.mp4`;
      return;
    }
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
      const next = newSession(body.fixture ?? START_FIXTURE, body.document ?? null);
      if (body.latency !== undefined) next.config.latency = body.latency;
      if (body.exportMs !== undefined) next.config.exportMs = body.exportMs;
      sessions.set(id, next);
      return send(res, 200, { ok: true, revision: next.revision });
    }
    case 'POST /__mock/external-edit': {
      // As if someone changed the file on disk, or saved from another tab
      const body = await readBody(req);
      s.doc = { ...s.doc, title: body.title ?? `${s.doc.title ?? 'Untitled'} (edited elsewhere)` };
      s.revision += 1;
      return send(res, 200, { revision: s.revision });
    }
    case 'POST /__mock/config': {
      const body = await readBody(req);
      Object.assign(s.config, body);
      return send(res, 200, s.config);
    }
    case 'GET /__mock/state':
      return send(res, 200, { document: s.doc, revision: s.revision, stats: s.stats, problems: validator.check(s.doc).problems });
    default:
      return send(res, 404, { error: 'unknown mock hook' });
  }
}

function handleFiles(req, res, url) {
  const s = session(req);
  const [, , kind, name] = url.pathname.split('/');
  if (kind === 'stills' && name && s.stills.has(name)) {
    return send(res, 200, s.stills.get(name), { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'max-age=3600' });
  }
  if ((kind === 'clips' || kind === 'exports') && name?.endsWith('.mp4')) {
    const headers = { 'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes' };
    if (kind === 'exports') headers['Content-Disposition'] = `attachment; filename="${s.doc.title ?? 'video'}.mp4"`;
    return send(res, 200, clipBytes, headers);
  }
  return send(res, 404, 'Not found');
}

const TYPES = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.json': 'application/json', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
};

function handleStatic(req, res, url) {
  if (!STATIC_DIR) return send(res, 404, 'The mock serves only the API; run Vite for the editor (npm run dev:mock)');
  let file = path.normalize(path.join(STATIC_DIR, decodeURIComponent(url.pathname)));
  if (!file.startsWith(STATIC_DIR)) return send(res, 403, 'Forbidden');
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(STATIC_DIR, 'index.html');
  if (!fs.existsSync(file)) return send(res, 404, 'Build the editor first: npm run build');
  const type = TYPES[path.extname(file)] ?? 'application/octet-stream';
  return send(res, 200, fs.readFileSync(file), { 'Content-Type': type, 'Cache-Control': 'no-cache' });
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://${req.headers.host ?? 'localhost'}`);
  try {
    if (url.pathname.startsWith('/api/')) await handleApi(req, res, url);
    else if (url.pathname.startsWith('/__mock/')) await handleMock(req, res, url);
    else if (url.pathname.startsWith('/files/')) handleFiles(req, res, url);
    else handleStatic(req, res, url);
    if (!QUIET) console.log(`${req.method} ${url.pathname} ${res.statusCode}`);
  } catch (error) {
    if (!QUIET) console.error(error);
    if (!res.headersSent) send(res, 500, { problems: [{ message: 'The mock server failed; see its log', severity: 'error', loc: [], path: '', scene_id: null, item_id: null }] });
  }
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Mock editor server on http://127.0.0.1:${PORT}${STATIC_DIR ? ` (serving ${STATIC_DIR})` : ''}`);
});
