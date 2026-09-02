(function(){
 const root=document.documentElement;
 const saved=localStorage.getItem('studyplay-theme'); if(saved) root.dataset.theme=saved;
 document.querySelectorAll('[data-theme-toggle]').forEach(b=>{b.textContent=root.dataset.theme==='dark'?'☀️':'🌙';b.onclick=()=>{const next=root.dataset.theme==='dark'?'light':'dark';root.dataset.theme=next;localStorage.setItem('studyplay-theme',next);document.querySelectorAll('[data-theme-toggle]').forEach(x=>x.textContent=next==='dark'?'☀️':'🌙')}});
 window.toast=function(msg,type='success'){let box=document.getElementById('toastBox');if(!box){box=document.createElement('div');box.id='toastBox';box.className='toast-box';document.body.appendChild(box)}const t=document.createElement('div');t.className='toast '+type;t.textContent=msg;box.appendChild(t);setTimeout(()=>t.remove(),3200)};
 document.querySelectorAll('.btn').forEach(b=>b.addEventListener('click',()=>{b.classList.add('pressed');setTimeout(()=>b.classList.remove('pressed'),140)}));
})();
