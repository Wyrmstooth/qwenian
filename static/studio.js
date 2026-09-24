'use strict';
const $ = id => document.getElementById(id);
const terminal = new Set(['done', 'error', 'cancelled']);
const state = {mode: 'create', refs: [], batches: [], legacy: [], selected: null, config: null, submitting: false, galleryKey: '', jobsKey: ''};
const modeCopy = {
  create: ['Describe your image', 'Be specific about the subject, composition, lighting, and mood.', 'A sunlit editorial photograph of a quiet coastal home, linen curtains, warm stone, soft morning light. Wide composition, with the sea visible through an open window.'],
  ui: ['Design your next interface', 'Describe the screen, sections, layout, and content. This creates a visual mockup as an image.', 'A desktop dashboard for a personal finance app called FOLIO. Warm ivory background, dark forest-green sidebar, three summary cards across the top, a spending chart below, and a short recent transactions list. A spacious 12-column grid, consistent rounded cards, crisp sans-serif labels. Straight-on UI, no device frame.'],
  graphics: ['Give your message a shape', 'Describe the format, focal point, hierarchy, and exact words. Graphics are exported as raster PNGs.', 'A minimalist exhibition poster for a ceramic art show. One sculptural terracotta vase centered on warm cream, a large headline at the top reading FORM & EARTH, and a small date at the bottom reading OCTOBER 12. Restrained typography, generous margins, balanced editorial layout.'],
  product: ['Make the product the hero', 'Specify materials, geometry, viewing angle, background, and lighting.', 'A premium amber glass skincare bottle with a matte ivory cap. A simple cream label reading SOL. Centered on a warm stone pedestal against a soft beige studio background. Three-quarter view, broad diffused light from the left, realistic glass reflections, one bottle only.'],
  illustration: ['Build a world of your own', 'Describe the subject, pose, composition, medium, and visual style.', 'A charming gouache illustration of a small orange fox curled up beside a blue teapot in a cozy woodland kitchen. Clearly separated silhouettes, warm muted colors, visible brush texture, gentle morning light, a simple uncluttered composition.'],
  edit: ['Give an image a new direction', 'Add image 1, then describe only what should change. Keep matching proportions on for aligned edits.', 'Keep the subject, pose, framing, and all foreground details in image 1. Replace only the background with a softly lit cream studio backdrop. Match the existing direction of light and preserve natural edges.'],
  design: ['Keep the direction. Change the details.', 'Use image 1 as the master design. State what should stay and precisely what should change.', 'Preserve image 1’s packaging proportions, layout, typography style, and material finish. Change only the brand name to NOVA and the accent color to deep forest green. Keep every other design element in place.'
  ]
};

