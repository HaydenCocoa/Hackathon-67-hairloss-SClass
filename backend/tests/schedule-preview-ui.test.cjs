// Run with NODE_PATH pointing to a local jsdom installation; see backend docs.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM, CookieJar } = require('jsdom');

const assets = path.join(__dirname, '../app/scheduling/development');
const html = fs.readFileSync(path.join(assets, 'index.html'), 'utf8').replace('__CAMPUS_TIMEZONE__', 'Asia/Kuala_Lumpur');
const script = fs.readFileSync(path.join(assets, 'app.js'), 'utf8');
const intakeId = '00000000-0000-0000-0000-000000000001';

function result(status = 'OPTIMAL') {
  return {
    status, has_solution: ['OPTIMAL', 'FEASIBLE'].includes(status), week_start: '2026-11-09',
    timezone: 'Asia/Kuala_Lumpur', required_count: status === 'NO_PENDING_REQUIREMENTS' ? 0 : 1,
    scope: 'intake', intake_id: intakeId, group_number: null,
    snapshot_revision: 'a'.repeat(64), quality_optimized: false, quality: null,
    statistics: { elapsed_seconds: 0.02 }, diagnostics: [], candidate_failures: [],
    placements: status === 'OPTIMAL' ? [{
      starts_at: '2026-11-09T01:17:23.123456Z', ends_at: '2026-11-09T02:47:23.123456Z',
      occurrence_id: 'test-occurrence', room_id: 'test-room', section_id: 'test-section',
      course_code: 'TEST101', course_name: '<img src=x onerror=alert(1)>', course_type: 'lecture',
      group_number: 1, intake_id: 'test-intake', room_name: 'Classroom A', room_building: 'Block A',
      lecturer_id: 'test-lecturer', student_count: 40,
    }] : [],
  };
}

function page(fetch) {
  const dom = new JSDOM(html, { url: 'http://127.0.0.1:8000/admin/development/scheduling-test-hayden', runScripts: 'outside-only' });
  dom.window.fetch = fetch;
  dom.window.eval(script);
  dom.window.document.querySelector('#week-start').value = '2026-11-09';
  dom.window.document.querySelector('#intake-id').value = intakeId;
  return dom;
}

function submit(dom) {
  dom.window.document.querySelector('form').dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
}

async function settled(dom) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline && dom.window.document.querySelector('button').disabled) {
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.equal(dom.window.document.querySelector('button').disabled, false);
}

test('page submits selected week, shows progress, and renders safe local-time preview', async () => {
  let request, resolveResponse;
  const dom = page((url, options) => {
    request = { url, options };
    return new Promise(resolve => { resolveResponse = resolve; });
  });
  try {
    const document = dom.window.document;
    submit(dom);
    assert.equal(request.url, '/api/schedules/generate');
    assert.equal(request.options.method, 'POST');
    assert.deepEqual(JSON.parse(request.options.body), { week_start: '2026-11-09', intake_id: intakeId, group_number: null });
    assert.equal(document.querySelector('button').disabled, true);
    assert.match(document.querySelector('#status').textContent, /Loading database inputs/);
    assert.equal(document.querySelector('#result').hidden, true);
    resolveResponse({ ok: true, json: async () => result() });
    await settled(dom);
    assert.equal(document.querySelector('#result').hidden, false);
    assert.equal(document.querySelectorAll('tbody tr').length, 1);
    const text = document.querySelector('tbody').textContent;
    assert.match(text, /09:17:23\.123456/);
    assert.match(text, /10:47:23\.123456/);
    assert.match(text, /TEST101/);
    assert.match(text, /Classroom A/);
    assert.equal(document.querySelector('img'), null); // Provider labels are text.
    assert.match(text, /<img src=x/);
    assert.match(document.querySelector('#raw').textContent, /"quality_optimized": false/);
    assert.match(document.querySelector('#status').textContent, /nothing has been saved/);
  } finally { dom.window.close(); }
});

test('non-Monday input is rejected before fetch and editing clears the error', () => {
  let calls = 0;
  const dom = page(() => { calls++; });
  try {
    const input = dom.window.document.querySelector('input');
    input.value = '2026-11-10';
    submit(dom);
    assert.equal(calls, 0);
    assert.equal(input.validity.customError, true);
    input.value = '2026-11-09';
    input.dispatchEvent(new dom.window.Event('input'));
    assert.equal(input.validity.customError, false);
  } finally { dom.window.close(); }
});

