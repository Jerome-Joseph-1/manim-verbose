/**
 * A small YAML reader and writer for the hosted editor's "Download .yaml" and "Open .yaml".
 *
 * The editor holds documents as JSON (see doc/types.ts); locally the Python server does the
 * YAML <-> JSON conversion, but the hosted editor has no server file, so a downloaded or
 * opened `.yaml` has to be converted in the browser. Rather than pull in a full YAML library,
 * this covers the subset scene files actually use — the same shapes the Python side writes
 * (canonical form: block maps and sequences, flow maps `{a: 1}` and flow sequences `[1, 2]`,
 * plain / single- / double-quoted scalars, and `|` / `>` block scalars) plus JSON, which is
 * valid YAML. It is deliberately strict about that subset and throws a clear error on anything
 * outside it, rather than guessing.
 *
 * `.json` files are handled by JSON.parse; only `.yaml` / `.yml` come through the parser here.
 */
import type { Json } from './types';

export class YamlError extends Error {
  constructor(message: string, line?: number) {
    super(line === undefined ? message : `${message} (line ${line + 1})`);
    this.name = 'YamlError';
  }
}

// --- Writing -----------------------------------------------------------------------------

const FLOW_WIDTH = 88;

/** A document (or any JSON value) as YAML text. Short scalar collections go on one line, the
 * way a person would write them; longer things get a line each. */
export function toYaml(value: Json): string {
  return emit(value, 0).join('\n') + '\n';
}

function emit(value: Json, indent: number): string[] {
  if (value === null || typeof value !== 'object') {
    return [emitScalarValue(value)];
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return ['[]'];
    const flow = tryFlow(value);
    if (flow !== null) return [flow];
    const pad = ' '.repeat(indent);
    const lines: string[] = [];
    for (const item of value) {
      const sub = emit(item, indent + 2);
      // `- ` sits where the first line of the item would; the rest keep the deeper indent
      lines.push(`${pad}- ${sub[0]!.trimStart()}`);
      for (let i = 1; i < sub.length; i += 1) lines.push(sub[i]!);
    }
    return lines;
  }
  const keys = Object.keys(value);
  if (keys.length === 0) return ['{}'];
  const flow = tryFlow(value);
  if (flow !== null) return [flow];
  const pad = ' '.repeat(indent);
  const lines: string[] = [];
  for (const key of keys) {
    const child = (value as Record<string, Json>)[key]!;
    const inline = child === null || typeof child !== 'object' || tryFlow(child) !== null;
    if (inline) {
      lines.push(`${pad}${key}: ${emit(child, indent + 2)[0]!.trimStart()}`);
    } else {
      lines.push(`${pad}${key}:`);
      for (const line of emit(child, indent + 2)) lines.push(line);
    }
  }
  return lines;
}

/** Whether a value fits on one line (all scalars, short enough), and its flow text if so. */
function tryFlow(value: Json): string | null {
  if (!isFlow(value)) return null;
  const text = flowText(value);
  return text.length <= FLOW_WIDTH ? text : null;
}

function isFlow(value: Json): boolean {
  if (value === null || typeof value !== 'object') {
    return typeof value !== 'string' || !value.includes('\n');
  }
  if (Array.isArray(value)) return value.every(isFlow);
  return Object.values(value).every(isFlow);
}

function flowText(value: Json): string {
  if (value === null || typeof value !== 'object') return scalar(value);
  if (Array.isArray(value)) return `[${value.map(flowText).join(', ')}]`;
  const parts = Object.entries(value).map(([k, v]) => `${k}: ${flowText(v)}`);
  return `{${parts.join(', ')}}`;
}

function scalar(value: Json): string {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '.nan';
  return quoteString(value as string);
}

/** Plain where it is safe, otherwise quoted; multiline strings become a `|` block. */
function quoteString(text: string): string {
  if (text.includes('\n')) return text; // caller emits block scalars; not reached in flow
  if (text === '') return "''";
  const needsQuote =
    /^[\s]|[\s]$/.test(text) ||
    /[:#\-?,[\]{}&*!|>'"%@`]/.test(text) ||
    /^(true|false|null|~|yes|no|on|off)$/i.test(text) ||
    /^[+-]?(\d|\.\d)/.test(text);
  if (!needsQuote) return text;
  if (!text.includes("'")) return `'${text}'`;
  return `"${text.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

// A scalar leaf in block context. Multiline strings become double-quoted with \n escapes,
// which keeps the writer simple and round-trips through the reader below.
function emitScalarValue(value: Json): string {
  if (typeof value === 'string' && value.includes('\n')) {
    return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n')}"`;
  }
  return scalar(value);
}

