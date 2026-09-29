/* Connects your ORIGINAL landing page to the admin database.
   It does not change the design: it only swaps in the content you upload.
   If the backend is off, the page keeps showing its original placeholder content. */
(async () => {
  let D;
  try { D = await (await fetch('/api/public')).json(); } catch (e) { return; }
  const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  /* 1. count the visit once per browser session */
  if (!sessionStorage.czVisit) { sessionStorage.czVisit = 1; fetch('/api/visit', { method: 'POST' }); }

  /* 2. hero background video */
  if (D.hero) {
    const v = document.querySelector('#home video');
    v.innerHTML = ''; v.src = D.hero.url; v.load(); v.play().catch(() => {});
  }

  /* 3. about-section slider pictures */
  if (D.slider.length) {
    const old = document.getElementById('about-slideshow-track');
    const t = document.createElement('div');
    t.className = old.className;
    const urls = D.slider.map(s => s.url);
    t.innerHTML = urls.concat(urls[0]).map(u => `<img src="${u}" alt="Art Director portrait" class="h-full w-full flex-shrink-0 object-cover">`).join('');
    old.replaceWith(t);
    let i = 0;
    setInterval(() => {
      i++; t.style.transform = `translateX(-${i * 100}%)`;
      if (i === urls.length) setTimeout(() => {
        t.style.transition = 'none'; i = 0; t.style.transform = 'translateX(0)';
        t.offsetHeight; t.style.removeProperty('transition');
      }, 700);
    }, 2200);
  }

  /* 4. brand marquee + contact subjects */
  const btn = 'text-2xl font-display font-bold hover:text-gray-400 transition-colors px-6 py-2 border border-white/10 rounded-full hover:border-white';
  if (D.brands.length) {
    const one = D.brands.map(b => `<button data-brand="${esc(b.name)}" class="${btn}">${esc(b.name.toUpperCase())}</button>`).join('');
    document.querySelector('.marquee-content').innerHTML = one + one;
  }
  const subj = document.querySelector('#contact-form select');
  if (subj) subj.innerHTML = D.sectors.map(s => `<option>${esc(s.name)}</option>`).join('') + '<option>Full Creative Direction</option>';

  /* 5. creatives: sectors -> items (same markup/classes as your original) */
  categories.length = 0;
  D.sectors.forEach((s, n) => categories.push({ id: 's' + s.id, title: `${n + 1}. ${s.name}`, items: D.items.filter(i => i.sector_id === s.id) }));
  let bf = null; const open = new Set(), expanded = new Set();

  const hdr = document.querySelector('#creatives .text-center');
  const bar = document.createElement('div');
  bar.className = 'hidden pt-2';
  hdr.appendChild(bar);

  const thumb = i => i.media_type === 'video'
    ? `<video src="${i.url}#t=0.5" muted preload="metadata" playsinline class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"></video><span class="absolute top-2 right-2 bg-black/70 text-white text-[10px] px-2 py-1 rounded-full">▶ VIDEO</span>`
    : `<img src="${i.url}" alt="${esc(i.title)}" class="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500">`;

  window.renderCategories = function () {
    bar.classList.toggle('hidden', !bf);
    bar.innerHTML = bf ? `<button id="czClear" class="px-5 py-2 bg-black text-white rounded-full text-xs font-medium hover:bg-gray-800">Showing: ${esc(bf)} &nbsp;✕ Clear filter</button>` : '';
    if (bf) document.getElementById('czClear').onclick = () => { bf = null; renderCategories(); };
    document.getElementById('creative-categories').innerHTML = categories.map(cat => {
      const list = bf ? cat.items.filter(i => i.brand === bf) : cat.items;
      const limit = expanded.has(cat.id) ? Infinity : 6, more = list.length > limit;
      const isOpen = open.has(cat.id) || (bf && list.length);
      return `<div class="border border-gray-200 rounded-2xl overflow-hidden bg-white shadow-sm transition-all duration-300">
        <button onclick="toggleAccordion('${cat.id}')" class="w-full px-8 py-6 text-left flex items-center justify-between hover:bg-gray-50 transition-colors">
          <span class="font-display text-xl md:text-2xl font-bold">${esc(cat.title)}</span>
          <div class="flex items-center gap-4"><span class="text-xs bg-gray-100 px-3 py-1 rounded-full text-gray-600 font-medium">${list.length} Projects</span>
          <i id="icon-${cat.id}" class="fa-solid fa-chevron-down text-gray-400 transition-transform duration-300 ${isOpen ? 'rotate-180' : ''}"></i></div></button>
        <div id="content-${cat.id}" class="${isOpen ? '' : 'hidden'} px-8 py-6 border-t border-gray-100 bg-gray-50/30">
          ${list.length ? `<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">${list.slice(0, limit).map(i => `
            <div data-cid="${i.id}" class="cz-card cursor-pointer group relative bg-white rounded-xl overflow-hidden border border-gray-200 shadow-sm hover:shadow-lg transition-all duration-300">
              <div class="aspect-video overflow-hidden relative">${thumb(i)}</div>
              <div class="p-4 flex justify-between items-center"><div><h4 class="font-bold text-sm group-hover:text-gray-600 transition-colors">${esc(i.title)}</h4><p class="text-xs text-gray-400 mt-1">${esc(i.brand)}</p></div>
              <i class="fa-solid fa-arrow-up-right-from-square text-xs text-gray-400 group-hover:text-black transition-colors"></i></div></div>`).join('')}</div>`
            : '<p class="text-center text-sm text-gray-400">No work added here yet.</p>'}
          ${more ? `<div class="mt-8 text-center"><button onclick="viewAllCategoryPage('${cat.id}')" class="px-6 py-3 bg-black text-white text-xs uppercase font-bold tracking-wider rounded-full hover:bg-gray-800 transition-all">View More (${list.length - limit} remaining)</button></div>` : ''}
        </div></div>`;
    }).join('');
    wire();
  };
  window.toggleAccordion = id => {
    const c = document.getElementById('content-' + id), ic = document.getElementById('icon-' + id);
    const hidden = c.classList.toggle('hidden'); ic.classList.toggle('rotate-180', !hidden);
    hidden ? open.delete(id) : open.add(id);
  };
  window.viewAllCategoryPage = id => { expanded.add(id); open.add(id); renderCategories(); };
  window.filterByBrand = b => { bf = b; renderCategories(); document.getElementById('creatives').scrollIntoView({ behavior: 'smooth' }); };

  /* 6. tracking: views + viewing time */
  const vis = new Set(), secs = {}, views = {}; let lb = null;
  const io = new IntersectionObserver(es => es.forEach(e => { const id = e.target.dataset.cid; e.isIntersecting ? vis.add(id) : vis.delete(id); }), { threshold: .6 });
  setInterval(() => {
    if (document.hidden) return;
    vis.forEach(id => secs[id] = (secs[id] || 0) + 1);
    if (lb) secs[lb] = (secs[lb] || 0) + 1;
  }, 1000);
  const flush = () => {
    if (!Object.keys(secs).length && !Object.keys(views).length) return;
    navigator.sendBeacon('/api/track', new Blob([JSON.stringify({ seconds: secs, views })], { type: 'application/json' }));
    for (const k in secs) delete secs[k]; for (const k in views) delete views[k];
  };
  setInterval(flush, 10000);
  document.addEventListener('visibilitychange', () => { if (document.hidden) flush(); });
  addEventListener('pagehide', flush);

  /* 7. lightbox */
  const box = document.createElement('div');
  box.className = 'hidden fixed inset-0 z-[10000] bg-black/90 flex items-center justify-center p-4';
  box.innerHTML = '<div class="max-w-4xl w-full"><div id="czMedia"></div><div class="flex items-center justify-between mt-3 text-white"><div><p id="czT" class="font-bold"></p><p id="czB" class="text-sm text-gray-400"></p></div><button id="czX" class="px-5 py-2 bg-white text-black rounded-full text-sm font-medium">Close</button></div></div>';
  document.body.appendChild(box);
  const close = () => { box.classList.add('hidden'); document.getElementById('czMedia').innerHTML = ''; lb = null; };
  box.onclick = e => { if (e.target === box) close(); };
  document.getElementById('czX').onclick = close;
  const show = id => {
    const i = D.items.find(x => x.id == id); if (!i) return;
    views[id] = (views[id] || 0) + 1; lb = String(id);
    document.getElementById('czMedia').innerHTML = i.media_type === 'video'
      ? `<video src="${i.url}" controls autoplay class="w-full max-h-[75vh] rounded-xl bg-black"></video>`
      : `<img src="${i.url}" alt="${esc(i.title)}" class="w-full max-h-[75vh] object-contain rounded-xl">`;
    document.getElementById('czT').textContent = i.title;
    document.getElementById('czB').textContent = i.brand;
    box.classList.remove('hidden');
  };

  /* 8. wire up new elements (clicks, tracking, your companion character) */
  function pounce(el) {
    el.addEventListener('mouseenter', () => { if (typeof companionActive !== 'undefined' && companionActive && companionPose !== 'sleeping' && !companionDragging) setCompanionPose('pounce'); });
    el.addEventListener('mouseleave', () => { if (typeof companionActive !== 'undefined' && companionActive && companionPose === 'pounce' && !companionDragging) setCompanionPose('active'); });
  }
  function wire() {
    io.disconnect(); vis.clear();
    document.querySelectorAll('.cz-card').forEach(el => { io.observe(el); el.onclick = () => show(el.dataset.cid); pounce(el); });
    document.querySelectorAll('#creative-categories button').forEach(pounce);
  }
  document.querySelectorAll('.marquee-content button').forEach(b => { b.onclick = () => filterByBrand(b.dataset.brand); pounce(b); });

  /* 9. contact form -> your backend -> Resend email */
  const form = document.getElementById('contact-form') || document.querySelector('#contact form');
  if (form) {
    form.removeAttribute('action'); form.removeAttribute('method');
    const trap = document.createElement('input');
    trap.type = 'text'; trap.name = 'website'; trap.tabIndex = -1; trap.autocomplete = 'off';
    trap.setAttribute('aria-hidden', 'true'); trap.style.cssText = 'position:absolute;left:-9999px;height:0;width:0;opacity:0';
    form.appendChild(trap);
    const note = document.createElement('p'); note.className = 'hidden'; form.appendChild(note);
    const sb = form.querySelector('button[type=submit]');
    form.addEventListener('submit', async e => {
      e.preventDefault();
      const label = sb.textContent; sb.disabled = true; sb.textContent = 'Sending...'; note.className = 'hidden';
      try {
        const r = await fetch('/api/contact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(new FormData(form))) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.error || 'Something went wrong. Please try again.');
        form.reset(); note.textContent = 'Message sent! Thank you, I will get back to you shortly.';
        note.className = 'text-sm text-center text-green-600 font-medium';
      } catch (err) { note.textContent = err.message; note.className = 'text-sm text-center text-red-600 font-medium'; }
      sb.disabled = false; sb.textContent = label;
    });
  }

  renderCategories();
})();
