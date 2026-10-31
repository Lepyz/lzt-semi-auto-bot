/* Mapping editor only: no polling, provider requests, or order submission. */
(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('mapping-data').textContent);
  const form = document.getElementById('mapping-form');
  const editor = document.getElementById('mapping-editor');
  const rows = document.getElementById('component-rows');
  const preview = document.getElementById('mapping-preview');
  const error = document.getElementById('mapping-error');
  const save = document.getElementById('save-mapping');
  let dirty = false;
  let saving = false;
  let filter = 'all';
  const field = name => form.elements.namedItem(name);
  const hidePreview = () => { preview.hidden = true; error.hidden = true; };
  const canLeave = () => !saving && (!dirty || window.confirm('Kaydedilmemiş değişiklikler var. Vazgeçmek istiyor musun?'));
  function showError(message) {
    error.textContent = message;
    error.hidden = false;
    error.focus();
  }
  function updateRows() {
    [...rows.children].forEach((row, i) => {
      row.querySelector('[data-row-title]').textContent = `${i + 1}. servis`;
      row.querySelector('[data-remove]').disabled = rows.children.length === 1;
    });
  }
  function addRow(part = {}) {
    const row = document.getElementById('component-template').content.firstElementChild.cloneNode(true);
    row.querySelectorAll('[data-field]').forEach(input => {
      const value = part[input.dataset.field];
      if (value === undefined) return;
      if (input.tagName === 'SELECT' && ![...input.options].some(option => option.value === String(value))) {
        input.add(new Option(String(value), String(value)));
      }
      input.value = value;
    });
    rows.append(row);
    updateRows();
  }
  function openEditor(id = '', copy = false) {
    if (!canLeave()) return;
    form.reset();
    const binding = data.bindings[id] || {};
    const editing = Boolean(id && !copy);
    field('mode').value = editing ? 'edit' : 'create';
    field('version').value = editing ? data.versions[id] : '';
    field('advert_id').value = editing ? id : '';
    field('advert_id').readOnly = editing;
    field('name').value = binding.name || '';
    field('active').value = binding.active === false ? 'false' : 'true';
    rows.replaceChildren();
    (binding.components || [{}]).forEach(addRow);
    document.getElementById('editor-title').textContent = editing ? 'İlan eşleştirmesini düzenle' : copy ? 'Eşleştirmeyi yeni ilana kopyala' : 'Yeni ilan bağla';
    document.getElementById('editor-help').textContent = copy ? `İlan ${id} ayarları kopyalandı. Yeni ilan numarasını girip adedi kontrol et.` : editing ? `İlan ${id} · Mevcut servisleri ve paket bileşenlerini düzenleyebilirsin.` : 'İlan numarasını gir, panel ve servis bilgilerini belirle.';
    save.textContent = editing ? 'Değişiklikleri kaydet' : 'Eşleştirmeyi kaydet';
    const deletion = document.getElementById('delete-section');
    deletion.hidden = !editing;
    deletion.open = false;
    deletion.querySelector('[type=checkbox]').checked = false;
    document.getElementById('delete-advert').value = editing ? id : '';
    hidePreview();
    dirty = false;
    editor.hidden = false;
    editor.scrollIntoView({behavior: 'smooth', block: 'start'});
    (editing ? field('name') : field('advert_id')).focus({preventScroll: true});
  }
  function components() {
    return [...rows.children].map(row => Object.fromEntries([...row.querySelectorAll('[data-field]')].map(input => [input.dataset.field, input.value.trim()])));
  }
  function validate() {
    field('advert_id').value = field('advert_id').value.trim();
    if (!form.reportValidity()) return false;
    if (!/[1-9]/.test(field('advert_id').value)) {
      showError('Geçerli bir ilan numarası girin.');
      return false;
    }
    if (components().some(part => !/[1-9]/.test(part.service_id))) {
      showError('Servis numarası sıfır olamaz. Paneldeki servis numarasını girin.');
      return false;
    }
    if (field('mode').value === 'create' && Object.prototype.hasOwnProperty.call(data.bindings, field('advert_id').value)) {
      showError('Bu ilan zaten eşleştirilmiş. İlan kartındaki Düzenle düğmesini kullanın.');
      return false;
    }
    return true;
  }
  function showPreview() {
    if (!validate()) return false;
    preview.replaceChildren();
    const title = document.createElement('h3');
    title.textContent = 'Eşleştirme özeti';
    preview.append(title);
    const line = text => {
      const p = document.createElement('p');
      p.textContent = text;
      preview.append(p);
    };
    line(`İlan ${field('advert_id').value} · ${field('name').value || 'İlan adı girilmedi'}`);
    line(`Durum: ${field('active').selectedOptions[0].textContent}`);
    [...rows.children].forEach((row, i) => {
      const get = name => row.querySelector(`[data-field="${name}"]`);
      line(`${i + 1}. ${get('panel').selectedOptions[0].textContent} · Servis ${get('service_id').value} · ${get('quantity').value} adet · ${get('platform').selectedOptions[0].textContent}`);
    });
    line('Kaydetmek sipariş göndermez. Mevcut panel siparişleri korunur.');
    error.hidden = true;
    preview.hidden = false;
    return true;
  }
  document.getElementById('new-mapping').addEventListener('click', () => openEditor());
  document.getElementById('close-editor').addEventListener('click', () => {
    if (canLeave()) { editor.hidden = true; dirty = false; }
  });
  document.getElementById('mapping-list').addEventListener('click', event => {
    const edit = event.target.closest('[data-edit]');
    const copy = event.target.closest('[data-copy]');
    if (edit) openEditor(edit.dataset.edit);
    if (copy) openEditor(copy.dataset.copy, true);
  });
  document.getElementById('add-component').addEventListener('click', () => {
    addRow(); dirty = true; hidePreview();
  });
  rows.addEventListener('click', event => {
    const button = event.target.closest('[data-remove]');
    if (button && rows.children.length > 1) {
      button.closest('.mapping-component').remove(); updateRows(); dirty = true; hidePreview();
    }
  });
  form.addEventListener('input', () => { dirty = true; hidePreview(); });
  form.addEventListener('change', () => { dirty = true; hidePreview(); });
  document.getElementById('show-preview').addEventListener('click', () => {
    if (showPreview()) preview.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || !showPreview()) return;
    field('components').value = JSON.stringify(components());
    saving = true;
    save.disabled = true;
    save.textContent = 'Kaydediliyor…';
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin'});
      if (!response.ok) {
        const body = await response.text();
        const message = new DOMParser().parseFromString(body, 'text/html').body.textContent;
        showError(response.status === 401 ? 'Oturum doğrulanamadı. Sayfayı yenileyip tekrar giriş yapın.' :
          response.status >= 500 ? 'Sunucuda bir sorun oluştu. Bilgilerin formda duruyor; tekrar denemeden önce kaydı listeden kontrol et.' :
          response.status === 422 ? 'Formdaki zorunlu alanları ve sayısal değerleri kontrol edin.' :
          message || 'Eşleştirme kaydedilemedi. Formu kontrol edin.');
        return;
      }
      dirty = false;
      window.location.assign(response.url);
    } catch (_) {
      showError('Sunucuya ulaşılamadı. Bilgilerin formda duruyor. Bağlantını kontrol et; sayfayı yenilediğinde kaydı listeden doğrulayabilirsin.');
    } finally {
      saving = false;
      save.disabled = false;
      save.textContent = field('mode').value === 'edit' ? 'Değişiklikleri kaydet' : 'Eşleştirmeyi kaydet';
    }
  });
  window.addEventListener('beforeunload', event => {
    if (dirty) { event.preventDefault(); event.returnValue = ''; }
  });
  function applyFilters() {
    const query = document.getElementById('mapping-search').value.trim().toLocaleLowerCase('tr');
    const panel = document.getElementById('panel-filter').value;
    let count = 0;
    document.querySelectorAll('.mapping-card').forEach(card => {
      const id = card.dataset.advert;
      const binding = data.bindings[id];
      const parts = binding.components || [];
      const haystack = [id, binding.name, ...parts.flatMap(part => [part.panel, part.service_id, part.name, part.platform])].join(' ').toLocaleLowerCase('tr');
      const match = (!query || haystack.includes(query)) && (!panel || parts.some(part => part.panel === panel)) &&
        (filter === 'all' || filter === 'active' && binding.active !== false || filter === 'inactive' && binding.active === false || filter === 'package' && parts.length > 1);
      card.hidden = !match;
      if (match) count++;
    });
    document.getElementById('mapping-count').textContent = `${count} / ${Object.keys(data.bindings).length} eşleştirme gösteriliyor`;
    const empty = document.getElementById('mapping-empty');
    empty.hidden = count > 0;
    empty.textContent = Object.keys(data.bindings).length ? 'Bu arama ve filtreye uygun eşleştirme yok. Aramayı veya filtreyi değiştir.' : 'Henüz eşleştirme yok. Yeni ilan bağla düğmesiyle istediğin ilanı ekleyebilirsin.';
  }
  document.getElementById('mapping-search').addEventListener('input', applyFilters);
  document.getElementById('panel-filter').addEventListener('change', applyFilters);
  document.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    filter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    applyFilters();
  }));
  applyFilters();
  const requested = new URLSearchParams(window.location.search).get('edit');
  if (requested && Object.prototype.hasOwnProperty.call(data.bindings, requested)) openEditor(requested);
})();