// --- Reading -----------------------------------------------------------------------------

interface Line {
  indent: number;
  text: string; // trimmed of indentation and inline comment, right-trimmed
  raw: string;
  no: number;
}

export function fromYaml(source: string): Json {
  const doc = stripDocumentMarkers(source);
  const lines = readLines(doc);
  if (lines.length === 0) return null;
  const [value, next] = parseNode(lines, 0, lines[0]!.indent);
  if (next < lines.length) {
    throw new YamlError('unexpected extra content', lines[next]!.no);
  }
  return value;
}

function stripDocumentMarkers(source: string): string {
  return source.replace(/^\uFEFF/, '');
}

function readLines(source: string): Line[] {
  const out: Line[] = [];
  const rawLines = source.split(/\r?\n/);
  let inBlock = false;
  let blockIndent = 0;
  for (let i = 0; i < rawLines.length; i += 1) {
    const raw = rawLines[i]!;
    if (raw.includes('\t')) {
      throw new YamlError('tabs are not allowed for indentation; use spaces', i);
    }
    const indent = raw.length - raw.trimStart().length;
    // Block-scalar body lines are kept verbatim (comments and blanks included); the parser
    // that started the block consumes them, so here we just avoid mangling them.
    if (inBlock) {
      if (raw.trim() === '' || indent > blockIndent) {
        out.push({ indent, text: raw.slice(Math.min(indent, blockIndent + 1)), raw, no: i });
        continue;
      }
      inBlock = false;
    }
    const trimmed = raw.trim();
    if (trimmed === '' || trimmed.startsWith('#')) continue; // blank or whole-line comment
    const text = stripInlineComment(raw.slice(indent));
    out.push({ indent, text: text.replace(/\s+$/, ''), raw, no: i });
    if (/(^|\s)[|>][+-]?\d*\s*$/.test(text) || /:\s*[|>][+-]?\d*\s*$/.test(text)) {
      inBlock = true;
      blockIndent = indent;
    }
  }
  return out;
}

/** Remove a ` # comment` that is outside quotes and flow. */
function stripInlineComment(text: string): string {
  let quote: string | null = null;
  let depth = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === quote && !(quote === '"' && text[i - 1] === '\\')) quote = null;
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    else if (c === '[' || c === '{') depth += 1;
    else if (c === ']' || c === '}') depth -= 1;
    else if (c === '#' && depth === 0 && (i === 0 || /\s/.test(text[i - 1]!))) return text.slice(0, i);
  }
  return text;
}

function parseNode(lines: Line[], start: number, indent: number): [Json, number] {
  const line = lines[start]!;
  if (line.text === '-' || line.text.startsWith('- ')) {
    return parseSequence(lines, start, indent);
  }
  if (isMappingLine(line.text)) {
    return parseMapping(lines, start, indent);
  }
  // A lone scalar (rare at top level, but valid)
  return [parseInline(line.text, line.no), start + 1];
}

function parseSequence(lines: Line[], start: number, indent: number): [Json[], number] {
  const items: Json[] = [];
  let i = start;
  while (i < lines.length) {
    const line = lines[i]!;
    if (line.indent !== indent || !(line.text === '-' || line.text.startsWith('- '))) break;
    const rest = line.text === '-' ? '' : line.text.slice(2);
    const next1 = i + 1 < lines.length ? lines[i + 1]! : null;
    if (rest === '') {
      // The item is a nested block on the following, more-indented lines
      if (next1 !== null && next1.indent > indent) {
        const [value, next] = parseNode(lines, i + 1, next1.indent);
        items.push(value);
        i = next;
      } else {
        items.push(null);
        i += 1;
      }
    } else if (isMappingLine(rest) || rest.startsWith('- ')) {
      // A block mapping (or nested sequence) that starts on the `- ` line and continues on
      // following lines indented to where `rest` begins.
      const contentIndent = indent + (line.text.length - rest.length);
      const virtual = makeVirtual(lines, i, contentIndent, rest);
      const [value, consumedVirtual] = parseNode(virtual.lines, 0, contentIndent);
      items.push(value);
      i = virtual.nextReal;
      void consumedVirtual;
    } else {
      items.push(parseInline(rest, line.no));
      i += 1;
    }
  }
  return [items, i];
}

/** Build a line list for a block that starts on a `- ` line: the text after `- ` as the first
 * line at `contentIndent`, then the following real lines that belong to it. */
