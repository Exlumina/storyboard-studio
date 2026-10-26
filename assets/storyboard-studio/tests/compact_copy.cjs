const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('app.js','utf8');const a=source.indexOf('function bindCopyIds('),b=source.indexOf('function applySceneCodes',a);
async function check(success,clipboard,native='unsupported'){
 let statusText='',focused=0,removed=0,selected=0,manual=null,written=null;
 const make=()=>({style:{},setAttribute(){},focus(){focused++;},select(){selected++;},remove(){removed++;}});
 const button={dataset:{copyId:'SN9SSR'},parentElement:{querySelector(){return manual}},after(field){manual=field;}};
 const document={activeElement:{focus(){focused++;}},body:{append(){}},createElement:make,execCommand(name){assert.equal(name,'copy');return success;}};
 const ctx={api:async()=>{if(native==='error')throw Error('Unavailable');return {native_supported:native!=='unsupported',copied:native==='success'};},document,navigator:{clipboard:clipboard?{writeText:async text=>{written=text;if(clipboard==='reject')throw Error('Denied');}}:undefined},status:s=>{statusText=s},setTimeout};vm.createContext(ctx);vm.runInContext(source.slice(a,b),ctx);ctx.bindCopyIds({querySelectorAll:()=>[button]});await button.onclick({preventDefault(){},stopPropagation(){}});
 if(native==='success'||native==='unsupported'&&clipboard===true){assert.equal(removed,0);assert.equal(focused,0);assert.equal(selected,0);}else{assert.equal(removed,1);assert(focused>=2);assert(selected>=1);}
 if(native==='success'||native==='unsupported'&&(success||clipboard===true)){assert.equal(statusText,'Copied SN9SSR');assert.equal(manual,null);}else{assert.equal(manual.value,'SN9SSR');assert(manual.readOnly);assert.equal(statusText,'ID selected. Press Command+C to copy.');}
 return written;
}
(async()=>{await check(true,false);assert.equal(await check(false,true),'SN9SSR');await check(false,'reject');await check(false,false);assert.equal(await check(false,false,'success'),null);assert.equal(await check(true,true,'failed'),null);assert.equal(await check(true,true,'error'),null);console.log('PASS compact copy: verified native system clipboard first, browser and manual fallbacks');})().catch(e=>{console.error(e);process.exitCode=1;});
