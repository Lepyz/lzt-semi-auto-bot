(() => {
  'use strict';
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
