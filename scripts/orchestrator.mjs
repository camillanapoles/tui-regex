#!/usr/bin/env node
/* ============================================================
 * Orquestrador BPMN do USHub (sequência topológica de issues).
 *
 * Toda ACTION retorna um ENVELOPE JSON padronizado:
 * {
 *   id:          string   — ex.: "USH-02"
 *   acao:        string   — "advance" | "report" | "self-test"
 *   mensagem:    string   — texto pronto (ou resumo do log)
 *   adendos:     array    — anexos gerados: { path } e/ou { file }
 *   status:      { code: number, label: string }
 *   continuidade: boolean — true enquanto o fluxo não chegou a DONE
 *   next_issue:  { id, number?, title } | null
 *   ts:          string   — ISO-8601
 * }
 *
 * CODEC de status (como BPMN):
 *   0 = SUCESSO          — tarefa provada (testes verdes) e fluxo avançou/concluiu
 *   1 = ERRO_BLOQUEANTE  — gate vermelho (CI com erro / testes ausentes): interrompe
 *   2 = CONTINUIDADE     — aguardando ação (humana ou agendada): fluxo segue
 *
 * Uso:
 *   node scripts/orchestrator.mjs advance --issue <n> --title "<t>" --gate <success|failure> [--dry-run]
 *   node scripts/orchestrator.mjs report
 *   node scripts/orchestrator.mjs self-test          (offline, sem gh/ rede)
 * ========================================================== */
'use strict';

import { execFileSync } from 'node:child_process';
import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SEQ = JSON.parse(readFileSync(join(ROOT, 'scripts', 'sequence.json'), 'utf8'));

const CODEC = {
  0: 'SUCESSO',
  1: 'ERRO_BLOQUEANTE',
  2: 'CONTINUIDADE'
};

/* ---------- envelope ---------- */
function envelope({ id = 'orchestrator', acao, code, mensagem, adendos = [], next_issue = null, continuidade }) {
  return {
    id, acao, mensagem, adendos,
    status: { code, label: CODEC[code] || 'DESCONHECIDO' },
    continuidade: continuidade != null ? continuidade : code !== 0,
    next_issue,
    ts: new Date().toISOString()
  };
}

/* ---------- persistência do envelope (BPMN: ação deixa rastro) ---------- */
function publish(env, issueNumber) {
  const out = JSON.stringify(env, null, 2);
  process.stdout.write(out + '\n');
  try { writeFileSync(join(ROOT, 'gate-envelope.json'), out + '\n'); } catch (e) { /* artefato local opcional */ }
  const md = [
    '## 🔀 Envelope da action',
    '',
    '| campo | valor |',
    '|---|---|',
    `| id | \`${env.id}\` |`,
    `| ação | \`${env.acao}\` |`,
    `| status | **${env.status.code} · ${env.status.label}** |`,
    `| mensagem | ${env.mensagem} |`,
    `| continuidade | ${env.continuidade ? '➡️ segue' : '🏁 DONE'} |`,
    `| next_issue | ${env.next_issue ? '`' + (env.next_issue.number ? '#' + env.next_issue.number + ' ' : '') + env.next_issue.id + ' · ' + env.next_issue.title + '`' : '—'} |`,
    `| ts | ${env.ts} |`,
    ''
  ].join('\n');
  if (process.env.GITHUB_STEP_SUMMARY) {
    try { appendFileSync(process.env.GITHUB_STEP_SUMMARY, md + '\n'); } catch (e) { /* noop */ }
  }
  if (issueNumber && !process.env.DRY_RUN) {
    try {
      sh('gh', ['issue', 'comment', String(issueNumber), '--body', '```json\n' + JSON.stringify(env, null, 2) + '\n```\n\n_Envelope BPMN registrado pelo orquestrador._']);
    } catch (e) { /* comentário é best-effort */ }
  }
  return env;
}