test('selected group is sent and invalid intake/group is rejected before fetch', async () => {
  let calls = 0, request;
  const dom = page(async (url, options) => {
    calls++;
    request = JSON.parse(options.body);
    return { ok: true, json: async () => ({ ...result(), scope: 'intake_group', group_number: 2 }) };
  });
  try {
    const document = dom.window.document;
    const intake = document.querySelector('#intake-id');
    const group = document.querySelector('#group-number');
    intake.value = 'bad-id';
    submit(dom);
    assert.equal(calls, 0);
    assert.equal(intake.validity.customError, true);
    intake.value = intakeId;
    intake.dispatchEvent(new dom.window.Event('input'));
    group.value = '1.5';
    submit(dom);
    assert.equal(calls, 0);
    group.value = '2';
    group.dispatchEvent(new dom.window.Event('input'));
    submit(dom);
    await settled(dom);
    assert.deepEqual(request, { week_start: '2026-11-09', intake_id: intakeId, group_number: 2 });
    assert.match(document.querySelector('#schedule-caption').textContent, /Group 2/);
    assert.equal(intake.disabled, false);
    assert.equal(group.disabled, false);
  } finally { dom.window.close(); }
});

for (const [status, message] of [
  ['NO_PENDING_REQUIREMENTS', /No pending classes/],
  ['UNKNOWN', /does not prove the week is impossible/],
  ['INFEASIBLE', /No complete timetable satisfies/],
]) {
  test(`page distinguishes ${status} without showing assignments`, async () => {
    const data = result(status);
    if (status === 'INFEASIBLE') data.candidate_failures = [{ occurrence_id: 'test-occurrence', diagnostics: [{ code: 'NO_VALID_START_RANGE', detail: 'No uninterrupted room time.' }] }];
    const dom = page(async () => ({ ok: true, json: async () => data }));
    try {
      submit(dom);
      await settled(dom);
      const document = dom.window.document;
      assert.equal(document.querySelector('#result').hidden, false);
      assert.equal(document.querySelector('#schedule').hidden, true);
      assert.match(document.querySelector('#status').textContent, message);
      if (status === 'INFEASIBLE') assert.match(document.querySelector('#diagnostics').textContent, /NO_VALID_START_RANGE/);
    } finally { dom.window.close(); }
  });
}

for (const [name, response, message] of [
  ['busy', { ok: false, status: 429, json: async () => ({ detail: { code: 'GENERATION_BUSY', message: 'Another preview is being generated.' } }) }, /HTTP 429 \[GENERATION_BUSY\]: Another preview/],
  ['validation', { ok: false, status: 422, json: async () => ({ detail: [{ msg: 'week_start must be a Monday' }] }) }, /must be a Monday/],
  ['invalid response', { ok: false, status: 502, json: async () => { throw new Error('invalid JSON'); } }, /unreadable response/],
]) {
  test(`page handles ${name} and removes a previous preview`, async () => {
    let first = true;
    const dom = page(async () => first ? { ok: true, json: async () => result() } : response);
    try {
      submit(dom);
      await settled(dom);
      assert.equal(dom.window.document.querySelector('#result').hidden, false);
      first = false;
      submit(dom);
      await settled(dom);
      const document = dom.window.document;
      assert.equal(document.querySelector('#result').hidden, true);
      assert.match(document.querySelector('#status').textContent, message);
      assert.equal(document.querySelector('input').disabled, false);
    } finally { dom.window.close(); }
  });
}

test('network failure is shown and controls recover', async () => {
  const dom = page(async () => { throw new Error('Network unavailable'); });
  try {
    submit(dom);
    await settled(dom);
    assert.match(dom.window.document.querySelector('#status').textContent, /Could not reach the API server/);
    assert.equal(dom.window.document.querySelector('#result').hidden, true);
  } finally { dom.window.close(); }
});

test('provider error shows its classification and trace ID for log lookup', async () => {
  const traceId = 'a'.repeat(32);
  const dom = page(async () => ({
    ok: false, status: 502, headers: { get: () => traceId },
    json: async () => ({ detail: { code: 'DATABASE_UNAVAILABLE', message: 'A scheduling data read failed.', request_id: traceId } }),
  }));
  try {
    submit(dom);
    await settled(dom);
    const status = dom.window.document.querySelector('#status').textContent;
    assert.match(status, /DATABASE_UNAVAILABLE/);
    assert.match(status, /scheduling data read failed/);
    assert.ok(status.includes(`Request ID: ${traceId}`));
    assert.equal(dom.window.document.querySelector('#result').hidden, true);
  } finally { dom.window.close(); }
});

