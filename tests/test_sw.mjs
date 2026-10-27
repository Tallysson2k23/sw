import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const events={}, stored=[], deleted=[];
let online=true, install;
const caches={open:async()=>({addAll:async assets=>stored.push(...assets)}),keys:async()=>['sw-public-v0','another-app'],delete:async key=>deleted.push(key),match:async key=>stored.includes(key)?{cached:key}:undefined};
const self={location:{origin:'https://sw.test'},addEventListener:(name,fn)=>events[name]=fn,skipWaiting:async()=>{},clients:{claim:async()=>{}}};
vm.runInNewContext(readFileSync('static/sw.js','utf8'),{self,caches,URL,fetch:async req=>{if(!online)throw Error('offline');return {network:req.url};}});
events.install({waitUntil:p=>install=p});await install;
assert(stored.includes('/static/offline.html'));
assert(stored.every(path=>path.startsWith('/static/')));
events.activate({waitUntil:p=>install=p});await install;
assert.deepEqual(deleted,['sw-public-v0']);
async function request(path,method='GET',mode='navigate'){
 let response;events.fetch({request:{url:'https://sw.test'+path,method,mode},respondWith:p=>response=p});return response&&await response;
}
assert.equal((await request('/aluno')).network,'https://sw.test/aluno');
online=false;
for(const path of ['/','/admin','/aluno','/material/1','/cursos'])assert.equal((await request(path)).cached,'/static/offline.html');
assert.equal((await request('/static/style.css','GET','cors')).cached,'/static/style.css');
assert.equal(await request('/interesse','POST'),undefined);
assert.equal(await request('/material/1','GET','cors'),undefined);
assert.equal(await request('/foto/1','GET','cors'),undefined);
assert.equal(await request('/anuncio/1/imagem','GET','cors'),undefined);
assert.equal(await request('/static/app.js?v=future','GET','cors'),undefined);
console.log('OK: instalação, ativação, cache público, fallback offline e ausência de cache privado.');
