// One socket per page tracks tab lifetime without relying on unload requests
// or timers that browsers throttle in background tabs.
(function () {
  'use strict';
  if (!globalThis.SerialConnection?.backend) return;
  const button = document.getElementById('quitApp');
  let socket = null, leaving = false, quitting = false, submitting = false;
  const dialog = document.createElement('dialog');
  dialog.className = 'quit-dialog';
  dialog.setAttribute('aria-labelledby', 'quitTitle');
  dialog.setAttribute('aria-describedby', 'quitDescription');
  dialog.innerHTML = `<div class="quit-dialog-heading"><img src="c3scope.svg" width="48" height="48" alt=""><div><span>C3SCOPE</span><h2 id="quitTitle">Quit C3SCOPE?</h2></div></div>
    <p id="quitDescription">This will stop the app and release the USB receiver.</p>
    <p class="quit-detail">All open C3SCOPE viewers will disconnect.</p>
    <p id="quitError" role="alert" hidden></p>
    <div class="quit-dialog-actions"><button id="quitCancel" type="button">Cancel</button><button id="quitConfirm" type="button">Quit C3SCOPE</button></div>`;
  document.body.append(dialog);
  const cancel = document.getElementById('quitCancel');
  const confirmButton = document.getElementById('quitConfirm');
  const errorMessage = document.getElementById('quitError');
  cancel.onclick = () => { if (!submitting) dialog.close(); };
  dialog.addEventListener('cancel', event => { if (submitting) event.preventDefault(); });
  button.hidden = globalThis.C3ScopeAccess?.local === false;
  const lanNotice = document.getElementById('lanNotice');
  if (globalThis.C3ScopeAccess?.lan && lanNotice) {
    lanNotice.hidden = false;
    lanNotice.textContent = C3ScopeAccess.local
      ? `LAN access: ${C3ScopeAccess.urls.join(' · ') || 'use this PC’s LAN IP and the port shown in the terminal'}. One viewer controls the receiver at a time. Close this tab to use another PC; the app stays running.`
      : 'LAN viewer · Firmware operations and Quit are available on the host PC. Closing this tab leaves the host running.';
  }
  button.title = 'Stop the app and release USB. Closing the last viewer tab also stops the app after 10 seconds.';
  function stopped() {
    if (globalThis.C3ScopeStopped) return;
    globalThis.C3ScopeStopped = true;
    quitting = true;
    if (dialog.open) dialog.close();
    document.body.classList.add('app-stopped');
    document.getElementById('status').textContent = 'Stopped';
    document.getElementById('light').classList.remove('on');
    document.getElementById('chipIdentity').hidden = true;
    document.getElementById('toggleControls').hidden = true;
    button.hidden = true;
    const panel = document.createElement('section');
    panel.className = 'app-stopped-panel';
    panel.setAttribute('role', 'status');
    panel.innerHTML = '<div class="receiver-waiting-card"><img class="receiver-search-symbol" src="c3scope.svg" alt=""><h2>C3SCOPE stopped</h2><p>The app has shut down and released the USB receiver.<br>You can close this tab.</p></div>';
    document.body.append(panel);
    socket?.close();
  }
  function connect() {
    if (leaving || quitting) return;
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/lifecycle`);
    socket.onmessage = ({ data }) => {
      if (JSON.parse(data).event === 'stopping') stopped();
    };
    socket.onclose = () => { if (!leaving && !quitting) setTimeout(connect, 1000); };
  }
  button.onclick = () => {
    if (quitting || submitting || button.disabled) return;
    errorMessage.hidden = true;
    dialog.showModal();
    cancel.focus();
  };
  confirmButton.onclick = async () => {
    if (quitting || submitting || confirmButton.disabled) return;
    submitting = true;
    button.disabled = true;
    cancel.disabled = true;
    confirmButton.disabled = true;
    confirmButton.textContent = 'Stopping…';
    errorMessage.hidden = true;
    try {
      const response = await fetch('/api/quit', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: '{}', signal: AbortSignal.timeout(5000) });
      const result = await response.json();
      if (!response.ok) throw Error(result.error || 'Could not stop C3SCOPE.');
      stopped();
    } catch (error) {
      if (!globalThis.C3ScopeStopped) {
        errorMessage.textContent = error.message;
        errorMessage.hidden = false;
        button.disabled = false;
      }
    } finally {
      submitting = false;
      cancel.disabled = false;
      confirmButton.disabled = false;
      confirmButton.textContent = 'Quit C3SCOPE';
    }
  };
  globalThis.addEventListener('receiverstatus', () => {
    const installing = ['preparing', 'flashing'].includes(SerialConnection.receiverStatus?.installation?.state);
    button.disabled = installing || submitting;
    confirmButton.disabled = installing || submitting;
    button.title = installing ? 'Let firmware installation finish before quitting.' : 'Quit C3SCOPE and release the USB receiver.';
  });
  globalThis.addEventListener('pagehide', () => { leaving = true; socket?.close(); });
  globalThis.addEventListener('pageshow', event => {
    if (event.persisted) { leaving = false; connect(); }
  });
  connect();
})();