// ---------- Step 10: save with a two-step confirmation ----------

async function until(check) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline && !check()) await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(check());
}

function click(dom, selector) {
  dom.window.document.querySelector(selector).dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
}

function acknowledge(dom) {
  const box = dom.window.document.querySelector('#save-ack');
  box.checked = true;
  box.dispatchEvent(new dom.window.Event('change', { bubbles: true }));
}

function savingPage(saveResponse) {
  const requests = [];
  const dom = page(async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    return url === '/api/schedules/save' ? saveResponse() : { ok: true, json: async () => result() };
  });
  return { dom, requests };
}

test('save needs both confirmation steps and sends only occurrence, room and start', async () => {
  const { dom, requests } = savingPage(() => ({ ok: true, status: 201, json: async () => ({ status: 'SAVED', saved_count: 1, saved_by: 'Ada Admin', saved: [] }) }));
  try {
    const document = dom.window.document;
    submit(dom);
    await settled(dom);
    assert.equal(document.querySelector('#save-panel').hidden, false);
    assert.equal(document.querySelector('#save-confirm').hidden, true);
    click(dom, '#save');  // step 1
    assert.equal(document.querySelector('#save-confirm').hidden, false);
    assert.match(document.querySelector('#save-summary').textContent, /Save 1 class .*cannot undo/);
    assert.equal(document.querySelector('#save').disabled, true);
    assert.equal(document.querySelector('#save-confirm-button').disabled, true);
    click(dom, '#save-confirm-button');  // not acknowledged yet: nothing is sent
    assert.equal(requests.length, 1);
    acknowledge(dom);
    assert.equal(document.querySelector('#save-confirm-button').disabled, false);
    click(dom, '#save-confirm-button');  // step 2
    await until(() => /Saved 1 class/.test(document.querySelector('#status').textContent));
    assert.match(document.querySelector('#status').textContent, /recorded as saved by Ada Admin\./);
    assert.equal(requests.length, 2);
    assert.equal(requests[1].url, '/api/schedules/save');
    assert.deepEqual(requests[1].body, {
      week_start: '2026-11-09', intake_id: intakeId, group_number: null, snapshot_revision: 'a'.repeat(64),
      placements: [{ occurrence_id: 'test-occurrence', room_id: 'test-room', starts_at: '2026-11-09T01:17:23.123456Z' }],
    });
    assert.equal(document.querySelector('#save').textContent, 'Saved');
    assert.equal(document.querySelector('#save').disabled, true);
    assert.equal(document.querySelector('#save-confirm').hidden, true);
    assert.equal(document.querySelector('button').disabled, false);  // generate is usable again
  } finally { dom.window.close(); }
});

test('cancel closes the confirmation without saving', async () => {
  const { dom, requests } = savingPage(() => { throw new Error('must not save'); });
  try {
    const document = dom.window.document;
    submit(dom);
    await settled(dom);
    click(dom, '#save');
    acknowledge(dom);
    click(dom, '#save-cancel');
    assert.equal(document.querySelector('#save-confirm').hidden, true);
    assert.equal(document.querySelector('#save-ack').checked, false);
    assert.equal(document.querySelector('#save').disabled, false);
    assert.equal(requests.length, 1);
  } finally { dom.window.close(); }
});

for (const [code, retry] of [['PREVIEW_STALE', false], ['SAVE_OUTCOME_UNKNOWN', false], ['GENERATION_BUSY', true]]) {
  test(`save error ${code} is shown and ${retry ? 'allows retry' : 'requires a new preview'}`, async () => {
    const traceId = 'b'.repeat(32);
    const { dom } = savingPage(() => ({
      ok: false, status: 409, headers: { get: () => traceId },
      json: async () => ({ detail: { code, message: 'Nothing was saved.', request_id: traceId } }),
    }));
    try {
      const document = dom.window.document;
      submit(dom);
      await settled(dom);
      click(dom, '#save');
      acknowledge(dom);
      click(dom, '#save-confirm-button');
      await until(() => document.querySelector('#status').textContent.includes(code));
      const text = document.querySelector('#status').textContent;
      assert.ok(text.includes(`Request ID: ${traceId}`));
      assert.match(text, retry ? /Try saving again/ : /Generate a new preview/);
      assert.equal(document.querySelector('#save').disabled, !retry);
      assert.equal(document.querySelector('#save-confirm').hidden, true);
      assert.equal(document.querySelector('button').disabled, false);
    } finally { dom.window.close(); }
  });
}