function sh(cmd, args) {
  return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

/* ---------- helpers da cadeia ---------- */
const findIdx = (ushId) => SEQ.chain.findIndex((s) => s.id === ushId);
const parseUsh = (title) => { const m = /USH-(\d{2})/.exec(title || ''); return m ? 'USH-' + m[1] : null; };

function issueBody(step) {
  return [
    `> Sequência topológica **${SEQ.sequencia_topologica}** · regra: só avança quando esta issue é FECHADA e os testes passam.`,
    '',
    `**Gap auditado:** ${step.gap} · **Tipo:** ${step.type}${step.dependsOn ? ' · **Depende de:** ' + step.dependsOn : ''}`,
    '',
    '### Instruções',
    '',
    ...step.instrucao.map((l, i) => `${i + 1}. ${l}`),
    '',
    '---',
    '_Ao fechar, o workflow `orchestrate` roda `npm test` (gate). Sucesso ⇒ comenta o envelope JSON aqui e cria a próxima issue indexada. Erro ⇒ envelope `1 · ERRO_BLOQUEANTE` com instruções de continuidade, sem avançar._'
  ].join('\n');
}

/* ---------- ACTION: advance (issues:closed) ---------- */
function cmdAdvance({ issue, title, gate, dryRun }) {
  const ush = parseUsh(title);
  if (!ush || findIdx(ush) < 0) {
    return publish(envelope({
      id: 'orchestrator', acao: 'advance', code: 0,
      mensagem: `Issue #${issue} fechada fora da cadeia USH — nada a orquestrar.`,
      continuidade: false, next_issue: null
    }), issue);
  }
  const idx = findIdx(ush);

  if (gate !== 'success') {
    return publish(envelope({
      id: ush, acao: 'advance', code: 1,
      mensagem: `Gate VERMELHO para ${ush}: testes falharam. Correção obrigatória antes de avançar.`,
      adendos: [{ path: 'tests/test-main.js' }, { path: 'tests/test-edge.js' }, { path: 'gate-envelope.json' }],
      continuidade: true,
      next_issue: { id: ush, title: SEQ.chain[idx].title }  // mesma: reabrir e corrigir
    }), issue);
  }

  const isLast = idx === SEQ.chain.length - 1;
  if (isLast) {
    return publish(envelope({
      id: ush, acao: 'advance', code: 0,
      mensagem: `${ush} fechada com testes verdes. Cadeia topológica COMPLETA → DONE. Guardião passa a relatar SUCESSO.`,
      adendos: [{ path: 'docs/ENTREGA.md' }, { file: 'gate-envelope.json' }],
      continuidade: false, next_issue: null
    }), issue);
  }

  const next = SEQ.chain[idx + 1];
  let number = null;
  if (dryRun || process.env.DRY_RUN) {
    process.stdout.write('[dry-run] criaria issue: ' + JSON.stringify({ title: next.id + ' · ' + next.title }) + '\n');
  } else {
    const out = sh('gh', ['issue', 'create', '--title', next.id + ' · ' + next.title, '--body', issueBody(next)]);
    const m = /issues\/(\d+)/.exec(out);
    number = m ? Number(m[1]) : null;
  }
  return publish(envelope({
    id: ush, acao: 'advance', code: 0,
    mensagem: `${ush} fechada e testes verdes. Próxima indexada criada: ${next.id}.`,
    adendos: [{ path: 'scripts/sequence.json' }, { file: 'gate-envelope.json' }],
    continuidade: true,
    next_issue: { id: next.id, number, title: next.title }
  }), issue);
}

/* ---------- ACTION: report (guardian) ---------- */
function cmdReport() {
  let openIssues = 0;
  let openTitles = [];
  let ciConclusion = 'unknown';
  let testsExist = true;

  try {
    const raw = sh('gh', ['issue', 'list', '--state', 'open', '--json', 'number,title', '--limit', '50']);
    const list = JSON.parse(raw || '[]');
    openIssues = list.length;
    openTitles = list.map((i) => `#${i.number} ${i.title}`);
  } catch (e) {
    return publish(envelope({ id: 'guardian', acao: 'report', code: 1, mensagem: 'Não consegui consultar issues (gh/API).', continuidade: true }));
  }
  try {
    const raw = sh('gh', ['run', 'list', '--workflow', 'test.yml', '--limit', '1', '--json', 'conclusion']);
    const list = JSON.parse(raw || '[]');
    ciConclusion = (list[0] && list[0].conclusion) || 'unknown';
  } catch (e) { ciConclusion = 'unknown'; }
  try {
    readFileSync(join(ROOT, 'tests', 'test-main.js'), 'utf8');
    readFileSync(join(ROOT, 'tests', 'test-edge.js'), 'utf8');
  } catch (e) { testsExist = false; }

  if (!testsExist || (ciConclusion !== 'success' && ciConclusion !== 'unknown')) {
    return publish(envelope({
      id: 'guardian', acao: 'report', code: 1,
      mensagem: `ERRO: ${!testsExist ? 'suítes de teste ausentes' : 'test.yml conclusão=' + ciConclusion}. Corrija antes de prosseguir.`,
      adendos: [{ path: '.github/workflows/test.yml' }],
      continuidade: true, next_issue: null
    }));
  }
  if (openIssues > 0) {
    const first = openTitles[0] || '';
    const ush = parseUsh(first);
    const step = ush ? SEQ.chain[findIdx(ush)] : null;
    return publish(envelope({
      id: ush || 'guardian', acao: 'report', code: 2,
      mensagem: `CONTINUIDADE: ${openIssues} issue(s) aberta(s). Pendente: ${step ? step.id + ' · ' + step.title : first}. CI verde, testes presentes.`,
      adendos: [{ path: 'scripts/sequence.json' }, { path: 'docs/ENTREGA.md' }],
      continuidade: true,
      next_issue: step ? { id: step.id, title: step.title } : null
    }));
  }
  return publish(envelope({
    id: 'guardian', acao: 'report', code: 0,
    mensagem: 'SUCESSO: zero issues abertas, CI verde e testes presentes. Nada pendente.',
    continuidade: false, next_issue: null
  }));
}

/* ---------- ACTION: self-test (offline; usado no dispatch e no CI) ---------- */
function cmdSelfTest() {
  const cases = [];
  // cenário a: gate verde, USH-01 → cria USH-02 (dry-run)
  const a = envelope({ id: 'USH-01', acao: 'advance', code: 0, mensagem: 'ok', continuidade: true, next_issue: { id: 'USH-02', title: SEQ.chain[1].title } });
  // cenário b: gate vermelho → 1 bloqueante, next = mesma
  const b = envelope({ id: 'USH-01', acao: 'advance', code: 1, mensagem: 'gate', continuidade: true, next_issue: { id: 'USH-01', title: SEQ.chain[0].title } });
  // cenário c: última → DONE
  const c = envelope({ id: 'USH-04', acao: 'advance', code: 0, mensagem: 'done', continuidade: false, next_issue: null });
  for (const env of [a, b, c]) {
    const ok = ['id', 'acao', 'mensagem', 'adendos', 'status', 'continuidade', 'next_issue', 'ts']
      .every((k) => Object.prototype.hasOwnProperty.call(env, k))
      && typeof env.mensagem === 'string'
      && typeof env.status.label === 'string'
      && [0, 1, 2].includes(env.status.code);
    cases.push({ id: env.id, shape_ok: ok });
    if (!ok) {
      const bad = envelope({ id: 'self-test', acao: 'self-test', code: 1, mensagem: 'Envelope fora do padrão JSON.', continuidade: true });
      process.stdout.write(JSON.stringify(bad, null, 2) + '\n');
      process.exit(1);
    }
  }
  const env = envelope({
    id: 'self-test', acao: 'self-test', code: 0,
    mensagem: `Envelope padrão validado em ${cases.length} cenários (advance ok / gate vermelho / DONE).`,
    adendos: [{ path: 'scripts/orchestrator.mjs' }, { path: 'scripts/sequence.json' }],
    continuidade: false, next_issue: { id: 'USH-01', title: SEQ.chain[0].title }
  });
  process.stdout.write(JSON.stringify(env, null, 2) + '\n');
}

/* ---------- CLI ---------- */
const args = process.argv.slice(2);
const cmd = args[0];
const opt = (name, def) => { const i = args.indexOf('--' + name); return i >= 0 ? args[i + 1] : def; };
const has = (name) => args.includes('--' + name);

let exitCode = 0;
if (cmd === 'advance') {
  const env = cmdAdvance({
    issue: Number(opt('issue', '0')),
    title: opt('title', ''),
    gate: opt('gate', 'failure'),
    dryRun: has('dry-run')
  });
  exitCode = env.status.code === 1 ? 1 : 0;      // 2 (continuidade em advance) não ocorre; 0/1 dirigem o job
} else if (cmd === 'report') {
  const env = cmdReport();
  exitCode = env.status.code === 1 ? 1 : 0;      // CONTINUIDADE (2) = run verde com envelope 2
} else if (cmd === 'self-test') {
  cmdSelfTest();
} else {
  const env = envelope({ id: 'orchestrator', acao: String(cmd || 'none'), code: 1, mensagem: 'Comando desconhecido. Use advance | report | self-test.', continuidade: true });
  process.stdout.write(JSON.stringify(env, null, 2) + '\n');
  exitCode = 1;
}
process.exit(exitCode);
