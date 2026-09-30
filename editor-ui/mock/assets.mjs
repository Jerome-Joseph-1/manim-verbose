// Pictures uploaded to the mock server (POST /api/assets), kept in memory per session, with the
// same checks and names as manim_verbose/editor/assets.py: the kind decided by the content,
// the name made safe, the same picture keeping its name and another getting name-2.
import crypto from 'node:crypto';

const TYPES = { png: 'image/png', jpg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', svg: 'image/svg+xml' };

function problem(message) {
  return { message, severity: 'error', loc: ['file'], path: 'file', scene_id: null, item_id: null };
}

export function sniff(bytes) {
  const head = bytes.subarray(0, 12);
  if (head.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return 'png';
  if (head[0] === 0xff && head[1] === 0xd8 && head[2] === 0xff) return 'jpg';
  const text6 = head.subarray(0, 6).toString('latin1');
  if (text6 === 'GIF87a' || text6 === 'GIF89a') return 'gif';
  if (head.subarray(0, 4).toString('latin1') === 'RIFF' && head.subarray(8, 12).toString('latin1') === 'WEBP') return 'webp';
  const text = bytes.toString('utf8').replace(/^\uFEFF/, '');
  const start = text.trimStart().slice(0, 512).toLowerCase();
  if ((start.startsWith('<?xml') || start.startsWith('<svg') || start.startsWith('<!--')) && /<svg[\s>]/i.test(text) && !/<!doctype|<!entity/i.test(text) && /<\/svg>\s*$|\/>\s*$/i.test(text.trim())) {
    return 'svg';
  }
  return null;
}

export function safeStem(filename) {
  const base = String(filename ?? '').split(/[\\/]/).pop();
  const stem = base.replace(/^\.+/, '').includes('.') ? base.slice(0, base.lastIndexOf('.')) : base;
  const clean = stem.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^[-_]+|[-_]+$/g, '').slice(0, 48).replace(/[-_]+$/, '');
  return clean || 'picture';
}

export async function savePicture(raw, contentType, assets, maxBytes) {
  if (!/^multipart\/form-data/i.test(contentType)) return { status: 415, body: { problems: [problem("Send the picture as multipart/form-data, in a part called 'file'")] } };
  if (raw.length > maxBytes + 64 * 1024) return { status: 413, body: { problems: [problem('That file is too big to send')] } };
  let form;
  try {
    form = await new Request('http://mock/upload', { method: 'POST', headers: { 'content-type': contentType }, body: raw }).formData();
  } catch {
    return { status: 422, body: { problems: [problem("The upload couldn't be read")] } };
  }
  const file = form.get('file') ?? [...form.values()].find((v) => typeof v === 'object');
  if (!file || typeof file === 'string') return { status: 422, body: { problems: [problem('The upload has no file in it')] } };
  const bytes = Buffer.from(await file.arrayBuffer());
  if (bytes.length === 0) return { status: 422, body: { problems: [problem('That file is empty')] } };
  if (bytes.length > maxBytes) {
    return { status: 413, body: { problems: [problem(`That file is ${(bytes.length / 1048576).toFixed(1)} MB; pictures can be at most ${(maxBytes / 1048576).toFixed(1)} MB`)] } };
  }
  const kind = sniff(bytes);
  if (!kind) return { status: 415, body: { problems: [problem("That isn't a picture the editor can use: send a PNG, JPEG, GIF, WebP or SVG file")] } };
  const stem = safeStem(file.name);
  const digest = crypto.createHash('sha256').update(bytes).digest('hex');
  for (let n = 1; n < 1000; n += 1) {
    const path = `assets/${n === 1 ? stem : `${stem}-${n}`}.${kind}`;
    const existing = assets.get(path);
    if (existing && existing.digest !== digest) continue;
    if (!existing) assets.set(path, { bytes, type: TYPES[kind], digest });
    return { status: 200, body: { path, kind } };
  }
  return { status: 500, body: { problems: [problem('There are too many pictures of that name already')] } };
}
