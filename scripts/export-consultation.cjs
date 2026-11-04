// Export an authorized consultation without printing credentials or transcript.
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const id = process.argv[2];
if (!/^[0-9a-f-]{36}$/.test(id || '')) throw Error('Provide consultation UUID');
const origin = 'https://phone.hehaizhao.site';
(async () => {
  const password = fs.readFileSync(path.join(root, 'BigApple输出/consultation-access.txt'), 'utf8')
    .split('管理员密码：')[1].split('\n')[0];
  const login = await fetch(origin + '/api/consult/login', {
    method: 'POST', headers: {'Content-Type': 'application/json', Origin: origin, 'X-Consultation': '1'},
    body: JSON.stringify({password}),
  });
  if (!login.ok) throw Error('Login failed: ' + login.status);
  const cookie = login.headers.getSetCookie().map(value => value.split(';')[0]).join('; ');
  async function get(route) {
    const response = await fetch(origin + '/api/consult/' + route, {headers: {Cookie: cookie}});
    if (!response.ok) throw Error('Read failed: ' + response.status);
    return response;
  }
  const session = await (await get('session?id=' + id)).json();
  const events = await (await get('events?id=' + id)).json();
  if (session.status !== 'closed' || session.report_status !== 'ready') throw Error('Consultation not archived');
  const out = path.join(root, 'BigApple输出/consultation-' + id);
  fs.mkdirSync(out, {recursive: true, mode: 0o700});
  for (const kind of ['report', 'transcript']) {
    const content = await (await get('export?id=' + id + '&kind=' + kind)).text();
    fs.writeFileSync(path.join(out, kind + '.md'), content, {mode: 0o600});
  }
  const farewell = events.find(event => event.kind === 'voice.farewell_played');
  const closed = events.find(event => event.kind === 'voice.closed');
  const result = {id, mode: session.mode, reason: session.reason, report_status: session.report_status,
    messages: session.messages.length, interruptions: session.messages.filter(message => message.interrupted).length,
    farewellBeforeClose: !!farewell && !!closed && farewell.seq < closed.seq, eventCount: events.length};
  fs.writeFileSync(path.join(out, 'verification.json'), JSON.stringify(result, null, 2), {mode: 0o600});
  console.log(JSON.stringify(result));
})().catch(error => {console.error(error.message); process.exitCode = 1;});
