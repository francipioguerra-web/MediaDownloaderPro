/* Gestures are scoped to the completed carousel under the pointer. */
(function(root){
  'use strict';
  root.createCarouselCatalogSpring=function(){
    const registered=new WeakSet(), entries=new WeakMap();
    const threshold=242;
    const wheelEndDelay=550;
    let active=null, pull=0, ready=false, releasing=false, wheelReadyAt=0;
    let idle=null, animation=null, touch=null, mouse=null, preview=null, suppressClick=false;
    const atEnd=track=>track.scrollWidth-track.clientWidth>2 && track.scrollLeft>=track.scrollWidth-track.clientWidth-Math.max(3,track.querySelector('.row-catalog-end')?.offsetWidth||0);
    const usable=()=>{
      if(!active?.track.isConnected || !active.end.isConnected || (!preview&&!atEnd(active.track)))return false;
      if(active.track.closest('.hidden') || document.querySelector('.modal-overlay:not(.hidden), .player-overlay:not(.hidden), dialog[open], .profiles-gate-modal:not(.hidden)'))return false;
      const rect=active.track.getBoundingClientRect();
      return rect.bottom>0 && rect.top<window.innerHeight;
    };
    const paint=()=>{
      if(!active)return;
      if(!preview){
        preview=document.createElement('div');preview.className='catalog-drag-preview';
        preview.setAttribute('aria-hidden','true');preview.inert=true;
        const heading=document.createElement('h1');
        heading.textContent=active.track.closest('section, .home-row-section, .personal-shelf')?.querySelector('h2')?.textContent||'Catalogo completo';
        const grid=document.createElement('div');grid.className='catalog-drag-preview__grid';
        active.track.querySelectorAll(':scope > .card, :scope > .rank-card, :scope > .resume-card, :scope > .personal-favorite').forEach(card=>{
          const copy=card.cloneNode(true);copy.removeAttribute('id');copy.querySelectorAll('[id]').forEach(el=>el.removeAttribute('id'));
          grid.appendChild(copy);
        });
        preview.append(heading,grid);document.body.appendChild(preview);
      }
      const distance=Math.min(window.innerWidth,Math.max(0,pull));
      preview.style.transform=`translateX(${window.innerWidth-distance}px)`;
      active.hint.textContent=ready?'Rilascia per aprire il catalogo':'Trascina verso sinistra per aprire il catalogo';
    };
    const reset=()=>{
      clearTimeout(idle);animation?.cancel();animation=null;
      preview?.remove();preview=null;
      if(active)active.hint.textContent='Scorri o trascina ancora per aprire il catalogo';
      active=null;pull=0;ready=false;releasing=false;touch=null;
    };
    const activate=entry=>{
      if(active===entry)return;
      reset();active=entry;wheelReadyAt=performance.now()+wheelEndDelay;
    };
    const release=()=>{
      clearTimeout(idle);
      if(!active||releasing)return;
      if(!usable()){reset();return;}
      const entry=active, shouldOpen=ready;
      releasing=true;
      const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const finish=async()=>{
        if(active!==entry)return;
        const canOpen=shouldOpen&&usable();
        try{if(canOpen)await entry.open();}finally{
          if(active===entry){reset();if(!shouldOpen)active=entry;}
        }
      };
      if(reduced||!preview?.animate){finish();return;}
      animation=preview.animate([
        {transform:preview.style.transform},
        {transform:shouldOpen?'translateX(0px)':`translateX(${window.innerWidth}px)`}
      ],{duration:shouldOpen?320:220,easing:'cubic-bezier(.2,.7,.2,1)',fill:'forwards'});
      animation.finished.then(finish,()=>{});
    };
    const stretch=delta=>{
      if(!active||releasing)return;
      pull=Math.max(0,Math.min(window.innerWidth,pull+delta));ready=pull>=threshold;paint();
    };
    document.addEventListener('wheel',event=>{
      const track=event.target.closest?.('.row');
      const candidate=track&&entries.get(track);
      if(!candidate||!atEnd(track))return;
      if(active!==candidate)activate(candidate);
      if(!usable()){reset();return;}
      if(event.target.closest?.('input,select,textarea,[contenteditable="true"]'))return;
      if(releasing){if(event.cancelable)event.preventDefault();return;}
      const delta=Math.abs(event.deltaX)>Math.abs(event.deltaY)?event.deltaX:event.deltaY;
      if(delta<=0){reset();return;}
      if(event.cancelable)event.preventDefault();
      // Ignore the fast tail of the gesture that reached the end.
      if(performance.now()<wheelReadyAt)return;
      stretch(delta*2.2*(event.deltaMode===1?16:event.deltaMode===2?window.innerHeight:1));
      clearTimeout(idle);idle=setTimeout(release,150);
    },{capture:true,passive:false});
    document.addEventListener('mousedown',event=>{
      const track=event.target.closest?.('.row'),entry=track&&entries.get(track);
      if(event.button!==0||!entry||event.target.closest?.('input,select,textarea,a,.row-nav__btn'))return;
      mouse={entry,x:event.clientX,last:event.clientX,dragging:false};
      if(atEnd(track))event.preventDefault();
    },true);
    document.addEventListener('dragstart',event=>{if(mouse)event.preventDefault();},true);
    document.addEventListener('mousemove',event=>{
      if(!mouse||releasing)return;
      const delta=mouse.last-event.clientX;
      if(!mouse.dragging){
        if(!atEnd(mouse.entry.track)){mouse.x=event.clientX;mouse.last=event.clientX;return;}
        if(mouse.x-event.clientX<6)return;
        activate(mouse.entry);if(!usable())return;
        mouse.dragging=true;suppressClick=true;
        pull=Math.max(0,window.innerWidth-mouse.x);
      }
      event.preventDefault();event.stopPropagation();
      stretch(delta);mouse.last=event.clientX;
    },true);
    window.addEventListener('mouseup',()=>{
      if(mouse?.dragging)release();mouse=null;
      setTimeout(()=>{suppressClick=false;},0);
    });
    document.addEventListener('click',event=>{
      if(suppressClick){event.preventDefault();event.stopPropagation();}
    },true);
    document.addEventListener('touchstart',event=>{
      const track=event.target.closest?.('.row'), candidate=track&&entries.get(track);
      if(candidate&&atEnd(track))activate(candidate);
      touch=active?.track===track&&usable()&&event.touches.length===1?{x:event.touches[0].clientX,y:event.touches[0].clientY,last:0,dragging:false}:null;
    },{passive:true});
    document.addEventListener('touchmove',event=>{
      if(!touch||!active||releasing)return;
      const dx=touch.x-event.touches[0].clientX,dy=touch.y-event.touches[0].clientY;
      if(Math.abs(dy)>Math.abs(dx)){touch=null;return;}
      const distance=dx;
      if(distance<0){reset();return;}
      if(event.cancelable)event.preventDefault();
      if(!touch.dragging){
        if(distance<6)return;
        touch.dragging=true;pull=Math.max(0,window.innerWidth-touch.x);
      }
      stretch(distance-touch.last);touch.last=distance;
    },{capture:true,passive:false});
    document.addEventListener('touchend',()=>{if(touch){touch=null;release();}},{passive:true});
    document.addEventListener('touchcancel',reset,{passive:true});
    window.addEventListener('popstate',reset);
    window.addEventListener('scroll',()=>{if(active&&!usable())reset();},{passive:true});
    return {register(track,open){
      if (['track-home-favorites', 'track-continue-watching'].includes(track.id))return;
      track._catalogSpringOpen=open;
      if(registered.has(track))return;
      registered.add(track);
      let entry=null;
      const sync=()=>{
        const existing=track.querySelector('.row-catalog-end');
        if(existing&&entry?.end===existing)return;
        if(active?.track===track)reset();
        if(!track.querySelector('.card, .rank-card, .resume-card, .personal-favorite'))return;
        const end=existing||document.createElement('button');
        end.type='button';end.className='row-catalog-end';
        const arrow=document.createElement('span');arrow.className='row-catalog-end__arrow';arrow.textContent='→';
        const title=document.createElement('strong');title.textContent='C’è ancora molto da vedere';
        const hint=document.createElement('span');hint.textContent='Scorri ancora sul carosello per aprire il catalogo';
        end.replaceChildren(arrow,title,hint);end.setAttribute('aria-label','Apri il catalogo completo della sezione');
        entry={track,end,hint,open:()=>track._catalogSpringOpen()};
        entries.set(track,entry);
        end.onclick=()=>{activate(entry);pull=threshold;ready=true;paint();release();};
        if(!existing)track.appendChild(end);
      };
      new MutationObserver(sync).observe(track,{childList:true});sync();
      track.addEventListener('scroll',()=>{
        if(atEnd(track)&&entry)activate(entry);
        else if(active?.track===track&&!preview)reset();
      },{passive:true});
    }};
  };
})(window);
