const banner=document.querySelector('#offline');
function connectivity(){if(banner)banner.hidden=navigator.onLine;document.querySelectorAll('form[method="post"] button').forEach(b=>b.disabled=!navigator.onLine);}
window.addEventListener('online',connectivity);window.addEventListener('offline',connectivity);connectivity();
if('serviceWorker' in navigator)navigator.serviceWorker.register('/sw.js');
document.querySelectorAll('[data-confirm]').forEach(form=>form.addEventListener('submit',event=>{if(!confirm(form.dataset.confirm))event.preventDefault();}));
const search=document.querySelector('#admin-search');if(search)search.addEventListener('input',()=>{const q=search.value.toLocaleLowerCase('pt-BR');let found=0;document.querySelectorAll('.searchable').forEach(item=>{item.hidden=!item.textContent.toLocaleLowerCase('pt-BR').includes(q);if(!item.hidden)found++;});document.querySelector('#search-empty').hidden=found>0||!q;});

// Automatic five-second rotation; only the explicit pause control or a hidden tab stops it.
document.querySelectorAll('[data-carousel]').forEach(carousel=>{
 const slides=[...carousel.querySelectorAll('[data-slide]')];
 if(slides.length<2)return;
 const pause=carousel.querySelector('[data-pause]'),count=carousel.querySelector('[data-slide-count]');
 let index=0,paused=false,timer;
 function show(next){index=(next+slides.length)%slides.length;slides.forEach((slide,i)=>slide.hidden=i!==index);count.textContent=`${index+1} / ${slides.length}`;}
 function schedule(){clearInterval(timer);pause.textContent=paused?'Iniciar rotação':'Pausar rotação';pause.setAttribute('aria-pressed',String(paused));if(!paused&&!document.hidden)timer=setInterval(()=>show(index+1),5000);}
 carousel.querySelector('[data-previous]').addEventListener('click',()=>{show(index-1);schedule();});
 carousel.querySelector('[data-next]').addEventListener('click',()=>{show(index+1);schedule();});
 pause.addEventListener('click',()=>{paused=!paused;schedule();});
 document.addEventListener('visibilitychange',schedule);schedule();
});
