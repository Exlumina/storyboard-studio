// Actual inline-card editing functions with isolated mock DOM/API; never touches live boards.
async function main(){
const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{id,hidden:true,style:{setProperty(){}},dataset:{},innerHTML:'',textContent:'',value:'',clientWidth:1200,clientHeight:700,offsetHeight:160,classList:{toggle(){},add(){},remove(){}},querySelectorAll:()=>[],querySelector:()=>el('dummy'),addEventListener(){},getBoundingClientRect:()=>({left:100,top:100,right:306,bottom:264,width:1200,height:700}),remove(){},close(){},showModal(){},setAttribute(name,value){this.attributes??={};this.attributes[name]=value},getAttribute(name){return this.attributes?.[name]},animate(){},setPointerCapture(){}});return elements.get(id)}
const context={console,crypto,performance:{now:()=>1000},CSS:{escape:s=>s},URL,location:{href:'http://127.0.0.1:8840/'},document:{documentElement:{style:{setProperty(){}}},getElementById:el,querySelectorAll:()=>[],querySelector:()=>el('dummy'),addEventListener(){}},window:{matchMedia:()=>({matches:false}),addEventListener(){}},innerHeight:900,localStorage:{setItem(){},getItem(){return null},removeItem(){}},setTimeout:()=>1,clearTimeout(){},requestAnimationFrame(){},ResizeObserver:class{observe(){}},fetch:()=>{throw Error('Unexpected network access')} };vm.createContext(context);
vm.runInContext(fs.readFileSync('app.js','utf8').replace(/init\(\);\s*$/,''),context);
const run=s=>vm.runInContext(s,context);let checks=0;function check(s){assert.equal(run(s),true,s);checks++}


run(`render=()=>{};renderEdges=()=>{};project={id:'spacing-test'};catalog=[];function spacingFixture(){board={board_id:'fixture',nodes:[{id:'a',scene_id:'scene-a',x:0,y:10},{id:'b',scene_id:'scene-b',x:500,y:40},{id:'c',scene_id:'scene-c',x:1000,y:80}],edges:[{id:'ab',from:'a',to:'b',transition:'continuous',notes:'Keep'},{id:'bc',from:'b',to:'c',transition:'cut'}],effects:[{id:'follow',parent_node_id:'b',target_node_ids:['b','c'],follow_parent:true,x:520,y:-50},{id:'selected-fx',parent_node_id:'b',target_node_ids:['b'],follow_parent:true,x:750,y:-100}],feedback_cards:[],chosen_path:['a','b','c'],render_path_ends_here:true};selectedIds=new Set(['a','b','c']);selectedEffectIds=new Set();history=[];future=[];suppressSpacingUntil=0;lastCardClick=null;reviewMode=false;document.getElementById('scene-a').offsetWidth=206;document.getElementById('scene-b').offsetWidth=240;document.getElementById('scene-c').offsetWidth=180;}spacingFixture();const original=JSON.stringify(board),edgesBefore=JSON.stringify(board.edges);`);
check(`distributeSelectedCards(1000)===true&&history.length===1`);
check(`node('a').x===0&&node('c').x===1000&&node('b').x-206===node('c').x-(node('b').x+240)`);
check(`node('a').y===10&&node('b').y===40&&node('c').y===80&&JSON.stringify(board.edges)===edgesBefore&&selectedIds.size===3&&node('a').scene_id==='scene-a'`);
check(`auxiliaryCard('follow').x===node('b').x+20&&auxiliaryCard('follow').y===-50&&auxiliaryTargets(auxiliaryCard('follow')).join(',')==='b,c'`);
run(`board=history.pop()`);check(`JSON.stringify(board)===original`);
run(`spacingFixture();selectedIds=new Set(['a','b']);`);check(`distributeSelectedCards(1000)&&node('b').x===206+72&&node('c').x===1000`);
run(`spacingFixture();node('b').x=100;node('c').x=200;`);check(`distributeSelectedCards(1000)&&node('b').x===278&&node('c').x===590`);
run(`spacingFixture();selectedIds=new Set(['a','b']);selectedEffectIds=new Set(['selected-fx']);document.getElementById('effect-selected-fx').offsetWidth=174;const explicitBeforeY=auxiliaryCard('selected-fx').y;`);check(`distributeSelectedCards(1000)&&Math.abs((node('b').x-206)-(auxiliaryCard('selected-fx').x-node('b').x-240))<.001&&auxiliaryCard('selected-fx').y===explicitBeforeY&&auxiliaryCard('selected-fx').parent_node_id==='b'`);
run(`spacingFixture();reviewMode=true;const reviewBefore=JSON.stringify(board);`);check(`distributeSelectedCards(1000)===false&&JSON.stringify(board)===reviewBefore&&history.length===0`);
run(`spacingFixture();suppressInspectorUntil=0;`);check(`registerCardClick('node','b',1000)===false&&registerCardClick('node','b',1200)===true&&history.length===1&&selectedIds.size===3`);
check(`distributeSelectedCards(1250)===false&&history.length===1`);
console.log({status:'PASS',assertions:checks,scope:'Actual measured-width spacing, equal gaps, stable y/identities/connections, following versus selected auxiliaries, undo, double-tap and review protection. Mock DOM only.'});
}
main().catch(e=>{console.error(e);process.exit(1)});
