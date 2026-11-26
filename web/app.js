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

const preferred = { mode: 'workflow', effort: 'none' };
const MODES = ['workflow', 'agent'];
const EFFORTS = ['none', 'low', 'high', 'max'];
const EXAMPLES = [
  '乳腺癌的症状有哪些？',
  '高血压应该吃什么药？',
  '感冒需要做哪些检查？',
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
  return `${view.mode} · ${view.effort === 'none' ? '无推理' : `推理 ${view.effort}`}`;
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
  box.append(el('h2', null, '向医学知识图谱提问'));
  const setup = div('setup');
  setup.append(selectField('模式', MODES, preferred.mode, (value) => {
    preferred.mode = value;
    localStorage.setItem(MODE_KEY, value);
  }));
  setup.append(selectField('推理', EFFORTS, preferred.effort, (value) => {
    preferred.effort = value;
    localStorage.setItem(EFFORT_KEY, value);
  }));
  box.append(setup);
  const examples = div('examples');
  for (const question of EXAMPLES) {
    const button = el('button', null, question);
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
      span('tag', `推理 ${step.index + 1}`),
      span('count', `${step.text.length} 字`),
      span('snippet', oneLine(step.text)),
    );
    body.append(pre(step.text));
  } else {
    const result = step.result || {};
    const failed = typeof result.error === 'string';
    const rows = Array.isArray(result.rows) ? result.rows : [];
    summary.append(
      span('tag', `查询 ${step.index + 1}`),
      span(failed ? 'count fail' : 'count',
        failed ? '失败' : `${rows.length} 行${result.truncated ? ' · 已截断' : ''}`),
      span('snippet', firstLine(step.cypher)),
    );
    body.append(field('Cypher', pre(step.cypher)));
    body.append(field('参数', pre(JSON.stringify(step.parameters || {}, null, 2))));
    if (failed) body.append(div('failed', result.error));
    else body.append(field('结果', pre(JSON.stringify(rows, null, 2))));
  }

  details.append(summary, body);
  return details;
}

function renderSteps(steps) {
  const box = div('steps');
  for (const step of steps) box.append(renderStep(step));
  return box;
}

function renderTurn(turn) {
  const wrap = div('turn');
  wrap.append(div('question', turn.question));
  if (turn.steps && turn.steps.length) wrap.append(renderSteps(turn.steps));
  if (turn.error) wrap.append(div('failed', `本轮失败：${turn.error}`));
  else if (!turn.answer && turn.status === 'failed') wrap.append(div('failed', '本轮失败。'));
  else if (!turn.answer && turn.status === 'incomplete') {
    wrap.append(div('incomplete', '本轮未完成：已达到图谱查询上限。'));
  }
  if (turn.answer) wrap.append(div('answer', turn.answer));
  const usage = usageText(turn.usage);
  if (usage) wrap.append(div('usage', usage));
  return wrap;
}

function renderPending(pending) {
  const wrap = div('turn');
  wrap.append(div('question', pending.question));
  wrap.append(div('pending-line', '正在生成'));
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
  $('title').textContent = '新对话';
  $('meta').textContent = '';
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
  const steps = div('steps');
  const status = div('pending-line', '正在生成');
  wrap.append(div('question', question), steps, status);
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
  live.status.textContent = step.kind === 'query' ? '正在查询图谱' : '正在推演';
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

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem(THEME_KEY, theme);
}

function bind() {
  $('theme').addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });

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
  preferred.mode = localStorage.getItem(MODE_KEY) === 'agent' ? 'agent' : 'workflow';
  const storedEffort = localStorage.getItem(EFFORT_KEY);
  preferred.effort = EFFORTS.includes(storedEffort) ? storedEffort : 'none';

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
  const first = state.conversations[0];
  if (first) await openConversation(first.id);
  else resetToEmpty();
}

init();
