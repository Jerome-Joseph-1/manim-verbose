/** Every problem in the document, errors first; clicking one goes to the field it is about. */
import { useMemo } from 'react';
import type { Document, Problem } from '../doc/types';
import { formatLoc } from '../doc/paths';
import { isRequestProblem, locateProblem, sortProblems } from '../lib/problems';
import { requestFocus, setFrameStep, useAllProblems, useEditor } from '../state/store';
import { Icon } from './Icon';

function describeWhere(problem: Problem, doc: Document | null): string {
  const target = locateProblem(problem, doc);
  const field = target.field.length ? ` › ${formatLoc(target.field)}` : '';
  switch (target.kind) {
    case 'document':
      return target.field.length ? `video settings${field}` : 'the whole video';
    case 'scene':
      return `scene ${target.sceneId ?? '?'}${field}`;
    case 'object':
      return `${target.sceneId ?? '?'} › ${target.itemId ?? 'object'}${field}`;
    case 'step': {
      const scene = doc?.scenes.find((s) => s.id === target.sceneId);
      const index = scene?.steps?.findIndex((s) => s.id === target.itemId) ?? -1;
      return `${target.sceneId ?? '?'} › ${index >= 0 ? `step ${index + 1}` : (target.itemId ?? 'step')}${field}`;
    }
  }
}

export function ProblemsPanel() {
  const all = useAllProblems();
  const open = useEditor((s) => s.problemsOpen);
  const doc = useEditor((s) => s.history?.present ?? null);
  const problems = useMemo(
    () => sortProblems(all.filter((p) => !isRequestProblem(p))),
    [all],
  );
  const errors = problems.filter((p) => p.severity === 'error').length;
  const warnings = problems.length - errors;

  const go = (problem: Problem) => {
    const target = locateProblem(problem, doc);
    if (target.kind === 'step' && target.sceneId && target.itemId) {
      const scene = doc?.scenes.find((s) => s.id === target.sceneId);
      if (scene?.steps?.some((s) => s.id === target.itemId)) setFrameStep(target.sceneId, target.itemId);
    }
    requestFocus({ kind: target.kind, sceneId: target.sceneId, itemId: target.itemId }, target.field);
  };

  return (
    <section className="problems" aria-label="Problems" data-testid="problems-panel">
      <button
        type="button"
        className="problems-header"
        aria-expanded={open}
        aria-controls="problems-list"
        onClick={() => useEditor.setState({ problemsOpen: !open })}
      >
        <Icon name={open ? 'down' : 'up'} />
        Problems
        <span className="counts">
          {problems.length === 0 ? (
            <span>None: everything checks out</span>
          ) : (
            <>
              {errors ? <span className="err">{errors} error{errors === 1 ? '' : 's'}</span> : null}
              {warnings ? <span className="warn">{warnings} warning{warnings === 1 ? '' : 's'}</span> : null}
            </>
          )}
        </span>
      </button>
      {open && problems.length ? (
        <ul className="problems-list" id="problems-list">
          {problems.map((p, i) => (
            <li key={`${p.path}-${p.message}-${i}`}>
              <button type="button" className="problem-item" onClick={() => go(p)} data-testid="problem-item">
                <span className={`sev ${p.severity}`}>{p.severity}</span>
                <span className="msg">{p.message}</span>
                <span className="where">{describeWhere(p, doc)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
