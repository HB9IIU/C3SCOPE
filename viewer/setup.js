// Guided setup uses the local Python serial backend, never a browser port picker.
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('setupDevices') || !globalThis.SerialConnection?.backend) return;
  const kept = new Set();
  let listKey = '', submitting = false, running = false;
  let prepared = null;
  let handoffPending = false, watchInstallation = false;
  const dialog = document.createElement('dialog');
  dialog.className = 'setup-dialog';
  dialog.setAttribute('aria-labelledby', 'setupConfirmTitle');
  dialog.innerHTML = `<form method="dialog">
    <h2 id="setupConfirmTitle">Install C3SCOPE receiver firmware?</h2>
    <p id="setupConfirmDevice"></p>
    <p id="setupOperationDescription"></p>
    <p id="setupDialogError" role="alert" hidden></p>
    <p id="setupC3castWarning" class="setup-warning" hidden><strong>C3CAST transmitter detected!</strong><br>
    This board will stop working as your C3CAST transmitter until you reinstall its transmitter firmware.</p>
    <p class="setup-warning">This will erase and replace <strong>all firmware and settings stored on this board</strong>.<br>
    Files and settings on your computer will not be affected.</p>
    <label class="setup-confirm-check"><input id="setupConfirmBoard" type="checkbox">This board is a Seeed Studio XIAO ESP32-C3.</label>
    <label class="setup-confirm-check"><input id="setupConfirmErase" type="checkbox"><span id="setupEraseLabel">I understand that all firmware and settings on this board will be erased and receiver firmware installed.</span></label>
    <div class="setup-actions"><button id="setupCancel" type="button">Cancel</button><button id="setupInstall" type="button" disabled>Erase &amp; install C3SCOPE firmware</button></div>
  </form>`;
  document.body.append(dialog);
  const error = message => { $('setupError').textContent = message; $('setupError').hidden = !message; };
  const post = async (url, data) => {
    const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data), signal: AbortSignal.timeout(10000) });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Setup request failed.');
    return result;
  };
  function checked() {
    $('setupInstall').disabled = !prepared || submitting || !$('setupConfirmBoard').checked || !$('setupConfirmErase').checked;
  }
  $('setupConfirmBoard').onchange = checked;
  $('setupConfirmErase').onchange = checked;
  $('setupCancel').onclick = () => { prepared = null; dialog.close(); };
  dialog.addEventListener('cancel', event => { if (submitting) event.preventDefault(); else prepared = null; });
  async function review(candidate, operation = 'install') {
    if (submitting || running) return;
    error('');
    submitting = true;
    prepared = null;
    $('setupDialogError').hidden = true;
    $('setupConfirmBoard').checked = false;
    $('setupConfirmErase').checked = false;
    try {
      prepared = await post('/api/setup/prepare', { device: candidate.device, operation });
      const erasing = operation === 'erase';
      $('setupConfirmDevice').textContent = `Selected board: ${prepared.board} on ${prepared.device}.` + (erasing ? '' : ` Receiver firmware: ${prepared.build_date}.`);
      $('setupOperationDescription').textContent = erasing ? 'This leaves the ESP32 blank. It will not receive or transmit until firmware is installed again.' : '';
      $('setupEraseLabel').textContent = erasing ? 'I understand that all firmware and settings on this board will be erased. No replacement firmware will be installed.' : 'I understand that all firmware and settings on this board will be erased and receiver firmware installed.';
      $('setupInstall').textContent = erasing ? 'Erase ESP32' : 'Erase & install C3SCOPE firmware';
      $('setupC3castWarning').hidden = prepared.kind !== 'c3cast';
      $('setupConfirmTitle').textContent = erasing ? 'Erase this ESP32 completely?' : prepared.kind === 'c3cast' ? 'Convert your C3CAST to C3SCOPE?' : operation === 'update' ? 'Update receiver firmware?' : operation === 'reinstall' ? 'Reinstall receiver firmware?' : 'Prepare your XIAO for C3SCOPE';
      $('setupConfirmBoard').checked = false;
      $('setupConfirmErase').checked = false;
      dialog.showModal();
      $('setupCancel').focus();
    } catch (e) {
      error(e.message);
      $('setupConfirmTitle').textContent = 'Firmware setup unavailable';
      $('setupDialogError').textContent = e.message;
      $('setupDialogError').hidden = false;
      dialog.showModal();
    }
    finally { submitting = false; checked(); }
  }
  $('setupInstall').onclick = async () => {
    if (!prepared || submitting || !$('setupConfirmBoard').checked || !$('setupConfirmErase').checked) return;
    submitting = true; checked(); $('setupCancel').disabled = true;
    handoffPending = true;
    watchInstallation = false;
    try {
      if (prepared.kind === 'receiver') {
        if (!globalThis.C3ScopeFirmware) throw Error('Reload C3SCOPE before updating receiver firmware.');
        await C3ScopeFirmware.releaseReceiver();
      }
      const installation = await post('/api/setup/install', { token: prepared.token, confirm_board: true, confirm_erase: true });
      handoffPending = false;
      watchInstallation = installation.job_id || null;
      prepared = null; running = true; dialog.close();
      $('setupDevices').replaceChildren(); listKey = '';
      $('setupProgress').hidden = false;
      $('setupProgressText').textContent = 'Preparing your board. Keep it connected…';
    } catch (e) {
      handoffPending = false;
      watchInstallation = false;
      globalThis.C3ScopeFirmware?.resume();
      prepared = null;
      error(e.message);
      $('setupDialogError').textContent = e.message;
      $('setupDialogError').hidden = false;
    }
    finally { submitting = false; $('setupCancel').disabled = false; checked(); }
  };
  function render() {
    const info = SerialConnection.receiverStatus;
    if (!info) return;
    const job = info.installation || { state: 'idle' };
    running = handoffPending || ['preparing', 'flashing'].includes(job.state);
    if (watchInstallation && job.id === watchInstallation && !handoffPending && ['complete', 'error'].includes(job.state)) {
      watchInstallation = false;
      globalThis.C3ScopeFirmware?.resume();
    }
    $('reinstallFirmware').disabled = !info.can_reinstall || running || submitting;
    $('eraseReceiver').disabled = !info.can_reinstall || running || submitting;
    $('reinstallFirmware').hidden = info.local_control === false;
    $('eraseReceiver').hidden = info.local_control === false;
    $('updateFirmware').hidden = !info.can_reinstall;
    const waiting = document.body.classList.contains('receiver-waiting');
    $('setupProgress').hidden = job.state === 'idle' || !waiting;
    $('setupProgressText').textContent = job.message || '';
    $('setupProgressBar').hidden = job.state === 'error';
    if (job.progress === null || job.progress === undefined) $('setupProgressBar').removeAttribute('value');
    else $('setupProgressBar').value = job.progress;
    $('setupLog').textContent = (job.log || []).join('\n');
    const candidates = (info.setup_candidates || []).filter(c => !kept.has(JSON.stringify(c.fingerprint)));
    const key = JSON.stringify([candidates, running]);
    if (key !== listKey) {
      listKey = key;
      $('setupDevices').replaceChildren();
      if (!running) for (const candidate of candidates) {
        const card = document.createElement('div'); card.className = 'setup-device';
        const heading = document.createElement('h3');
        heading.textContent = candidate.kind === 'c3cast' ? `C3CAST transmitter detected · ${candidate.device}` : `ESP device found · ${candidate.device}`;
        const note = document.createElement('p');
        note.textContent = candidate.kind === 'c3cast'
          ? 'You can keep your transmitter and connect a separate receiver. Converting this board will replace C3CAST.'
          : 'Blank or unrecognized firmware. If this is your XIAO ESP32-C3, install the bundled receiver firmware.';
        const actions = document.createElement('div'); actions.className = 'setup-actions';
        const keep = document.createElement('button'); keep.type = 'button';
        keep.textContent = candidate.kind === 'c3cast' ? 'Keep my C3CAST' : 'Leave this board as it is';
        keep.onclick = () => { kept.add(JSON.stringify(candidate.fingerprint)); listKey = ''; render(); };
        const install = document.createElement('button'); install.type = 'button'; install.className = 'setup-convert';
        install.textContent = candidate.kind === 'c3cast' ? 'Convert to C3SCOPE…' : 'Install receiver firmware…';
        install.onclick = () => review(candidate);
        actions.append(keep, install); card.append(heading, note, actions); $('setupDevices').append(card);
      }
    }
    if (waiting && running) {
      $('receiverWaitingTitle').textContent = job.operation === 'erase' ? 'Erasing your ESP32' : 'Preparing your C3SCOPE receiver';
      $('receiverWaitingMessage').textContent = 'Keep the USB cable connected until installation finishes.';
      $('status').textContent = job.operation === 'erase' ? 'Erasing ESP32' : 'Installing receiver firmware';
    } else if (waiting && candidates.length) {
      $('receiverWaitingTitle').textContent = candidates.some(c => c.kind === 'c3cast') ? 'This looks like your C3CAST transmitter!' : 'Plug. Flash. Play.';
      $('receiverWaitingMessage').textContent = 'Guided setup for the Seeed Studio XIAO ESP32-C3.';
    }
  }
  const receiverReview = operation => {
    const info = SerialConnection.receiverStatus;
    if (info?.can_reinstall && !running) return review({ device: info.device }, operation);
  };
  $('reinstallFirmware').onclick = () => receiverReview('reinstall');
  $('eraseReceiver').onclick = () => receiverReview('erase');
  $('updateFirmware').onclick = event => { event.preventDefault(); return receiverReview('update'); };
  $('updateFirmware').removeAttribute('target');
  $('updateFirmware').setAttribute('role', 'button');
  globalThis.addEventListener('receiverstatus', render);
  globalThis.addEventListener('beforeunload', event => {
    if (running) { event.preventDefault(); event.returnValue = ''; }
  });
  render();
})();