function makeVirtual(lines: Line[], seqIndex: number, contentIndent: number, rest: string):
  { lines: Line[]; nextReal: number } {
  const anchor = lines[seqIndex]!;
  const first: Line = { indent: contentIndent, text: rest, raw: anchor.raw, no: anchor.no };
  const collected: Line[] = [first];
  let j = seqIndex + 1;
  while (j < lines.length && lines[j]!.indent >= contentIndent) {
    collected.push(lines[j]!);
    j += 1;
  }
  return { lines: collected, nextReal: j };
}

function parseMapping(lines: Line[], start: number, indent: number): [Record<string, Json>, number] {
  const map: Record<string, Json> = {};
  let i = start;
  while (i < lines.length) {
    const line = lines[i]!;
    if (line.indent !== indent || !isMappingLine(line.text)) break;
    const { key, value } = splitKey(line.text, line.no);
    if (isBlockScalarMarker(value)) {
      // A `|` or `>` block scalar, whose body is the following, more-indented lines
      const [text, next] = readBlockScalar(lines, i, indent, value);
      map[key] = text;
      i = next;
    } else if (value === '') {
      // A nested block (mapping or sequence) on the following lines, or null
      const nextLine = i + 1 < lines.length ? lines[i + 1]! : null;
      const isSeqLine = nextLine !== null && (nextLine.text.startsWith('- ') || nextLine.text === '-');
      // A block sequence may sit at the same indent as its key, or one deeper; a nested
      // mapping is always deeper.
      if (nextLine !== null && isSeqLine && nextLine.indent >= indent) {
        const [child, next] = parseSequence(lines, i + 1, nextLine.indent);
        map[key] = child;
        i = next;
      } else if (nextLine !== null && nextLine.indent > indent && isMappingLine(nextLine.text)) {
        const [child, next] = parseNode(lines, i + 1, nextLine.indent);
        map[key] = child;
        i = next;
      } else {
        map[key] = null;
        i += 1;
      }
    } else {
      map[key] = parseInline(value, line.no);
      i += 1;
    }
  }
  return [map, i];
}

function isBlockScalarMarker(text: string): boolean {
  return /^[|>][+-]?\d*$/.test(text);
}

function readBlockScalar(lines: Line[], keyIndex: number, keyIndent: number, marker: string): [string, number] {
  const folded = marker.startsWith('>');
  const bodyLines: string[] = [];
  let i = keyIndex + 1;
  let baseIndent = -1;
  while (i < lines.length) {
    const line = lines[i]!;
    if (line.raw.trim() === '') {
      bodyLines.push('');
      i += 1;
      continue;
    }
    if (line.indent <= keyIndent) break;
    if (baseIndent < 0) baseIndent = line.indent;
    bodyLines.push(line.raw.slice(baseIndent));
    i += 1;
  }
  while (bodyLines.length && bodyLines[bodyLines.length - 1] === '') bodyLines.pop();
  const text = folded ? foldLines(bodyLines) : bodyLines.join('\n');
  return [text, i];
}

function foldLines(lines: string[]): string {
  let out = '';
  for (let i = 0; i < lines.length; i += 1) {
    if (i > 0) out += lines[i] === '' || lines[i - 1] === '' ? '\n' : ' ';
    out += lines[i]!;
  }
  return out;
}

function isMappingLine(text: string): boolean {
  return colonIndex(text) >= 0;
}

/** The index of the `:` that separates a key from its value, ignoring `:` inside quotes and
 * flow collections and requiring it to be followed by a space or end of line. */
function colonIndex(text: string): number {
  let quote: string | null = null;
  let depth = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === quote && !(quote === '"' && text[i - 1] === '\\')) quote = null;
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    else if (c === '[' || c === '{') depth += 1;
    else if (c === ']' || c === '}') depth -= 1;
    else if (c === ':' && depth === 0 && (i + 1 >= text.length || text[i + 1] === ' ')) return i;
  }
  return -1;
}

function splitKey(text: string, no: number): { key: string; value: string } {
  const idx = colonIndex(text);
  if (idx < 0) throw new YamlError('expected a "key: value" line', no);
  const key = parseScalarToken(text.slice(0, idx).trim(), no);
  if (typeof key !== 'string') throw new YamlError('a key has to be text', no);
  return { key, value: text.slice(idx + 1).trim() };
}

// --- Scalars and flow --------------------------------------------------------------------

function parseInline(text: string, no: number): Json {
  const t = text.trim();
  if (t.startsWith('[') || t.startsWith('{')) return parseFlow(t, no);
  return parseScalarToken(t, no);
}

