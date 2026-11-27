const $ = (id) => document.getElementById(id);

const THEME_KEY = 'medical-kg-theme';
const MODE_KEY = 'medical-kg-mode';
const EFFORT_KEY = 'medical-kg-effort';

const state = {
  conversations: [],
  current: null,
  view: null,
  busy: false,
  pending: false,
  poll: null,
};

const preferred = { mode: 'agent', effort: 'none' };
const MODES = ['workflow', 'agent'];
const EFFORTS = ['none', 'low', 'high', 'max'];

/* 猜你想问：10 个图谱实测高覆盖医学热点问题 */
const HOT_QUESTIONS = [
  {
    question: '高血压有哪些常见并发症？平时忌吃什么食物？',
    topic: '心脑血管',
    heat: '99.8w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><path d="M10 16.8s-6-3.9-6-8.4a3.6 3.6 0 0 1 6-2.6 3.6 3.6 0 0 1 6 2.6c0 4.5-6 8.4-6 8.4Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M6.5 10h2l1.1-2.2 1.6 4.2 1.1-2h1.7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  },
  {
    question: '糖尿病的典型症状有哪些？日常宜吃什么调理？',
    topic: '内分泌代谢',
    heat: '96.4w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><path d="M10 3.2c2.8 3.6 5 6.3 5 9a5 5 0 1 1-10 0c0-2.7 2.2-5.4 5-9Z" stroke="currentColor" stroke-width="1.6"/><path d="M8.2 12.8a2.2 2.2 0 0 0 2.2 1.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  },
  {
    question: '怀疑冠心病一般需要做哪些诊断检查？',
    topic: '急重症筛查',
    heat: '92.1w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><path d="M2.5 10h3.2l1.8-4.5 2.8 9 2.1-6.2 1.4 1.7h3.7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  },
  {
    question: '乳腺癌的常见症状有哪些？应该挂哪个科室？',
    topic: '肿瘤防治',
    heat: '88.7w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><path d="M10 2.8l5.5 2.2v4.6c0 3.9-2.4 6.6-5.5 7.8-3.1-1.2-5.5-3.9-5.5-7.8V5L10 2.8Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M10 7v5M7.5 9.5h5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  },
  {
    question: '痛风患者忌吃什么食物？有哪些推荐食谱？',
    topic: '风湿膳食',
    heat: '85.3w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><path d="M15.5 4.5c-5.5 0-9.5 3.2-10.5 8.5 5.3-1 8.5-5 8.5-10.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M5 15c3.5-3.5 6.5-5.5 10.5-10.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  },
  {
    question: '肺炎有哪些症状表现？常用的治疗方式和药物有哪些？',
    topic: '呼吸内科',
    heat: '81.9w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><path d="M10 3.5v6.5M10 8c-2.2 0-5 1.8-5 6 0 1.4 1 2.2 2.3 2.2 1.4 0 2.2-.8 2.2-2.2V9.5M10 8c2.2 0 5 1.8 5 6 0 1.4-1 2.2-2.3 2.2-1.4 0-2.2-.8-2.2-2.2V9.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  },
  {
    question: '脂肪肝是怎么引起的？平时宜吃哪些食物？',
    topic: '消化肝病',
    heat: '78.5w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><ellipse cx="10" cy="10.2" rx="6.5" ry="4.8" stroke="currentColor" stroke-width="1.6"/><path d="M7.5 9.5h5M10 7.5v4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
  },
  {
    question: '长期失眠常用哪些药物？日常该如何预防？',
    topic: '神经睡眠',
    heat: '74.2w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><path d="M11.5 3.5a6 6 0 1 0 5 9.2A4.8 4.8 0 0 1 11.5 3.5Z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M14.5 4.5v2M13.5 5.5h2" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  },
  {
    question: '颈椎病会引起哪些症状？有哪些常见治疗方法？',
    topic: '骨科康复',
    heat: '70.6w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><rect x="6.5" y="3.5" width="7" height="3.2" rx="1.5" stroke="currentColor" stroke-width="1.5"/><rect x="6" y="8.4" width="8" height="3.2" rx="1.5" stroke="currentColor" stroke-width="1.5"/><rect x="6.5" y="13.3" width="7" height="3.2" rx="1.5" stroke="currentColor" stroke-width="1.5"/></svg>',
  },
  {
    question: '胃溃疡的常见病因是什么？平时饮食忌吃什么？',
    topic: '消化养护',
    heat: '67.4w 热度',
    icon: '<svg viewBox="0 0 20 20" fill="none"><path d="M6.2 7.5a3.8 3.8 0 0 1 7.6 0l-1.2 6.2a2.6 2.6 0 0 1-5.2 0L6.2 7.5Z" stroke="currentColor" stroke-width="1.6"/><path d="M7.5 10.5h5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
  },
];

const EXAMPLES = [
  '乳腺癌的症状有哪些？',
  '高血压常见的并发症有哪些？',
  '痛风患者忌吃什么食物？',
  '过敏性鼻炎常用哪些药？',
];

/* ---------- helpers ---------- */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const div = (className, text) => el('div', className, text);
const span = (className, text) => el('span', className, text);
const pre = (text) => el('pre', null, text);

function field(label, node) {
  const box = div('field');
  box.append(span('label', label), node);
  return box;
}

function oneLine(text, limit = 90) {
  const flat = String(text || '').replace(/\s+/g, ' ').trim();
  return flat.length > limit ? `${flat.slice(0, limit)}…` : flat;
}

function firstLine(text) {
  return oneLine(String(text || '').split('\n')[0]);
}

function compact(value) {
  if (value >= 1000) return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return String(value);
}

function usageText(usage) {
  if (!usage) return '';
  const parts = [];
  if (usage.elapsed_ms != null) parts.push(`耗时 ${(usage.elapsed_ms / 1000).toFixed(1)}s`);
  if (usage.prompt_tokens != null || usage.completion_tokens != null) {
    parts.push(`入 ${compact(usage.prompt_tokens || 0)} / 出 ${compact(usage.completion_tokens || 0)} tokens`);
  }
  if (usage.prompt_cache_hit_tokens) parts.push(`缓存命中 ${compact(usage.prompt_cache_hit_tokens)}`);
  return parts.join(' · ');
}

function metaText(view) {
  if (!view) return '';
  const modeLabel = view.mode === 'agent' ? 'AGENT 智能体' : 'WORKFLOW 流水线';
  return `${modeLabel} · ${view.effort === 'none' ? '极速直答' : `推理 ${view.effort.toUpperCase()}`}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  if (response.status === 204) return null;
  return response.json();
}

async function errorMessage(response) {
  try {
    const body = await response.json();
    if (typeof body.detail === 'string') return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).join('；');
  } catch (error) {
    /* fall through */
  }
  return `请求失败（${response.status}）`;
}

function scrollToBottom(force) {
  const thread = $('thread');
  const near = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 140;
  if (force || near) thread.scrollTop = thread.scrollHeight;
}

function autoGrow() {
  const input = $('input');
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}

/* ---------- 屏幕切换与「猜你想问」榜单渲染 ---------- */

function switchScreen(screen) {
  document.body.dataset.screen = screen;
  closeSidebar();
  if (screen === 'portal') {
    updatePortalResume();
    syncPortalModeButtons();
  }
}

function syncPortalModeButtons() {
  const wrap = $('portal-mode-switch');
  if (!wrap) return;
  for (const btn of wrap.querySelectorAll('button[data-mode]')) {
    btn.classList.toggle('active', btn.dataset.mode === preferred.mode);
  }
}

function updatePortalResume() {
  const btn = $('resume-qa');
  const text = $('resume-qa-text');
  if (!btn || !text) return;
  const count = state.conversations.length;
  if (count > 0) {
    btn.hidden = false;
    text.textContent = `继续历史互动会话（已有 ${count} 条记录）`;
  } else {
    btn.hidden = true;
  }
}

function renderHotList() {
  const list = $('hot-list');
  if (!list) return;
  list.replaceChildren();
  HOT_QUESTIONS.forEach((item, index) => {
    const rankNum = index + 1;
    const li = el('li', `hot-item${rankNum <= 3 ? ` top-${rankNum}` : ''}`);
    const btn = el('button', 'hot-item-btn');
    btn.type = 'button';

    const rank = span('hot-rank', String(rankNum).padStart(2, '0'));
    const catIcon = span('hot-cat-icon');
    catIcon.innerHTML = item.icon;

    const content = div('hot-content');
    const q = div('hot-question', item.question);
    const meta = div('hot-meta');
    meta.append(span('hot-topic', item.topic), span('hot-heat', item.heat));
    content.append(q, meta);

    const arrow = span('hot-arrow');
    arrow.innerHTML = '<svg viewBox="0 0 16 16" fill="none"><path d="M5.5 3.5L10 8l-4.5 4.5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    btn.append(rank, catIcon, content, arrow);
    btn.addEventListener('click', () => launchQuestionFromPortal(item.question));
    li.append(btn);
    list.append(li);
  });
}

async function launchQuestionFromPortal(question) {
  switchScreen('qa');
  if (state.busy || state.pending) return;
  resetToEmpty();
  const input = $('input');
  input.value = question;
  autoGrow();
  await send();
}

function selectField(label, options, value, onChange) {
  const wrap = el('label');
  wrap.append(el('span', null, label));
  const select = document.createElement('select');
  for (const option of options) {
    const item = el('option', null, option);
    item.value = option;
    select.append(item);
  }
  select.value = value;
  select.addEventListener('change', () => onChange(select.value));
  wrap.append(select);
  return wrap;
}

function emptyBox() {
  const box = div('empty');
  box.append(el('span', 'empty-mark'));
  box.append(el('h2', null, '向医学知识图谱发起提问'));
  box.append(el('p', 'empty-sub', '实时编写参数化 Cypher 检索 4.4 万医学实体，支持追问症状、检查、用药与膳食宜忌'));
  const setup = div('setup');
  setup.append(selectField('引擎模式', MODES, preferred.mode, (value) => {
    preferred.mode = value;
    localStorage.setItem(MODE_KEY, value);
    syncPortalModeButtons();
  }));
  setup.append(selectField('推理深度', EFFORTS, preferred.effort, (value) => {
    preferred.effort = value;
    localStorage.setItem(EFFORT_KEY, value);
  }));
  box.append(setup);
  const examples = div('examples');
  for (const question of EXAMPLES) {
    const button = el('button', null, `✦ ${question}`);
    button.type = 'button';
    button.dataset.question = question;
    examples.append(button);
  }
  box.append(examples);
  return box;
}

function removeEmpty() {
  document.querySelector('#thread-inner .empty')?.remove();
}

/* ---------- rendering ---------- */

function renderStep(step) {
  const details = el('details', 'step');
  const summary = el('summary');
  const body = div('step-body');

  if (step.kind === 'reasoning') {
    summary.append(
      span('tag', `思考推演 ${step.index + 1}`),
      span('count', `${step.text.length} 字`),
      span('snippet', oneLine(step.text)),
    );
    body.append(pre(step.text));
  } else {
    const result = step.result || {};
    const failed = typeof result.error === 'string';
    const rows = Array.isArray(result.rows) ? result.rows : [];
    summary.append(
      span('tag', `图谱查询 ${step.index + 1}`),
      span(failed ? 'count fail' : 'count',
        failed ? '查询失败' : `命中 ${rows.length} 行${result.truncated ? ' · 已截断' : ''}`),
      span('snippet', firstLine(step.cypher)),
    );
    body.append(field('Cypher 查询语句', pre(step.cypher)));
    body.append(field('绑定参数', pre(JSON.stringify(step.parameters || {}, null, 2))));
    if (failed) body.append(div('failed', result.error));
    else body.append(field('Neo4j 图谱证据', pre(JSON.stringify(rows, null, 2))));
  }

  details.append(summary, body);
  return details;
}

function renderSteps(steps) {
  const box = div('steps');
  for (const step of steps) box.append(renderStep(step));
  return box;
}

function assistantHeader() {
  const head = div('assistant-head');
  head.append(span('assistant-avatar', '+'), span(null, 'MedKG 图谱智能助手'));
  return head;
}

function renderTurn(turn) {
  const wrap = div('turn');
  wrap.append(div('question', turn.question));

  const card = div('assistant-card');
  card.append(assistantHeader());
  if (turn.steps && turn.steps.length) card.append(renderSteps(turn.steps));
  if (turn.error) card.append(div('failed', `本轮失败：${turn.error}`));
  else if (!turn.answer && turn.status === 'failed') card.append(div('failed', '本轮失败。'));
  else if (!turn.answer && turn.status === 'incomplete') {
    card.append(div('incomplete', '本轮未完成：已达到图谱查询上限。'));
  }
  if (turn.answer) card.append(div('answer', turn.answer));
  const usage = usageText(turn.usage);
  if (usage) card.append(div('usage', usage));

  wrap.append(card);
  return wrap;
}

function renderPending(pending) {
  const wrap = div('turn');
  wrap.append(div('question', pending.question));
  const card = div('assistant-card');
  card.append(assistantHeader(), div('pending-line', '正在检索医学知识图谱并生成解答'));
  wrap.append(card);
  return wrap;
}

function renderList() {
  const history = $('history');
  history.replaceChildren();
  for (const conversation of state.conversations) {
    const item = div(`history-item${conversation.id === state.current ? ' active' : ''}`);
    const open = el('button', 'open', conversation.title);
    open.type = 'button';
    open.title = conversation.title;
    open.addEventListener('click', () => {
      closeSidebar();
      openConversation(conversation.id);
    });
    const remove = el('button', 'remove', '×');
    remove.type = 'button';
    remove.setAttribute('aria-label', `删除 ${conversation.title}`);
    remove.addEventListener('click', (event) => {
      event.stopPropagation();
      removeConversation(conversation.id, conversation.title);
    });
    item.append(open, remove);
    history.append(item);
  }
  updatePortalResume();
}

function renderConversation() {
  const view = state.view;
  if (!view) {
    resetToEmpty();
    return;
  }
  const thread = $('thread');
  const near = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 140;
  $('title').textContent = view.title;
  $('meta').textContent = metaText(view);
  state.pending = Boolean(view.pending);
  const inner = $('thread-inner');
  inner.replaceChildren();
  if (!view.turns.length) inner.append(emptyBox());
  for (const turn of view.turns) inner.append(renderTurn(turn));
  if (state.pending) inner.append(renderPending(view.pending));
  updateComposer();
  if (near) scrollToBottom(true);
  clearTimeout(state.poll);
  if (state.pending) schedulePoll();
}

function resetToEmpty() {
  state.current = null;
  state.view = null;
  state.pending = false;
  clearTimeout(state.poll);
  $('title').textContent = '新建医学问答';
  $('meta').textContent = `${preferred.mode.toUpperCase()} 准备就绪`;
  $('thread-inner').replaceChildren(emptyBox());
  updateComposer();
  renderList();
}

/* ---------- data ---------- */

async function refreshList() {
  try {
    const data = await api('/api/conversations');
    state.conversations = data.conversations;
  } catch (error) {
    return;
  }
  if (state.current && !state.conversations.some((item) => item.id === state.current)) {
    state.current = null;
    state.view = null;
  }
  renderList();
  const current = state.conversations.find((item) => item.id === state.current);
  if (current) $('title').textContent = current.title;
}

async function openConversation(id) {
  try {
    const data = await api(`/api/conversations/${id}`);
    state.current = id;
    state.view = data.conversation;
    renderConversation();
    renderList();
  } catch (error) {
    showError(error.message);
  }
}

async function createConversation() {
  const data = await api('/api/conversations', {
    method: 'POST',
    body: JSON.stringify({ mode: preferred.mode, effort: preferred.effort }),
  });
  state.current = data.conversation.id;
  state.view = { ...data.conversation, turns: [], resumable: true, resume_error: null };
  $('title').textContent = state.view.title;
  $('meta').textContent = metaText(state.view);
  $('thread-inner').replaceChildren();
  await refreshList();
  return state.current;
}

async function removeConversation(id, title) {
  if (!confirm(`删除「${title}」？此操作不可恢复。`)) return;
  try {
    await api(`/api/conversations/${id}`, { method: 'DELETE' });
  } catch (error) {
    showError(error.message);
    return;
  }
  if (state.current === id) {
    state.current = null;
    state.view = null;
  }
  await refreshList();
  if (!state.current && state.conversations.length) await openConversation(state.conversations[0].id);
  else if (!state.current) resetToEmpty();
}

function schedulePoll() {
  clearTimeout(state.poll);
  state.poll = setTimeout(async () => {
    const id = state.current;
    if (!id) return;
    try {
      const data = await api(`/api/conversations/${id}`);
      if (state.current !== id) return;
      state.view = data.conversation;
      renderConversation();
      await refreshList();
    } catch (error) {
      state.pending = false;
      updateComposer();
    }
  }, 1200);
}

/* ---------- streaming ---------- */

function startLive(question) {
  const wrap = div('turn');
  const card = div('assistant-card');
  const steps = div('steps');
  const status = div('pending-line', '正在连接图谱引擎规划查询');
  card.append(assistantHeader(), steps, status);
  wrap.append(div('question', question), card);
  $('thread-inner').append(wrap);
  scrollToBottom(true);
  return {
    wrap,
    steps,
    status,
    fail(message) {
      if (this.status.isConnected) this.status.replaceWith(div('failed', message));
    },
  };
}

function appendLiveStep(live, step) {
  live.steps.append(renderStep(step));
  live.status.textContent = step.kind === 'query' ? '正在执行只读 Neo4j 图谱查询并汇总答案' : '正在进行医学图谱推演';
  scrollToBottom(true);
}

function finishLive(live, turn, id) {
  const rendered = renderTurn(turn);
  if (live.wrap.isConnected) live.wrap.replaceWith(rendered);
  if (state.current === id && state.view && !state.view.turns.includes(turn)) state.view.turns.push(turn);
  scrollToBottom(true);
}

function showError(message) {
  const wrap = div('turn');
  wrap.append(div('failed', message));
  $('thread-inner').append(wrap);
  scrollToBottom(true);
}

async function streamTurn(id, question, handlers) {
  const response = await fetch(`/api/conversations/${id}/turns`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  if (!response.ok) throw new Error(await errorMessage(response));
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut;
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const event = parseBlock(block);
      if (event && handlers[event.type]) handlers[event.type](event.data);
    }
  }
}

function parseBlock(block) {
  let type = 'message';
  const data = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) type = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try {
    return { type, data: JSON.parse(data.join('\n')) };
  } catch (error) {
    return null;
  }
}

async function send() {
  const input = $('input');
  const question = input.value.trim();
  if (!question || state.busy || state.pending) return;

  let id = state.current;
  let live = null;
  state.busy = true;
  updateComposer();
  try {
    if (!id) id = await createConversation();
    removeEmpty();
    clearTimeout(state.poll);
    input.value = '';
    autoGrow();
    live = startLive(question);
    await streamTurn(id, question, {
      step: (step) => appendLiveStep(live, step),
      turn: (turn) => finishLive(live, turn, id),
      error: (payload) => live.fail(payload.message),
    });
  } catch (error) {
    if (live && live.wrap.isConnected) live.fail(error.message);
    else showError(error.message);
  } finally {
    state.busy = false;
    updateComposer();
    await refreshList();
  }
}

/* ---------- ui wiring ---------- */

function updateComposer() {
  const locked = state.busy || state.pending;
  $('input').disabled = locked;
  $('send').disabled = locked;
}

function closeSidebar() {
  document.body.classList.remove('sidebar-open');
}

function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem(THEME_KEY, next);
}

function bind() {
  $('theme').addEventListener('click', toggleTheme);
  $('portal-theme').addEventListener('click', toggleTheme);

  $('portal-mode-switch').addEventListener('click', (event) => {
    const btn = event.target.closest('button[data-mode]');
    if (!btn) return;
    preferred.mode = btn.dataset.mode;
    localStorage.setItem(MODE_KEY, preferred.mode);
    syncPortalModeButtons();
  });

  $('enter-qa').addEventListener('click', () => {
    switchScreen('qa');
    resetToEmpty();
    $('input').focus();
  });

  $('resume-qa').addEventListener('click', async () => {
    switchScreen('qa');
    if (state.conversations.length) {
      await openConversation(state.conversations[0].id);
    } else {
      resetToEmpty();
    }
  });

  $('back-portal').addEventListener('click', () => switchScreen('portal'));
  $('header-home').addEventListener('click', () => switchScreen('portal'));

  $('new').addEventListener('click', () => {
    resetToEmpty();
    closeSidebar();
    $('input').focus();
  });

  $('composer').addEventListener('submit', (event) => {
    event.preventDefault();
    send();
  });

  let composing = false;
  const input = $('input');
  input.addEventListener('compositionstart', () => { composing = true; });
  input.addEventListener('compositionend', () => { composing = false; });
  input.addEventListener('input', autoGrow);
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !composing) {
      event.preventDefault();
      $('composer').requestSubmit();
    }
  });

  $('menu').addEventListener('click', () => document.body.classList.toggle('sidebar-open'));

  $('thread-inner').addEventListener('click', (event) => {
    const example = event.target.closest('[data-question]');
    if (!example) return;
    input.value = example.dataset.question;
    autoGrow();
    input.focus();
  });
}

async function init() {
  document.documentElement.dataset.theme = localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light';
  const storedMode = localStorage.getItem(MODE_KEY);
  preferred.mode = MODES.includes(storedMode) ? storedMode : 'agent';
  const storedEffort = localStorage.getItem(EFFORT_KEY);
  preferred.effort = EFFORTS.includes(storedEffort) ? storedEffort : 'none';

  renderHotList();
  syncPortalModeButtons();
  bind();
  updateComposer();
  await refreshList();
  try {
    const config = await api('/api/config');
    if (!EFFORTS.includes(storedEffort) && EFFORTS.includes(config.default_effort)) {
      preferred.effort = config.default_effort;
    }
  } catch (error) {
    /* keep the select at none */
  }

  // 预渲染后台工作区状态，同时默认停留在第一屏门户进入界面
  const first = state.conversations[0];
  if (first) await openConversation(first.id);
  else resetToEmpty();
  switchScreen('portal');
}

init();
