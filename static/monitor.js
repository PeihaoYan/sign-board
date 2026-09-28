(() => {
  const params = new URLSearchParams(window.location.search);
  const slug = params.get('event') || window.__SIGN_BOARD_DEFAULT_EVENT__ || 'integrity-2026';
  const tokenKey = 'sign-board-monitor-token';
  let token = params.get('key') || window.sessionStorage.getItem(tokenKey) || '';
  const list = document.querySelector('#monitor-list');
  const connectionState = document.querySelector('#connection-state');
  const notice = document.querySelector('#monitor-notice');
  let timer = null;
  let failures = 0;
  let currentItems = [];

  const statusLabels = {
    draft: '尚未开放',
    live: '现场开放',
    paused: '暂时暂停',
    ended: '活动结束',
  };

  const $ = (selector) => document.querySelector(selector);

  function setConnection(text, state) {
    connectionState.textContent = text;
    connectionState.dataset.state = state;
  }

  function formatTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleTimeString('zh-CN', { hour12: false });
  }

  function renderRecent(items) {
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'admin-empty';
      empty.textContent = '还没有签名提交。';
      list.append(empty);
      return;
    }
    items.forEach((item) => {
      const row = document.createElement('article');
      row.className = 'submission-row';
      const preview = document.createElement('canvas');
      preview.className = 'submission-preview';
      preview.setAttribute('aria-label', '签名预览');
      window.renderSignatureInto(preview, item, { width: 76, height: 56, lineWidth: 2.4 });
      const info = document.createElement('div');
      info.className = 'submission-info';
      const name = document.createElement('strong');
      name.textContent = item.name || '匿名参与者';
      const meta = document.createElement('span');
      const time = formatTime(item.created_at);
      meta.textContent = item.organization ? `${item.organization} · ${time}` : time;
      info.append(name, meta);
      if (item.message) {
        const message = document.createElement('p');
        message.textContent = item.message;
        info.append(message);
      }
      const pill = document.createElement('span');
      pill.className = 'status-pill';
      pill.textContent = item.status;
      info.append(pill);
      row.append(preview, info);
      list.append(row);
    });
  }

  async function load() {
    try {
      // The credential is exchanged once; subsequent requests use the short-lived HttpOnly cookie.
      const response = await fetch(`/api/monitor/events/${encodeURIComponent(slug)}`, {
        cache: 'no-store',
        credentials: 'same-origin',
      });
      if (response.status === 401) {
        setConnection('需要监控凭据', 'error');
        const hint = document.createElement('div');
        hint.className = 'admin-empty';
        hint.textContent = '请使用管理员生成的一次性监控链接，或先完成监控登录。';
        list.replaceChildren(hint);
        window.clearInterval(timer);
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      const stats = data.stats;

      $('#monitor-title').textContent = data.event.title || '签名墙现场监控';
      $('#monitor-subtitle').textContent = data.event.subtitle
        ? `${data.event.subtitle} · 本页可下载与清空当前页`
        : '本页面用于查看现场状态；「清空当前页」会真实删除服务端数据。';
      $('#stat-total').textContent = String(stats.total);
      $('#stat-total-foot').textContent = `已展示 ${stats.approved} 条，状态为 ${statusLabels[data.event.status] || data.event.status}`;
      $('#stat-minute').textContent = String(stats.last_minute);
      $('#stat-ten').textContent = String(stats.last_ten_minutes);
      $('#stat-blocked').textContent = `${stats.hidden} / ${stats.rejected}`;
      $('#event-state').textContent = `活动状态：${statusLabels[data.event.status] || data.event.status}`;
      $('#last-submission').textContent = `最近提交：${stats.last_submission ? formatTime(stats.last_submission) : '—'}`;
      $('#server-time').textContent = `服务器时间：${formatTime(data.server_time)}`;

      renderRecent(data.recent);
      currentItems = data.recent;
      failures = 0;
      setConnection('实时刷新中', 'live');
    } catch (error) {
      failures += 1;
      setConnection(failures > 2 ? '刷新失败' : '重试中', 'error');
    }
  }

  function restartTimer() {
    window.clearInterval(timer);
    timer = window.setInterval(load, 3000);
  }

  $('#refresh-now').addEventListener('click', load);
  $('#monitor-logout').addEventListener('click', async () => {
    try {
      await fetch('/api/monitor/logout', { method: 'POST' });
    } catch (_) {
      /* logging out locally is enough */
    }
    window.sessionStorage.removeItem(tokenKey);
    window.location.replace('/monitor');
  });

  function setNotice(message, error = false) {
    if (!notice) return;
    notice.textContent = message;
    notice.style.color = error ? '#f38472' : '#72d5c1';
  }

  // ---------------------------------------------------------------------------
  // Download the big screen as a PNG.
  //
  // The picture is the wall the audience is looking at: the venue background, every
  // signature in the arrangement the wall computed, the QR card and the status chip. It is
  // not a dump of this page's own table. The layout comes from wallLayout.js — the same
  // module the wall lays out with — so the arrangement in the picture is the one on screen.
  // ---------------------------------------------------------------------------
  async function downloadSnapshot() {
    const button = $('#download-page');
    const original = button.textContent;
    button.disabled = true;
    button.textContent = '生成中…';
    try {
      const rendered = await window.wallExport.renderWallPng({ slug });
      const blob = await new Promise((resolve, reject) => {
        rendered.canvas.toBlob((result) => {
          if (result) resolve(result);
          else reject(new Error('浏览器无法生成图片'));
        }, 'image/png');
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = window.wallExport.buildWallPngFileName();
      anchor.click();
      URL.revokeObjectURL(url);
      // A picture laid out without the wall's geometry is a valid arrangement but not necessarily
      // the one on screen, and the operator has to know which one they just saved.
      const matched = rendered.geometrySource && rendered.geometrySource.startsWith('wall');
      setNotice(
        matched
          ? `大屏 PNG 已下载：${rendered.items.length} 个签名，与大屏排布一致，`
            + `画面 ${rendered.stage.width}×${rendered.stage.height}。`
          : `大屏 PNG 已下载：${rendered.items.length} 个签名。大屏未上报排布参数，`
            + `本图按本机窗口比例排布，位置可能与现场大屏不同；请在大屏打开后重新下载。`,
        !matched,
      );
    } catch (error) {
      setNotice(error.message, true);
    } finally {
      button.disabled = false;
      button.textContent = original;
    }
  }

  async function clearPage() {
    if (!currentItems.length) {
      setNotice('当前页没有签名可清空。', true);
      return;
    }
    const confirmed = window.confirm(`将永久删除当前页的 ${currentItems.length} 条签名，大屏上也会立即消失。确认继续？`);
    if (!confirmed) return;
    const ids = currentItems.map((item) => item.id);
    try {
      const response = await fetch(`/api/monitor/events/${encodeURIComponent(slug)}/submissions/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ ids }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '删除失败');
      setNotice(`已删除 ${result.deleted} 条签名。`);
      await load();
    } catch (error) {
      setNotice(error.message, true);
    }
  }

  $('#download-page').addEventListener('click', downloadSnapshot);
  $('#clear-page').addEventListener('click', clearPage);

  // Exchange the one-time link or token before any monitor request is made.
  async function openSession() {
    if (!token) return;
    try {
      const response = await fetch('/api/monitor/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ key: token }),
      });
      if (!response.ok) throw new Error('监控凭据无效');
      token = '';
      window.sessionStorage.removeItem(tokenKey);
    } catch (_) {
      /* load() reports the unauthorised session without retaining the credential. */
      token = '';
      window.sessionStorage.removeItem(tokenKey);
    }
  }

  // Keep the credential only in this tab so a shared link or screenshot cannot leak it.
  if (params.get('key')) {
    window.sessionStorage.setItem(tokenKey, params.get('key'));
    params.delete('key');
    const query = params.toString();
    window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`);
  }

  // Point the archive link at this event and open a session cookie for it.
  $('#download-archive').href = `/api/monitor/events/${encodeURIComponent(slug)}/archive.zip`;

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      window.clearInterval(timer);
    } else {
      load();
      restartTimer();
    }
  });

  (async () => {
    await openSession();
    await load();
    restartTimer();
  })();
})();
