'use strict';
if('serviceWorker'in navigator){
 const reloadGuard='v381-sw-controller-reload';
 let reloading=false;
 navigator.serviceWorker.addEventListener('controllerchange',()=>{
  const controller=navigator.serviceWorker.controller;
  if(reloading||!controller)return;
  const channel=new MessageChannel();
  channel.port1.onmessage=event=>{
   channel.port1.close();
   const shellId=event.data;
   if(reloading||typeof shellId!=='string'||!shellId)return;
   // Keep the guard across reloads; a later shell generation can reload again.
   try{
    if(sessionStorage.getItem(reloadGuard)===shellId)return;
    sessionStorage.setItem(reloadGuard,shellId);
   }catch(e){/* Storage can be unavailable in embedded/private browsers. */}
   reloading=true;
   location.reload();
  };
  controller.postMessage({type:'GET_SHELL_ID'},[channel.port2]);
 });
 const update=()=>{
  navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).then(registration=>registration.update()).catch(()=>{});
 };
 if(document.readyState==='complete')update();
 else addEventListener('load',update,{once:true});
}