test('save is not offered without a complete timetable', async () => {
  const dom = page(async () => ({ ok: true, json: async () => result('INFEASIBLE') }));
  try {
    submit(dom);
    await settled(dom);
    assert.equal(dom.window.document.querySelector('#save-panel').hidden, true);
  } finally { dom.window.close(); }
});

// The served page needs an admin login: log in to the synthetic QA service
// (fake Supabase Auth, never a hosted project) and reuse its session cookies.
async function servedPage(url) {
  const origin = new URL(url).origin;
  const anonymous = await fetch(url, { redirect: 'manual' });
  assert.equal(anonymous.status, 303);
  assert.equal(anonymous.headers.get('location'), `/login?next=${new URL(url).pathname}`);
  const login = await fetch(`${origin}/api/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Origin: origin },
    body: JSON.stringify({ email: 'qa-admin@example.test', password: 'qa-password-synthetic' }),
  });
  assert.equal(login.status, 200, await login.clone().text());
  const cookies = login.headers.getSetCookie();
  const cookieJar = new CookieJar();
  for (const value of cookies) cookieJar.setCookieSync(value, origin);
  const cookie = cookies.map(value => value.split(';')[0]).join('; ');
  return JSDOM.fromURL(url, {
    resources: 'usable', runScripts: 'dangerously', cookieJar,
    beforeParse(window) {
      window.fetch = (target, options) => fetch(new URL(target, url), {
        ...options, headers: { ...options.headers, Origin: origin, Cookie: cookie },
      });
    },
  });
}

test('served page makes a real HTTP request and renders the real synthetic solver result', { skip: !process.env.SCHEDULING_UI_URL }, async () => {
  const dom = await servedPage(process.env.SCHEDULING_UI_URL);
  try {
    if (dom.window.document.readyState !== 'complete') await new Promise(resolve => dom.window.addEventListener('load', resolve, { once: true }));
    dom.window.document.querySelector('#week-start').value = '2026-11-09';
    dom.window.document.querySelector('#intake-id').value = intakeId;
    submit(dom);
    await settled(dom);
    const document = dom.window.document;
    assert.equal(document.querySelector('#result').hidden, false, document.querySelector('#status').textContent);
    assert.equal(document.querySelectorAll('tbody tr').length, 1);
    const data = JSON.parse(document.querySelector('#raw').textContent);
    assert.equal(data.has_solution, true);
    assert.equal(data.placements.length, data.required_count);
    assert.equal(data.quality_optimized, false);
    assert.equal('student_ids' in data.placements[0], false);
    // The stand-in models an empty following week, without changing hosted data.
    document.querySelector('input').value = '2026-11-16';
    document.querySelector('input').dispatchEvent(new dom.window.Event('input'));
    submit(dom);
    await settled(dom);
    assert.equal(JSON.parse(document.querySelector('#raw').textContent).status, 'NO_PENDING_REQUIREMENTS');
    assert.equal(document.querySelectorAll('tbody tr').length, 0);
    assert.match(document.querySelector('#status').textContent, /No pending classes/);
  } finally { dom.window.close(); }
});

test('served page saves a reviewed preview through the real backend', { skip: !process.env.SCHEDULING_UI_URL }, async () => {
  const dom = await servedPage(process.env.SCHEDULING_UI_URL);
  try {
    if (dom.window.document.readyState !== 'complete') await new Promise(resolve => dom.window.addEventListener('load', resolve, { once: true }));
    const document = dom.window.document;
    document.querySelector('#week-start').value = '2026-11-09';
    document.querySelector('#intake-id').value = intakeId;
    submit(dom);
    await settled(dom);
    assert.equal(document.querySelector('#save-panel').hidden, false, document.querySelector('#status').textContent);
    click(dom, '#save');
    acknowledge(dom);
    click(dom, '#save-confirm-button');
    await until(() => /Saved|HTTP/.test(document.querySelector('#status').textContent));
    assert.match(document.querySelector('#status').textContent, /Saved 1 class to the timetable, recorded as saved by QA Admin\. Request ID: [0-9a-f]{32}/);
  } finally { dom.window.close(); }
});
