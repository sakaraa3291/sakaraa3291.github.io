'use strict';
if('serviceWorker'in navigator){
 const reloadGuard='v380-sw-controller-reload',hadReloadGuard=sessionStorage.getItem(reloadGuard)==='1';
 let reloading=hadReloadGuard;
 if(hadReloadGuard)setTimeout(()=>{sessionStorage.removeItem(reloadGuard);reloading=false},10000);
 navigator.serviceWorker.addEventListener('controllerchange',()=>{
  if(reloading)return;
  reloading=true;sessionStorage.setItem(reloadGuard,'1');location.reload();
 });
 addEventListener('load',()=>{
  navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).then(registration=>registration.update()).catch(()=>{});
 },{once:true});
}
