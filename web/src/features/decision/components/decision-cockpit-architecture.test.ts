// @ts-nocheck -- Node built-ins are used only by this deterministic source audit.
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const COMPONENT_ROOT = dirname(fileURLToPath(import.meta.url));
const DECISION_COCKPIT_MODULES = [
  'automation-broker-evidence-sections.tsx',
  'automation-broker-status-sections.tsx',
  'automation-cockpit-panel.tsx',
  'automation-controlled-execution-section.tsx',
  'automation-reconciliation-section.tsx',
  'automation-review-sections.tsx',
  'daily-candidate-financial-preflight-panel.tsx',
  'daily-candidate-preflight-model.ts',
  'daily-trading-plan-panel.tsx',
  'decision-automation-model.ts',
  'decision-candidate-evidence-model.ts',
  'decision-cockpit-content.tsx',
  'decision-cockpit-page.tsx',
  'decision-cockpit-states.tsx',
  'decision-cockpit-workspace.tsx',
  'decision-execution-evidence-model.ts',
  'decision-execution-model.ts',
  'decision-gate-matrix-section.tsx',
  'decision-gate-model.ts',
  'decision-lane-panels.tsx',
  'decision-operator-action-labels.ts',
  'decision-signal-queue-panel.tsx',
  'decision-status-model.ts',
  'decision-trading-plan-model.ts',
  'decision-workflow-model.ts',
  'decision-workflow-panels.tsx',
  'use-decision-cockpit-workspace.ts',
] as const;

function source(fileName: string) {
  return readFileSync(resolve(COMPONENT_ROOT, fileName), 'utf8');
}

function topLevelFunctionLengths(fileName: string) {
  const lines = source(fileName).split('\n');
  return lines.flatMap((line, index) => {
    const match = line.match(/^(?:export\s+)?function\s+([\w$]+)/);
    if (!match) return [];
    const closingOffset = lines
      .slice(index + 1)
      .findIndex((item) => item === '}');
    if (closingOffset < 0) {
      throw new Error(
        `${fileName}:${index + 1} has no top-level closing brace`,
      );
    }
    return [
      {
        name: match[1],
        start: index + 1,
        lines: closingOffset + 2,
      },
    ];
  });
}

function localDependencies(fileName: string) {
  return [...source(fileName).matchAll(/from ['"]\.\/([^'"]+)['"]/g)]
    .map((match) => match[1])
    .map((dependency) =>
      DECISION_COCKPIT_MODULES.find((candidate) =>
        candidate.startsWith(`${dependency}.`),
      ),
    )
    .filter((dependency): dependency is string => Boolean(dependency));
}

describe('decision cockpit module architecture', () => {
  it('keeps every cockpit production module within the reviewable file budget', () => {
    const oversized = DECISION_COCKPIT_MODULES.flatMap((fileName) => {
      const lineCount = source(fileName).split('\n').length;
      return lineCount > 800 ? [`${fileName}: ${lineCount}`] : [];
    });

    expect(oversized).toEqual([]);
  });

  it('keeps every top-level cockpit function within the reviewable function budget', () => {
    const oversized = DECISION_COCKPIT_MODULES.flatMap((fileName) =>
      topLevelFunctionLengths(fileName)
        .filter((item) => item.lines > 350)
        .map(
          (item) =>
            `${fileName}:${item.start} ${item.name} (${item.lines} lines)`,
        ),
    );

    expect(oversized).toEqual([]);
  });

  it('keeps cockpit module dependencies acyclic', () => {
    const visiting = new Set<string>();
    const visited = new Set<string>();
    const cycles: string[] = [];

    function visit(fileName: string, path: string[]) {
      if (visiting.has(fileName)) {
        cycles.push([...path, fileName].join(' -> '));
        return;
      }
      if (visited.has(fileName)) return;
      visiting.add(fileName);
      for (const dependency of localDependencies(fileName)) {
        visit(dependency, [...path, fileName]);
      }
      visiting.delete(fileName);
      visited.add(fileName);
    }

    for (const fileName of DECISION_COCKPIT_MODULES) {
      visit(fileName, []);
    }

    expect(cycles).toEqual([]);
  });

  it('keeps the public entry and workspace focused on composition', () => {
    expect(source('decision-cockpit-page.tsx').trim()).toBe(
      "export { DecisionCockpitPage } from './decision-cockpit-workspace';",
    );

    const workspace = source('decision-cockpit-workspace.tsx');
    expect(workspace).toContain('useDecisionCockpitWorkspace');
    expect(workspace).toContain('<DecisionCockpitContent model={model} />');
    expect(workspace).not.toContain("from '../api'");
    expect(workspace).not.toContain("from '../../operations/api'");
  });
});