function safeStore(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} }
function stored(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }
function escapeHTML(value) { return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function showError(message) { $('error').textContent = message; $('error').hidden = false; }
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 3500); }
async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({error: `Request failed (${response.status}).`}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}
async function downloadFile(src, name) {
  const response = await fetch(src);
  if (!response.ok) { const detail = await response.json().catch(() => ({})); throw new Error(detail.error || 'Could not download this file.'); }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
function fields() {
  const data = {};
  for (const element of $('generationForm').elements) {
    if (!element.name || element.type === 'file') continue;
    data[element.name] = element.type === 'checkbox' ? element.checked : element.value;
  }
  data.mode = state.mode;
  return data;
}
function formData(withReferences = true) {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields())) data.append(key, String(value));
  if (withReferences) for (const ref of state.refs) {
    if (ref.saved) data.append('saved_references', ref.saved);
    else data.append('references', ref.file);
  }
  return data;
}
function setMode(mode, persist = true) {
  if (!modeCopy[mode]) mode = 'create';
  state.mode = mode;
  document.querySelectorAll('[data-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.mode === mode)));
  const [title, hint, placeholder] = modeCopy[mode];
  $('briefTitle').textContent = title; $('modeHint').textContent = hint; $('prompt').placeholder = placeholder;
  $('designOptions').hidden = mode !== 'design';
  $('referenceHint').hidden = !state.refs.length && !['edit','design'].includes(mode);
  updateControls(persist);
}
function setQuality(quality) {
  $('quality').value = quality;
  document.querySelectorAll('[data-quality]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.quality === quality)));
}
function updateControls(persist = true) {
  const steps = $('steps').value || ({draft:24, balanced:40, detailed:50}[$('quality').value]);
  $('stepsHint').textContent = `${steps} steps`;
  $('qualityNote').textContent = $('quality').value === 'draft' ? 'For exploring ideas. Fewer steps can reduce detail and consistency.' : $('quality').value === 'detailed' ? 'Extra refinement time. Results still depend on the brief and seed.' : 'Recommended settings for finished images.';
  const sizes = state.config?.sizes || {square:[1024,1024],portrait:[896,1152],landscape:[1152,896],wide:[1344,768],tall:[768,1344]};
  const scale = ({standard:1024,large:1280,high:1440}[$('resolution').value]) / 1024;
  const size = sizes[$('shape').value].map(n => Math.round(n * scale / 32) * 32);
  const match = !!state.refs.length && $('match_size').checked;
  $('shape').disabled = match;
  $('sizeHint').textContent = match ? 'Canvas follows image 1; resolution controls the pixel budget.' : `${size[0]} × ${size[1]} · ${scale === 1 ? 'best fit for 8 GB VRAM' : 'uses more memory and takes longer'}`;
  const count = Number($('count').value);
  if (!state.submitting) $('generate').innerHTML = `Generate ${count} image${count === 1 ? '' : 's'} <span>↗</span>`;
  $('charCount').textContent = `${$('prompt').value.length.toLocaleString()} / 12,000`;
  if (persist) safeStore('qwen-studio-draft-v2', fields());
  clearTimeout(updateControls.timer);
  updateControls.timer = setTimeout(previewPrompt, 300);
}
let previewSequence = 0;
async function previewPrompt() {
  const sequence = ++previewSequence;
  if (!$('prompt').value.trim()) { $('effectivePrompt').textContent = 'Write a brief to see the final prompt.'; return; }
  try {
    const data = await api('/api/preview', {method:'POST', body:formData(false)});
    if (sequence === previewSequence) $('effectivePrompt').textContent = data.prompt;
  } catch (error) { if (sequence === previewSequence) $('effectivePrompt').textContent = error.message; }
}
function releaseRefs() { state.refs.forEach(ref => { if (ref.file) URL.revokeObjectURL(ref.url); }); state.refs = []; }
function renderRefs() {
  $('references').replaceChildren();
  state.refs.forEach((ref, index) => {
    const tile = document.createElement('div'); tile.className = 'ref-tile';
    const img = document.createElement('img'); img.src = ref.url; img.alt = `Reference image ${index + 1}`;
    const number = document.createElement('span'); number.className = 'ref-number'; number.textContent = String(index + 1);
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', `Remove reference ${index + 1}`);
    remove.onclick = () => { if (ref.file) URL.revokeObjectURL(ref.url); state.refs.splice(index,1); renderRefs(); };
    tile.append(img,number,remove); $('references').append(tile);
  });
  $('refCount').textContent = `${state.refs.length} / 10`;
  $('clearRefs').hidden = !state.refs.length; $('matchRow').hidden = !state.refs.length;
  $('referenceHint').hidden = !state.refs.length && !['edit','design'].includes(state.mode);
  updateControls();
}
function addFiles(files) {
  for (const file of files) {
    if (state.refs.length >= 10) { showError('You can add up to 10 reference images.'); break; }
    if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { showError('Use PNG, JPEG, or WebP reference images.'); continue; }
    if (file.size > 20 * 1024 ** 2) { showError(`${file.name} exceeds the 20 MB limit.`); continue; }
    state.refs.push({file, url:URL.createObjectURL(file)});
  }
  renderRefs();
}
function applySettings(settings, refs = []) {
  for (const [name, value] of Object.entries(settings)) {
    const element = $(name);
    if (!element || !element.name) continue;
    if (element.type === 'checkbox') element.checked = !!value;
    else element.value = String(value ?? '');
  }
  setQuality(settings.quality || 'balanced');
  releaseRefs(); state.refs = refs.map(saved => ({saved, url:`/api/reference/${saved}`}));
  setMode(settings.mode || 'create', false); renderRefs();
  $('advanced').open = !!$('negative_prompt').value || Number($('cfg').value) > 1;
}
function duration(seconds) {
  seconds = Math.max(0, Math.round(seconds));
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds/60)}m ${seconds%60}s`;
}
function findImage(src) {
  for (const batch of state.batches) for (const item of batch.items) if (item.images.includes(src)) return {src,batch,item};
  return {src,batch:null,item:null};
}
function selectImage(src, scroll = false) {
  const selected = findImage(src); state.selected = selected;
  $('previewImage').src = src; $('previewImage').hidden = false; $('emptyPreview').hidden = true; $('previewOpen').disabled = false;
  $('resultInfo').hidden = false; $('resultActions').hidden = false;
  $('download').href = src; $('download').download = selected.item ? `qwen-${selected.item.seed}.png` : `qwen-studio.png`;
  $('resultTitle').textContent = selected.batch ? `${state.config?.modes[selected.batch.settings.mode]?.label || 'Image'} · Variation ${selected.item.index + 1}` : 'From your collection';
  $('resultMeta').textContent = selected.batch ? `${selected.batch.width} × ${selected.batch.height} · Seed ${selected.item.seed} · ${selected.batch.settings.steps} steps${selected.item.ended_at && selected.item.started_at ? ' · ' + duration(selected.item.ended_at - selected.item.started_at) : ''}` : 'Previously generated image';
  $('reuse').disabled = $('variation').disabled = !selected.batch;
  safeStore('qwen-studio-selected', src);
  if (scroll) document.querySelector('.results').scrollIntoView({behavior:'smooth', block:'start'});
}
function restoreSelected(variations = false) {
  if (!state.selected?.batch) return;
  const {batch,item} = state.selected;
  applySettings({...batch.settings, seed:variations ? '' : item.seed, count:variations ? 4 : 1}, batch.references);
  document.querySelector('.composer').scrollIntoView({behavior:'smooth', block:'start'});
  toast(variations ? 'Ready for new variations. Review the brief and generate.' : 'Settings and references restored.');
}
function renderJobs() {
  const active = state.batches.filter(b => b.status === 'working');
  const remaining = active.reduce((sum,b) => sum + b.items.length - b.finished, 0);
  $('queueCount').textContent = remaining ? `${remaining} image${remaining === 1 ? '' : 's'} remaining` : 'All clear';
  $('clearQueue').hidden = !state.batches.some(b => b.items.some(item => item.status === 'queued'));
  const visible = [...active, ...state.batches.filter(b => b.status !== 'working').slice(0,4)];
  const markup = visible.map(batch => {
    const items = batch.items.map(item => {
      let text = item.status === 'queued' ? `Queued${item.queue_position ? ' · position ' + item.queue_position : ''}` : item.status === 'running' ? `${item.stage || 'Preparing'}${item.step ? ` · ${item.step}/${item.total_steps}` : ''}` : item.status === 'done' ? `Complete · seed ${item.seed}` : item.status === 'error' ? item.error || 'Generation failed' : item.status === 'cancelled' ? 'Cancelled' : item.status === 'checking' ? 'Checking submission with the engine…' : 'Submitting…';
      if (item.status === 'running' && item.started_at) text += ` · ${duration(Date.now()/1000 - item.started_at)}`;
      return `<div class="job-item">${item.images.length ? `<button type="button" data-image="${escapeHTML(item.images[0])}" aria-label="View variation ${item.index+1}"><img src="${escapeHTML(item.images[0])}" alt="Variation ${item.index+1}" loading="lazy"></button>` : `<span class="item-index">${String(item.index+1).padStart(2,'0')}</span>`}<div class="item-info"><p class="${item.status === 'error' ? 'item-error' : ''}">${escapeHTML(text)}</p>${!terminal.has(item.status) ? `<progress aria-label="Image ${item.index+1} sampling progress" max="1" ${item.progress ? `value="${item.progress}"` : ''}></progress>` : ''}</div>${item.status === 'queued' ? `<button class="text-button remove-item" type="button" data-remove-item="${batch.id}:${item.index}" aria-label="Remove variation ${item.index+1}">Remove</button>` : ''}</div>`;
    }).join('');
    return `<article class="job-card"><div class="job-header"><strong>${escapeHTML(state.config?.modes[batch.settings.mode]?.label || 'Image')} · ${batch.items.length} image${batch.items.length===1?'':'s'}</strong><span>${batch.completed}/${batch.items.length} complete</span></div><p class="job-prompt" title="${escapeHTML(batch.settings.prompt)}">${escapeHTML(batch.settings.prompt)}</p>${items}<div class="job-actions">${batch.status === 'working' ? `<button class="text-button" type="button" data-cancel="${batch.id}">Cancel remaining</button>` : ''}<button class="text-button" type="button" data-reuse="${batch.id}">Reuse brief</button>${batch.images.length ? `<button class="text-button" type="button" data-download="${batch.id}">Download batch ↓</button>` : ''}<button class="text-button" type="button" data-settings="${batch.id}">Save settings</button></div></article>`;
  }).join('') || '<p class="queue-empty">Your next batch starts with a brief.</p>';
  if (markup !== state.jobsKey) { $('jobs').innerHTML = markup; state.jobsKey = markup; }
}
function renderGallery() {
  const filter = $('galleryFilter').value;
  const images = [], known = new Set();
  for (const batch of state.batches) for (const item of batch.items) for (const src of item.images) {
    known.add(src);
    if (filter === 'all' || filter === batch.settings.mode) images.push({src, label:state.config?.modes[batch.settings.mode]?.label || 'Image', meta:`Seed ${item.seed}`});
  }
  if (filter === 'all') for (const src of state.legacy) if (!known.has(src)) images.push({src,label:'Image',meta:'From your collection'});
  $('galleryCount').textContent = String(new Set([...known, ...state.legacy]).size);
  const markup = images.map(({src,label,meta}) => `<button type="button" class="gallery-card" data-image="${escapeHTML(src)}" aria-label="View ${escapeHTML(label)} ${escapeHTML(meta)}"><img src="${escapeHTML(src)}" alt="${escapeHTML(label)} creation" loading="lazy"><span class="caption">${escapeHTML(label)}<small>${escapeHTML(meta)}</small></span></button>`).join('');
  if (markup !== state.galleryKey) { $('gallery').innerHTML = markup; state.galleryKey = markup; }
  $('galleryEmpty').hidden = images.length > 0;
  $('galleryEmpty').textContent = filter === 'all' ? 'A fresh canvas. Finished images will be saved here.' : 'No creations in this category yet.';
}
let firstPoll = true;
async function poll() {
  try {
    const previous = new Set(state.batches.flatMap(b => b.images));
    const data = await api('/api/batches'); state.batches = data.batches;
    $('connectionNote').hidden = true;
    renderJobs(); renderGallery();
    const fresh = state.batches.flatMap(b => b.images).find(src => !previous.has(src));
    if (firstPoll) {
      const saved = stored('qwen-studio-selected', null);
      const all = [...state.batches.flatMap(b => b.images), ...state.legacy];
      if (saved && all.includes(saved)) selectImage(saved);
      else if (all.length) selectImage(all[0]);
    } else if (fresh) { selectImage(fresh); toast('A new image is ready.'); }
    firstPoll = false;
  } catch { $('connectionNote').hidden = false; }
  setTimeout(poll, state.batches.some(b => b.status === 'working') ? 1800 : 5000);
}
async function checkHealth() {
  try {
    const health = await api('/api/health');
    $('engine').className = 'status'; $('engine').textContent = 'LOCAL ENGINE READY'; $('engine').title = health.device;
    $('offline').hidden = true; $('gpuLabel').textContent = `${health.vram_gb} GB VRAM · ${health.running ? 'Generating' : 'Ready'}${health.queued ? ` · ${health.queued} queued` : ''}`;
  } catch (error) {
    $('engine').className = 'status offline'; $('engine').textContent = 'ENGINE OFFLINE'; $('engine').title = error.message;
    $('offline').hidden = false; $('gpuLabel').textContent = 'Local engine unavailable';
  }
  setTimeout(checkHealth, 15000);
}

$('modes').onclick = event => { const button = event.target.closest('[data-mode]'); if (button) setMode(button.dataset.mode); };
$('qualities').onclick = event => { const button = event.target.closest('[data-quality]'); if (button) { setQuality(button.dataset.quality); $('steps').value = ''; updateControls(); } };
$('generationForm').addEventListener('input', () => updateControls());
$('generationForm').addEventListener('change', () => updateControls());
$('randomSeed').onclick = () => { $('seed').value = ''; updateControls(); toast('A new random seed will be chosen for each batch.'); };
$('example').onclick = () => { if (!$('prompt').value.trim() || $('prompt').value === $('prompt').placeholder) { $('prompt').value = modeCopy[state.mode][2]; updateControls(); } else { $('prompt').focus(); toast('Clear the current brief to insert an example.'); } };
$('refs').onchange = event => { addFiles(event.target.files); event.target.value = ''; };
$('clearRefs').onclick = () => { releaseRefs(); renderRefs(); };
$('dropzone').ondragover = event => { event.preventDefault(); $('dropzone').classList.add('dragging'); };
$('dropzone').ondragleave = () => $('dropzone').classList.remove('dragging');
$('dropzone').ondrop = event => { event.preventDefault(); $('dropzone').classList.remove('dragging'); addFiles(event.dataTransfer.files); };
$('generationForm').onsubmit = async event => {
  event.preventDefault(); if (state.submitting) return;
  if (['edit','design'].includes(state.mode) && !state.refs.length) { showError('Add a reference image before generating in this mode.'); return; }
  if ($('negative_prompt').value.trim() && Number($('cfg').value) === 1) { $('advanced').open = true; showError('Negative prompts need guidance above 1. Increase guidance or clear the negative prompt.'); return; }
  state.submitting = true; $('generate').disabled = true; $('generate').textContent = 'Adding to queue…'; $('error').hidden = true;
  try {
    const batch = await api('/api/generate', {method:'POST', body:formData()});
    state.batches = [batch, ...state.batches.filter(b => b.id !== batch.id)]; renderJobs();
    // Reuse stable normalized filenames on subsequent submissions. This also makes
    // prompt encoding eligible for ComfyUI's cache across repeated variations.
    releaseRefs(); state.refs = batch.references.map(saved => ({saved,url:`/api/reference/${saved}`})); renderRefs();
    toast(`Batch queued · starting seed ${batch.settings.seed}`);
  } catch (error) { showError(error.message); }
  finally { state.submitting = false; $('generate').disabled = false; updateControls(); }
};
document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); $('generationForm').requestSubmit(); } });
$('gallery').onclick = event => { const button = event.target.closest('[data-image]'); if (button) selectImage(button.dataset.image, true); };
$('jobs').onclick = async event => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.dataset.image) { selectImage(button.dataset.image); return; }
  if (button.dataset.removeItem) {
    const [batchId, index] = button.dataset.removeItem.split(':'); button.disabled = true;
    try { const updated = await api(`/api/job/${batchId}/item/${index}/cancel`, {method:'POST'}); state.batches = state.batches.map(b => b.id === batchId ? updated : b); state.jobsKey = ''; renderJobs(); }
    catch (error) { button.disabled = false; showError(error.message); }
    return;
  }
  const id = button.dataset.cancel || button.dataset.reuse || button.dataset.settings || button.dataset.download;
  const batch = state.batches.find(b => b.id === id); if (!batch) return;
  if (button.dataset.reuse) { applySettings(batch.settings, batch.references); toast('Brief, settings, and references restored.'); }
  if (button.dataset.settings) { const url = URL.createObjectURL(new Blob([JSON.stringify(batch,null,2)],{type:'application/json'})); const link = document.createElement('a'); link.href = url; link.download = `qwen-settings-${batch.id.slice(0,8)}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000); }
  if (button.dataset.download) {
    button.disabled = true;
    try {
      await downloadFile(`/api/job/${id}/download`, `qwenian-${id.slice(0,8)}.zip`);
    } catch(error) { showError(error.message); }
    finally { button.disabled = false; }
  }
  if (button.dataset.cancel) {
    button.disabled = true; button.textContent = 'Cancelling…';
    try { const updated = await api(`/api/job/${id}/cancel`,{method:'POST'}); state.batches = state.batches.map(b => b.id === id ? updated : b); state.jobsKey = ''; renderJobs(); toast('Cancellation requested for this batch.'); }
    catch(error) { button.disabled = false; button.textContent = 'Cancel remaining'; showError(error.message); }
  }
};
$('reuse').onclick = () => restoreSelected(false); $('variation').onclick = () => restoreSelected(true);
$('download').onclick = async event => {
  event.preventDefault();
  if (state.selected) try { await downloadFile(state.selected.src, $('download').download); } catch(error) { showError(error.message); }
};
$('copyImage').onclick = async () => {
  if (!state.selected) return;
  try {
    const response = await fetch(state.selected.src);
    if (!response.ok) throw new Error('Could not load this image.');
    await navigator.clipboard.write([new ClipboardItem({'image/png':await response.blob()})]);
    toast('Image copied.');
  } catch { toast('Clipboard access is unavailable. Download the PNG instead.'); }
};
$('useReference').onclick = async () => {
  if (!state.selected) return;
  try {
    const response = await fetch(state.selected.src); if (!response.ok) throw new Error('Could not load this image.');
    const blob = await response.blob(); releaseRefs(); addFiles([new File([blob],'result.png',{type:'image/png'})]);
    $('prompt').value = ''; $('match_size').checked = true; setMode('edit'); document.querySelector('.composer').scrollIntoView({behavior:'smooth'}); $('prompt').focus();
  } catch(error) { showError(error.message); }
};
$('previewOpen').onclick = () => { if (!state.selected) return; $('fullImage').src = state.selected.src; $('lightbox').showModal(); };
$('closeLightbox').onclick = () => $('lightbox').close();
$('lightbox').onclick = event => { if (event.target === $('lightbox')) $('lightbox').close(); };
$('galleryFilter').onchange = renderGallery;
$('clearQueue').onclick = async () => {
  $('clearQueue').disabled = true;
  try { const result = await api('/api/queue/clear', {method:'POST'}); state.batches = result.batches; state.jobsKey = ''; renderJobs(); toast(`Removed ${result.removed} queued generation${result.removed === 1 ? '' : 's'}.`); }
  catch (error) { showError(error.message); }
  finally { $('clearQueue').disabled = false; }
};
function setCollection(open) {
  $('collectionBody').hidden = !open;
  $('collectionToggle').setAttribute('aria-expanded', String(open));
  $('collectionToggle').firstChild.textContent = open ? 'Hide collection ' : 'Show collection ';
}
$('collectionToggle').onclick = () => setCollection($('collectionBody').hidden);
$('galleryToggle').onclick = () => { setCollection(true); $('gallerySection').scrollIntoView({behavior:'smooth'}); };

async function init() {
  const draft = stored('qwen-studio-draft-v2', null);
  if (draft) applySettings(draft); else updateControls(false);
  try { state.config = await api('/api/config'); updateControls(false); } catch(error) { showError(error.message); }
  try { state.legacy = (await api('/api/recent')).images; } catch {}
  checkHealth(); poll();
}
init();
