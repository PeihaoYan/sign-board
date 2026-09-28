(() => {
  const params = new URLSearchParams(window.location.search);
  const slug = params.get('event') || window.__SIGN_BOARD_DEFAULT_EVENT__ || 'integrity-2026';
  const tokenKey = 'sign-board-admin-token';
  const loginPanel = document.querySelector('#login-panel');
  const adminShell = document.querySelector('#admin-shell');
  const loginForm = document.querySelector('#login-form');
  const loginInput = document.querySelector('#admin-token');
  const loginNotice = document.querySelector('#login-notice');
  const eventForm = document.querySelector('#event-form');
  const eventNotice = document.querySelector('#event-notice');
  const list = document.querySelector('#submission-list');
  const filterTabs = document.querySelector('#filter-tabs');
  let token = window.sessionStorage.getItem(tokenKey) || '';
  let currentFilter = 'all';
  let eventConfig = null;
  let monitorLink = '';

  const $ = (selector) => document.querySelector(selector);

  function headers(json = false) {
    const result = { Authorization: `Bearer ${token}` };
    if (json) result['Content-Type'] = 'application/json';
    return result;
  }

  function setNotice(target, message, error = false) {
    target.textContent = message;
    target.style.color = error ? '#f38472' : '#72d5c1';
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...headers(Boolean(options.body)), ...(options.headers || {}) } });
    if (response.status === 401) {
      logout();
      throw new Error('管理员凭据已失效');
    }
    const contentType = response.headers.get('content-type') || '';
    const body = contentType.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) throw new Error(body.detail || body || '请求失败');
    return body;
  }

  // ---------------------------------------------------------------------------
  // The QR size setting.
  //
  // The slider drives two things: the number the operator reads, and the preview, which is scaled
  // the same way the big screen scales the card, so a value can be judged before it is saved. The
  // wall itself is only told when the setting is saved.
  // ---------------------------------------------------------------------------
  const QR_PREVIEW_BASE = 180;
  // The card is about an eighth of the stage width at scale 1 (218 px on a 1884 px stage).
  const QR_STAGE_SHARE = 11.6;

  function qrScaleLabel(value) {
    return `${value.toFixed(1)}×`;
  }

  function setQrScale(scale) {
    const value = Math.min(Math.max(Number(scale) || 1, 0.5), 3);
    $('#qr-scale-input').value = String(value);
    $('#qr-scale-value').textContent = qrScaleLabel(value);
    $('#admin-qr').style.width = `${Math.round(QR_PREVIEW_BASE * value)}px`;
    $('#admin-qr').style.height = `${Math.round(QR_PREVIEW_BASE * value)}px`;
    $('#qr-preview-note').textContent = value === 1
      ? `预览为默认大小；大屏上约屏宽的 ${QR_STAGE_SHARE.toFixed(0)}%。`
      : `预览按 ${qrScaleLabel(value)} 显示；大屏上这张卡片约占屏宽 ${(QR_STAGE_SHARE * value).toFixed(0)}%，签名会避开它。`;
  }

  async function fillEvent(config) {
    eventConfig = config;
    $('#admin-event-label').textContent = `${config.title} · ${config.slug || slug}`;
    $('#event-title-input').value = config.title;
    $('#event-subtitle-input').value = config.subtitle;
    $('#event-org-input').value = config.organization;
    $('#event-welcome-input').value = config.welcome_text;
    $('#event-status-input').value = config.status;
    $('#display-limit-input').value = config.display_limit;
    setQrScale(Number(config.qr_scale) || 1);
    $('#admin-qr').src = `/api/events/${encodeURIComponent(slug)}/qr.svg`;

    // Prefer the configured public address so the shown links use the domain rather than
    // whatever host this console happens to be opened with.
    let base = window.location.origin;
    try {
      const publicUrl = await api(`/api/events/${encodeURIComponent(slug)}/public-url`);
      if (publicUrl && publicUrl.base_url) base = publicUrl.base_url;
    } catch (_) {
      /* fall back to the console's own origin */
    }
    const mobileUrl = `${base}/mobile?event=${encodeURIComponent(slug)}`;
    $('#mobile-url').textContent = mobileUrl;
    $('#open-mobile').href = mobileUrl;
    // Share a short-lived, one-time monitor code instead of placing the long-lived token in a URL.
    let monitorKey = '';
    try {
      const grant = await api(`/api/admin/events/${encodeURIComponent(slug)}/monitor-link`, { method: 'POST' });
      monitorKey = grant.key || '';
    } catch (_) {
      // The monitor page can still be opened manually with an existing session or token.
    }
    $('#open-monitor').href = monitorKey
      ? `${base}/monitor?event=${encodeURIComponent(slug)}&key=${encodeURIComponent(monitorKey)}`
      : `${base}/monitor`;
    monitorLink = $('#open-monitor').href;
    $('#download-csv').href = `/api/admin/events/${encodeURIComponent(slug)}/export.csv`;
    $('#download-zip').href = `/api/admin/events/${encodeURIComponent(slug)}/export.zip`;
    $('#download-csv').setAttribute('data-token', token);
    $('#download-zip').setAttribute('data-token', token);
  }

  function renderItems(items) {
    list.replaceChildren();
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'admin-empty';
      empty.textContent = '当前筛选条件下没有签名。';
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
      const metadata = document.createElement('span');
      // The participant page only collects a name, so later records have no unit.
      const time = new Date(item.created_at).toLocaleString();
      metadata.textContent = item.organization ? `${item.organization} · ${time}` : time;
      info.append(name, metadata);
      if (item.message) {
        const message = document.createElement('p');
        message.textContent = item.message;
        info.append(message);
      }
      const pill = document.createElement('span');
      pill.className = 'status-pill';
      pill.textContent = item.status;
      info.append(pill);
      const actions = document.createElement('div');
      actions.className = 'submission-actions';
      if (item.status !== 'approved') actions.append(actionButton('展示', () => updateStatus(item.id, 'approved'), 'gold'));
      if (item.status !== 'hidden') actions.append(actionButton('隐藏', () => updateStatus(item.id, 'hidden'), 'secondary'));
      if (item.status !== 'rejected') actions.append(actionButton('拒绝', () => updateStatus(item.id, 'rejected'), 'danger'));
      actions.append(actionButton('删除', () => deleteItem(item.id), 'danger'));
      row.append(preview, info, actions);
      list.append(row);
    });
  }

  function actionButton(label, handler, kind) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `button ${kind}`;
    button.textContent = label;
    button.addEventListener('click', handler);
    return button;
  }

  async function loadItems() {
    const result = await api(`/api/admin/events/${encodeURIComponent(slug)}/submissions?status=${currentFilter}`);
    renderItems(result.items);
  }

  async function updateStatus(id, status) {
    try {
      await api(`/api/admin/events/${encodeURIComponent(slug)}/submissions/${id}/status`, {
        method: 'PUT',
        body: JSON.stringify({ status }),
      });
      await loadItems();
    } catch (error) {
      window.alert(error.message);
    }
  }

  async function deleteItem(id) {
    if (!window.confirm('确认删除这条签名？删除后无法恢复。')) return;
    try {
      await api(`/api/admin/events/${encodeURIComponent(slug)}/submissions/${id}`, { method: 'DELETE' });
      await loadItems();
    } catch (error) {
      window.alert(error.message);
    }
  }

  async function openAdmin() {
    const config = await api(`/api/admin/events/${encodeURIComponent(slug)}`);
    await fillEvent(config);
    await loadItems();
    loginPanel.classList.add('admin-hidden');
    adminShell.classList.remove('admin-hidden');
  }

  function logout() {
    token = '';
    window.sessionStorage.removeItem(tokenKey);
    loginPanel.classList.remove('admin-hidden');
    adminShell.classList.add('admin-hidden');
    fetch('/api/admin/logout', { method: 'POST' }).catch(() => {});
  }

  $('#copy-monitor-link').addEventListener('click', async () => {
    if (!monitorLink) return;
    try {
      await navigator.clipboard.writeText(monitorLink);
      window.alert('监控链接已复制，可直接发给现场值班人员。');
    } catch (_) {
      window.prompt('复制下面的监控链接：', monitorLink);
    }
  });

  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    token = loginInput.value.trim();
    try {
      await api('/api/admin/login', { method: 'POST' });
      window.sessionStorage.setItem(tokenKey, token);
      await openAdmin();
    } catch (error) {
      setNotice(loginNotice, error.message, true);
      token = '';
    }
  });

  eventForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    try {
      const config = await api(`/api/admin/events/${encodeURIComponent(slug)}`, {
        method: 'PUT',
        body: JSON.stringify({
          title: $('#event-title-input').value.trim(),
          subtitle: $('#event-subtitle-input').value.trim(),
          organization: $('#event-org-input').value.trim(),
          welcome_text: $('#event-welcome-input').value.trim(),
          status: $('#event-status-input').value,
          display_limit: Number($('#display-limit-input').value),
          qr_scale: Number($('#qr-scale-input').value),
        }),
      });
      await fillEvent(config);
      setNotice(eventNotice, '活动设置已保存。');
    } catch (error) {
      setNotice(eventNotice, error.message, true);
    }
  });

  filterTabs.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-status]');
    if (!button) return;
    currentFilter = button.dataset.status;
    filterTabs.querySelectorAll('.filter-tab').forEach((tab) => tab.classList.toggle('is-active', tab === button));
    try { await loadItems(); } catch (error) { window.alert(error.message); }
  });

  document.querySelector('#logout-button').addEventListener('click', logout);

  // Dragging the slider shows the resulting size straight away; saving is what tells the wall.
  document.querySelector('#qr-scale-input').addEventListener('input', (event) => {
    setQrScale(event.target.value);
  });

  // Native download links cannot attach Authorization headers, so fetch the protected archive and save it locally.
  document.querySelectorAll('#download-csv, #download-zip').forEach((link) => {
    link.addEventListener('click', async (event) => {
      event.preventDefault();
      try {
        const response = await fetch(link.href, { headers: headers() });
        if (!response.ok) throw new Error('导出失败');
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = link.id.endsWith('zip') ? `${slug}-archive.zip` : `${slug}-submissions.csv`;
        anchor.click();
        URL.revokeObjectURL(url);
      } catch (error) { window.alert(error.message); }
    });
  });

  if (token) openAdmin().catch(() => logout());
})();
