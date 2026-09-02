(function(){
  'use strict';
  const root=document.documentElement;
  let saved=null;
  try{saved=localStorage.getItem('studyplay-theme')}catch(e){}
  root.dataset.theme=saved||'dark';

  function syncTheme(){
    document.querySelectorAll('[data-theme-toggle]').forEach(b=>{
      const dark=root.dataset.theme==='dark';
      b.setAttribute('aria-pressed',String(dark));
      b.textContent=dark?'☀️':'🌙';
      b.title=dark?'Жарық режим':'Қараңғы режим';
      b.setAttribute('aria-label',dark?'Жарық режимге ауысу':'Қараңғы режимге ауысу');
    });
  }
  syncTheme();
  document.querySelectorAll('[data-theme-toggle]').forEach(b=>b.addEventListener('click',()=>{
    const next=root.dataset.theme==='dark'?'light':'dark';
    root.dataset.theme=next;
    try{localStorage.setItem('studyplay-theme',next)}catch(e){}
    syncTheme();
  }));

  window.toast=function(msg,type='success'){
    let box=document.getElementById('toastBox');
    if(!box){box=document.createElement('div');box.id='toastBox';box.className='toast-box';document.body.appendChild(box)}
    const t=document.createElement('div');t.className='toast '+type;t.setAttribute('role','status');t.textContent=msg;box.appendChild(t);
    setTimeout(()=>t.remove(),3200);
  };

  document.querySelectorAll('.btn').forEach(b=>b.addEventListener('click',()=>{
    if(!b.disabled){b.classList.add('pressed');setTimeout(()=>b.classList.remove('pressed'),140)}
  }));

  // Safe modal manager. It never leaves a backdrop/scroll lock behind.
  let modalLocks=0;
  let previousOverflow='';
  let previousPosition='';
  let previousTop='';
  let previousWidth='';
  let lockedScrollY=0;
  function getModal(){return document.getElementById('modal')}
  function lockScroll(){
    if(modalLocks===0){
      previousOverflow=document.body.style.overflow;
      previousPosition=document.body.style.position;
      previousTop=document.body.style.top;
      previousWidth=document.body.style.width;
      lockedScrollY=window.scrollY||document.documentElement.scrollTop||0;
      document.body.style.overflow='hidden';
      // iOS Safari: fixed-body locking prevents the page from scrolling behind the modal.
      document.body.style.position='fixed';
      document.body.style.top=(-lockedScrollY)+'px';
      document.body.style.width='100%';
    }
    modalLocks++;
  }
  function unlockScroll(){
    if(modalLocks>0)modalLocks--;
    if(modalLocks===0){
      document.body.style.overflow=previousOverflow;
      document.body.style.position=previousPosition;
      document.body.style.top=previousTop;
      document.body.style.width=previousWidth;
      window.scrollTo(0,lockedScrollY);
    }
  }
  function ensureBody(m){
    let body=m.querySelector('#modalBody');
    if(!body){body=document.createElement('div');body.id='modalBody';m.querySelector('.modal-box').appendChild(body)}
    return body;
  }
  function showModalLoading(message='⏳ Жүктелуде...'){
    const m=getModal();if(!m)return;
    const body=ensureBody(m);
    body.innerHTML='<div class="modal-state"><div class="modal-spinner" aria-hidden="true"></div><h2>Мәліметтер</h2><p>'+message+'</p></div>';
    if(m.hidden){m.hidden=false;lockScroll()}
    requestAnimationFrame(()=>m.classList.add('is-open'));
  }
  function closeModal(m=getModal()){
    if(!m || m.hidden)return;
    m.classList.remove('is-open');
    m.hidden=true;
    unlockScroll();
    const body=m.querySelector('#modalBody');
    if(body)body.innerHTML='<div class="modal-state"><div class="modal-spinner" aria-hidden="true"></div><p>Мәліметтер жүктелуде...</p></div>';
  }
  function showModalError(retry){
    const m=getModal();if(!m)return;
    const body=ensureBody(m);
    body.innerHTML='<div class="modal-state error-state"><div class="modal-error-icon">😕</div><h2>Бірдеңе дұрыс болмады</h2><p>Мәліметті жүктеу мүмкін болмады. Қайта көріңіз немесе терезені жабыңыз.</p><div class="modal-actions"><button type="button" class="btn primary" id="modalRetry">Қайта көру</button><button type="button" class="btn" data-modal-close>Жабу</button></div></div>';
    const r=body.querySelector('#modalRetry');if(r&&retry)r.onclick=retry;
    body.querySelector('[data-modal-close]')?.addEventListener('click',()=>closeModal(m));
  }
  window.openStudyModal=function(renderOrMessage){
    const m=getModal();if(!m)return null;
    if(m.hidden){m.hidden=false;lockScroll()}
    m.classList.add('is-open');
    const body=ensureBody(m);
    if(typeof renderOrMessage==='string')body.innerHTML='<div class="modal-state"><p>'+renderOrMessage+'</p></div>';
    else if(typeof renderOrMessage==='function'){
      try{renderOrMessage(body)}catch(e){console.error('Modal render error',e);showModalError()}
    }
    return m;
  };
  window.closeStudyModal=closeModal;
  window.showModalLoading=showModalLoading;
  window.showModalError=showModalError;

  document.querySelectorAll('[data-modal-close]').forEach(b=>b.addEventListener('click',()=>closeModal(b.closest('.modal'))));
  document.querySelectorAll('.modal').forEach(m=>{
    if(!m.hidden)m.hidden=true;
    m.addEventListener('click',e=>{if(e.target===m)closeModal(m)});
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){const m=getModal();if(m&&!m.hidden)closeModal(m)}});
  window.addEventListener('pagehide',()=>{modalLocks=0;document.body.style.overflow=previousOverflow||'';document.body.style.position=previousPosition||'';document.body.style.top=previousTop||'';document.body.style.width=previousWidth||''});

  document.querySelectorAll('.server-flashes .toast-inline').forEach(t=>setTimeout(()=>{t.style.opacity='0';t.style.transform='translateY(-6px)'},3500));
})();
