// Actual Studio functions, isolated mocked DOM and API. No live board mutation.
async function main(){
const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{id,hidden:true,style:{setProperty(){}},dataset:{},innerHTML:'',textContent:'',value:'',clientWidth:1200,clientHeight:700,classList:{toggle(){},add(){},remove(){}},querySelectorAll:()=>[],querySelector:()=>el('dummy'),setAttribute(){},getBoundingClientRect:()=>({left:0,top:0,width:1200,height:700}),focus(){},click(){}});return elements.get(id)}
const context={console,crypto,performance:{now:()=>1000},CSS:{escape:s=>s},URL,location:{href:'http://127.0.0.1:8840/'},document:{documentElement:{style:{setProperty(){}}},getElementById:el,querySelectorAll:()=>[],querySelector:()=>el('dummy')},window:{matchMedia:()=>({matches:false}),addEventListener(){}},localStorage:{setItem(){},getItem(){return null}},setTimeout:()=>1,clearTimeout(){},requestAnimationFrame(){},FormData:class{append(name,value){this[name]=value}},fetch:()=>{throw Error('Unexpected network access')}};vm.createContext(context);vm.runInContext(fs.readFileSync('app.js','utf8').replace(/init\(\);\s*$/,''),context);const run=s=>vm.runInContext(s,context);let checks=0;function check(s){assert.equal(run(s),true,s);checks++}
run(`render=()=>{};renderBoardControls=()=>{};renderLibrary=()=>{};populateFilters=()=>{};openInspector=(type,id)=>{inspectorOpenFor={type,id};};project={id:'test',asset_policy:'latest-approved'};catalog=[];board={board_id:'test',nodes:[],edges:[],effects:[],chosen_path:[],render_path_ends_here:true};createDraftScene();const draft=board.nodes[0];`);
check(`board.nodes.length===1&&draft.new_draft&&draft.title==='New scene'`);check(`inspectorOpenFor===null&&selectedIds.has(draft.id)`);
run(`const imported={id:'image1',title:'Movie screenshot.png',source:'/local/original.png',sha256:'abc',version:'User import',image:'/assets/image.png',frames:{start:'/assets/image.png',middle:'/assets/image.png',end:'/assets/image.png'}};api=async()=>({item:imported});`);
await run(`attachSceneImages(draft.id,[{name:'Movie screenshot.png',type:'image/png'}])`);
check(`draft.reference_images[0]==='image1'&&catalog[0].source==='/local/original.png'`);check(`referenceImageBrief(draft)[0].sha256==='abc'&&referenceImageBrief(draft)[0].policy.includes('Visual reference')`);
run(`renderNodes()`);check(`$('nodes').innerHTML.includes('Visual reference · Not rendered')&&$('nodes').innerHTML.includes('/assets/image.png')`);
run(`draft.reference_id='primary';catalog.push({id:'primary',title:'Draft native preview',frames:{},source_interval:{start_s:0,end_s:5}});board.chosen_path=[draft.id];`);check(`renderPlan().scenes[0].reference_images[0].source==='/local/original.png'`);
run(`draft.reference_images.push('missing')`);check(`issues().some(s=>s.includes('Missing attached reference image'))`);
await run(`attachSceneImages(draft.id,[{name:'bad.txt',type:'text/plain'}])`);check(`catalog.length===2&&boardRequestCount===0`);
// A picker survives card replacement and captures the intended scene/board.
run(`const oldGetElement=document.getElementById;let stablePicker=null;document.getElementById=id=>id==='scene-image-file'?stablePicker:oldGetElement(id);document.createElement=()=>({dataset:{},value:'',addEventListener(){},click(){this.clicked=true}});document.body={append(input){stablePicker=input}};const firstPicker=ensureSceneImageInput();firstPicker.dataset.sceneTarget=draft.id;firstPicker.dataset.boardTarget=board.board_id;document.getElementById('inspector-content').innerHTML='replaced';`);
check(`ensureSceneImageInput()===firstPicker&&typeof firstPicker.onchange==='function'`);
await run(`firstPicker.onchange({target:{files:[{name:'Another.png',type:'image/png'}]}})`);
check(`firstPicker.value===''&&draft.reference_images.includes('image1')&&boardRequestCount===0`);
run(`firstPicker.dataset.boardTarget='different'`);await run(`firstPicker.onchange({target:{files:[{name:'Wrong.png',type:'image/png'}]}})`);check(`$('save-state').textContent.includes('storyboard changed')`);
const result={status:'PASS',assertions:checks,scope:'Isolated actual functions; mocked DOM/import API. No live board writes or physical drop claim.'};console.log(result);
}
main().catch(e=>{console.error(e);process.exitCode=1});
