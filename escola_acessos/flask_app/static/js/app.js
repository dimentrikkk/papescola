/* Pequenos efeitos: contadores animados, menu móvel, mensagens. Sem dependências. */
(function () {
  const reduzir = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Contadores: <strong data-count="42">
  document.querySelectorAll('[data-count]').forEach(el => {
    const alvo = parseInt(el.dataset.count, 10) || 0;
    if (reduzir || alvo === 0) { el.textContent = alvo; return; }
    const dur = 900, t0 = performance.now();
    const passo = t => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(alvo * e);
      if (p < 1) requestAnimationFrame(passo);
    };
    requestAnimationFrame(passo);
  });

  // Menu lateral em ecrãs pequenos
  const btn = document.querySelector('.menu-btn'), scrim = document.querySelector('.scrim');
  if (btn) btn.addEventListener('click', () => document.body.classList.toggle('nav-open'));
  if (scrim) scrim.addEventListener('click', () => document.body.classList.remove('nav-open'));

  // Mensagens: fecham ao clicar; as que trazem passwords temporárias não desaparecem sozinhas
  document.querySelectorAll('.flash').forEach(el => {
    el.addEventListener('click', () => el.remove());
    if (el.textContent.includes('temporária')) el.classList.add('sticky');
    else setTimeout(() => { el.style.transition = 'opacity .4s, transform .4s'; el.style.opacity = '0'; el.style.transform = 'translateX(30px)'; setTimeout(() => el.remove(), 450); }, 6000);
  });

  // Dias do horário: ativar/desativar campos
  document.querySelectorAll('.dia-edit input[type=checkbox]').forEach(cb => {
    const row = cb.closest('.dia-edit');
    const sync = () => row.classList.toggle('off', !cb.checked);
    cb.addEventListener('change', sync); sync();
  });
  const copiar = document.getElementById('copiarSegunda');
  if (copiar) copiar.addEventListener('click', () => {
    const lin = document.querySelectorAll('.dia-edit');
    const e0 = lin[0].querySelector('[name^=entrada_]').value, s0 = lin[0].querySelector('[name^=saida_]').value;
    for (let i = 1; i < 5 && i < lin.length; i++) {
      lin[i].querySelector('input[type=checkbox]').checked = true;
      lin[i].querySelector('[name^=entrada_]').value = e0; lin[i].querySelector('[name^=saida_]').value = s0;
      lin[i].classList.remove('off');
    }
  });
})();
