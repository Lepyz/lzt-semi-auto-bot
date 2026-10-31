(() => {
  'use strict';
  const dialog = document.getElementById('cleanup-dialog');
  if (dialog) {
    const picks = [...document.querySelectorAll('.cleanup-pick')];
    const bulk = [...document.querySelectorAll('[data-cleanup-bulk]')];
    const form = document.getElementById('cleanup-form');
    const selected = () => picks.filter(input => input.checked);
    function updateSelection() {
      const chosen = selected();
      document.getElementById('cleanup-count').textContent = `${chosen.length} kayıt seçili`;
      bulk.forEach(button => {
        button.disabled = !chosen.length || (button.dataset.cleanupAction === 'close' && chosen.some(input => input.dataset.canClose !== 'yes'));
      });
    }
    document.querySelectorAll('[data-cleanup-ui]').forEach(element => { element.hidden = false; });
    picks.forEach(input => input.addEventListener('change', updateSelection));
    document.getElementById('cleanup-select').addEventListener('click', () => {
      picks.forEach(input => { input.checked = true; }); updateSelection();
    });
    document.getElementById('cleanup-clear').addEventListener('click', () => {
      picks.forEach(input => { input.checked = false; }); updateSelection();
    });
    document.querySelectorAll('[data-cleanup-action]').forEach(button => button.addEventListener('click', () => {
      const values = button.dataset.cleanupOne ? [button.dataset.cleanupOne] : selected().map(input => input.value);
      if (!values.length) return;
      form.reset();
      const action = button.dataset.cleanupAction;
      document.getElementById('cleanup-action').value = action;
      const container = document.getElementById('cleanup-selection');
      container.replaceChildren();
      values.forEach(value => {
        const input = document.createElement('input');
        input.type = 'hidden'; input.name = 'selected'; input.value = value; container.append(input);
      });
      document.getElementById('cleanup-title').textContent = `${values.length} kayıt ${action === 'delete' ? 'silinecek' : 'kapatılacak'}`;
      document.getElementById('cleanup-explanation').textContent = action === 'delete'
        ? 'Seçilen kayıtların müşteri linki, ürün ve panel ayrıntıları silinecek. Geri alınamaz. Çift siparişi önleyen kimlikler korunur.'
        : 'Seçilen kayıtlar gönderilmeden kapatılacak ve Sonuçlananlar bölümüne taşınacak. Kayıt ayrıntıları korunur.';
      const records = document.getElementById('cleanup-records');
      records.replaceChildren();
      records.parentElement.open = false;
      values.forEach(value => {
        const row = document.createElement('li');
        row.textContent = picks.find(input => input.value === value)?.dataset.cleanupLabel || value.split(':')[0];
        records.append(row);
      });
      document.getElementById('cleanup-submit').textContent = action === 'delete' ? 'Onayla ve sil' : 'Onayla ve kapat';
      document.getElementById('cleanup-submit').disabled = false;
      dialog.showModal();
    }));
    document.getElementById('cleanup-cancel').addEventListener('click', () => dialog.close());
    form.addEventListener('submit', () => { document.getElementById('cleanup-submit').disabled = true; });
    updateSelection();
  }
  document.querySelectorAll('[data-copy-text]').forEach(button => button.addEventListener('click', async () => {
    const feedback = document.getElementById('copy-feedback');
    try {
      await navigator.clipboard.writeText(button.dataset.copyText);
      const previous = button.textContent;
      button.textContent = '✓ Kopyalandı';
      feedback.textContent = 'Kopyalandı.';
      setTimeout(() => { button.textContent = previous; }, 1800);
    } catch (_) {
      feedback.textContent = 'Kopyalama kullanılamadı. Metni seçip elle kopyalayabilirsin.';
    }
  }));
})();
