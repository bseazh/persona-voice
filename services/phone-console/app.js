const $ = (id) => document.getElementById(id);
let state = null;
let working = false;
function buttons() {
  $('dial').disabled = working || !state || !state.gateway_online || state.busy || !$('consent').checked;
  $('hangup').disabled = working || !state || !state.console_call_active;
}
async function refresh() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store' });
    if (!response.ok) throw new Error('无法读取服务状态，请检查 SSH 隧道或登录');
    state = await response.json();
    $('gateway').textContent = state.gateway_online ? '● 安卓网关在线' : '○ 安卓网关离线';
    $('call').textContent = state.console_call_active ? '本控制台通话中 / 正在呼叫' : state.pending ? '拨号请求处理中' : state.busy ? '线路被其他通话占用' : '线路空闲';
    if (JSON.stringify(state.numbers) !== $('number').dataset.values) {
      $('number').replaceChildren(...state.numbers.map((number) => new Option(number, number)));
      $('number').dataset.values = JSON.stringify(state.numbers);
    }
  } catch (error) {
    state = null;
    $('gateway').textContent = '状态不可用';
    $('call').textContent = error.message;
  }
  buttons();
}
async function action(path, data) {
  working = true; buttons();
  try {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Phone-Console': '1' }, body: JSON.stringify(data) });
    const result = await response.json();
    $('result').textContent = result.error || result.message;
    if (response.ok && path === '/api/dial') $('consent').checked = false;
  } catch {
    $('result').textContent = '请求结果未知，请检查通话状态，不要立即重复拨号。';
  } finally {
    working = false; await refresh();
  }
}
$('consent').addEventListener('change', buttons);
$('dial').addEventListener('click', () => action('/api/dial', { number: $('number').value }));
$('hangup').addEventListener('click', () => action('/api/hangup', {}));
refresh(); setInterval(refresh, 3000);