function parseScalarToken(token: string, no: number): Json {
  if (token === '' || token === '~' || token === 'null' || token === 'Null' || token === 'NULL') return null;
  if (token === 'true' || token === 'True' || token === 'TRUE') return true;
  if (token === 'false' || token === 'False' || token === 'FALSE') return false;
  if (token.startsWith('"')) return parseDoubleQuoted(token, no);
  if (token.startsWith("'")) return parseSingleQuoted(token, no);
  if (/^[+-]?\d+$/.test(token)) return parseInt(token, 10);
  if (/^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$/.test(token) && /[.eE]/.test(token)) {
    return Number(token);
  }
  if (token === '.nan' || token === '.NaN') return NaN as unknown as Json;
  if (token === '.inf' || token === '+.inf') return Infinity as unknown as Json;
  if (token === '-.inf') return -Infinity as unknown as Json;
  return token;
}

function parseDoubleQuoted(token: string, no: number): string {
  if (!token.endsWith('"') || token.length < 2) throw new YamlError('unterminated string', no);
  const inner = token.slice(1, -1);
  let out = '';
  for (let i = 0; i < inner.length; i += 1) {
    const c = inner[i];
    if (c === '\\') {
      const n = inner[i + 1];
      i += 1;
      out += n === 'n' ? '\n' : n === 't' ? '\t' : n === 'r' ? '\r' : n === '"' ? '"'
        : n === '\\' ? '\\' : n === '/' ? '/' : n === '0' ? '\0' : n ?? '';
    } else {
      out += c;
    }
  }
  return out;
}

function parseSingleQuoted(token: string, no: number): string {
  if (!token.endsWith("'") || token.length < 2) throw new YamlError('unterminated string', no);
  return token.slice(1, -1).replace(/''/g, "'");
}

/** Parse a single-line flow collection `[...]` or `{...}`. */
function parseFlow(text: string, no: number): Json {
  const [value, end] = parseFlowAt(text, 0, no);
  if (text.slice(end).trim() !== '') throw new YamlError('unexpected content after flow value', no);
  return value;
}

function parseFlowAt(text: string, start: number, no: number): [Json, number] {
  const i = skipSpace(text, start);
  if (text[i] === '[') return parseFlowSeq(text, i, no);
  if (text[i] === '{') return parseFlowMap(text, i, no);
  // A bare scalar inside flow: read up to , ] } (respecting quotes)
  const [token, end] = readFlowScalar(text, i);
  return [parseScalarToken(token.trim(), no), end];
}

function parseFlowSeq(text: string, start: number, no: number): [Json[], number] {
  const items: Json[] = [];
  let i = skipSpace(text, start + 1);
  if (text[i] === ']') return [items, i + 1];
  while (i < text.length) {
    const [value, end] = parseFlowAt(text, i, no);
    items.push(value);
    i = skipSpace(text, end);
    if (text[i] === ',') { i = skipSpace(text, i + 1); continue; }
    if (text[i] === ']') return [items, i + 1];
    throw new YamlError('expected "," or "]" in a flow sequence', no);
  }
  throw new YamlError('unterminated flow sequence', no);
}

function parseFlowMap(text: string, start: number, no: number): [Record<string, Json>, number] {
  const map: Record<string, Json> = {};
  let i = skipSpace(text, start + 1);
  if (text[i] === '}') return [map, i + 1];
  while (i < text.length) {
    const [rawKey, afterKey] = readFlowScalar(text, i, true);
    let j = skipSpace(text, afterKey);
    if (text[j] !== ':') throw new YamlError('expected ":" in a flow mapping', no);
    j = skipSpace(text, j + 1);
    const [value, end] = parseFlowAt(text, j, no);
    const key = parseScalarToken(rawKey.trim(), no);
    map[String(key)] = value;
    i = skipSpace(text, end);
    if (text[i] === ',') { i = skipSpace(text, i + 1); continue; }
    if (text[i] === '}') return [map, i + 1];
    throw new YamlError('expected "," or "}" in a flow mapping', no);
  }
  throw new YamlError('unterminated flow mapping', no);
}

function readFlowScalar(text: string, start: number, isKey = false): [string, number] {
  let i = start;
  if (text[i] === '"' || text[i] === "'") {
    const quote = text[i];
    i += 1;
    while (i < text.length) {
      if (text[i] === quote && !(quote === '"' && text[i - 1] === '\\')) {
        if (quote === "'" && text[i + 1] === "'") { i += 2; continue; }
        return [text.slice(start, i + 1), i + 1];
      }
      i += 1;
    }
    return [text.slice(start), i];
  }
  const stop = isKey ? /[:,\]}]/ : /[,\]}]/;
  while (i < text.length && !stop.test(text[i]!)) i += 1;
  return [text.slice(start, i), i];
}

function skipSpace(text: string, i: number): number {
  while (i < text.length && (text[i] === ' ' || text[i] === '\t')) i += 1;
  return i;
}
