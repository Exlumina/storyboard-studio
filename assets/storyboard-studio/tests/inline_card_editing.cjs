// Actual inline-card editing functions with isolated mock DOM/API; never touches live boards.
async function main(){
const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{id,hidden:true,style:{setProperty(){}},dataset:{},innerHTML:'',textContent:'',value:'',clientWidth:1200,clientHeight:700,offsetHeight:160,classList:{toggle(){},add(){},remove(){}},querySelectorAll:()=>[],querySelector:()=>el('dummy'),addEventListener(){},getBoundingClientRect:()=>({left:100,top:100,right:306,bottom:264,width:1200,height:700}),remove(){},close(){},showModal(){},setAttribute(name,value){this.attributes??={};this.attributes[name]=value},getAttribute(name){return this.attributes?.[name]},animate(){},setPointerCapture(){}});return elements.get(id)}
const context={console,crypto,performance:{now:()=>1000},CSS:{escape:s=>s},URL,location:{href:'http://127.0.0.1:8840/'},document:{documentElement:{style:{setProperty(){}}},getElementById:el,querySelectorAll:()=>[],querySelector:()=>el('dummy'),addEventListener(){}},window:{matchMedia:()=>({matches:false}),addEventListener(){}},innerHeight:900,localStorage:{setItem(){},getItem(){return null},removeItem(){}},setTimeout:()=>1,clearTimeout(){},requestAnimationFrame(){},ResizeObserver:class{observe(){}},fetch:()=>{throw Error('Unexpected network access')} };vm.createContext(context);
vm.runInContext(fs.readFileSync('app.js','utf8').replace(/init\(\);\s*$/,''),context);
const run=s=>vm.runInContext(s,context);let checks=0;function check(s){assert.equal(run(s),true,s);checks++}

run(`render=()=>{};renderEdges=()=>{};project={id:'test'};catalog=[{id:'ref',frames:{start:'/actual.png'}}];board={board_id:'fixture',nodes:[{id:'a',scene_id:'scene_a',title:'Original',reference_id:'ref',duration_s:5,x:0,y:0},{id:'draft',scene_id:'scene_d',title:'New scene',new_draft:true,description:'',duration_s:4,x:240,y:0}],edges:[],effects:[{id:'fx',kind:'flare',preset_id:'soft',enabled:true,follow_parent:true,settings:{intensity:1,custom:'keep'},target_node_ids:['a','draft']}],feedback_cards:[],chosen_path:['a'],render_path_ends_here:true};effectRegistry=[{id:'flare',title:'Flare',presets:[{id:'soft',title:'Soft',preview_image:'/actual.png'}]}];history=[];`);
check(`applyCardField('a','title',' Updated ' )&&node('a').title==='Updated'&&history.length===1`);
run(`const realCardQuery=document.querySelector;const durationLabelProbe={setAttribute(name,value){this[name]=value;},value:''};document.querySelector=()=>({setAttribute(){},querySelector(selector){return selector==='[data-card-duration]'?durationLabelProbe:null;}});refreshNodeText(node('a'));`);
check(`durationLabelProbe['aria-label']==='Duration for Updated in seconds'`);run(`document.querySelector=realCardQuery`);

run(`board=history.pop()`);check(`node('a').title==='Original'`);
check(`applyCardField('a','title',' ' )===false&&node('a').title==='Original'&&history.length===0`);
check(`applyCardField('a','duration_s','8.5')&&node('a').duration_s===8.5&&history.length===1`);
check(`applyCardField('a','duration_s','0')===false&&applyCardField('a','duration_s','NaN')===false&&node('a').duration_s===8.5&&history.length===1`);
// Test the bound Enter/change/blur route, including browsers that do not emit change.
run(`const actualNodeQueries=$('nodes').querySelectorAll;let durationBlurs=0;const durationInput={dataset:{cardDuration:'a'},type:'number',value:'1.2',blur(){durationBlurs++;this.onblur?.();}};$('nodes').querySelectorAll=selector=>selector==='[data-card-duration]'||selector.startsWith('input,textarea,')?[durationInput]:[];const durationHistoryBefore=history.length;bindInlineSceneEditors();durationInput.onkeydown({key:'Enter',preventDefault(){},stopPropagation(){}});`);
check(`node('a').duration_s===1.2&&history.length===durationHistoryBefore+1&&durationBlurs===1`);
run(`durationInput.onchange();durationInput.onblur();`);check(`history.length===durationHistoryBefore+1`);
run(`durationInput.value='0';durationInput.onblur();`);check(`node('a').duration_s===1.2&&durationInput.value==='1.2'&&history.length===durationHistoryBefore+1`);

run(`durationInput.onfocus();const inputHistoryBefore=history.length;durationInput.value='1.3';durationInput.oninput();durationInput.value='1.4';durationInput.oninput();`);
check(`node('a').duration_s===1.4&&history.length===inputHistoryBefore+1`);
run(`durationInput.value='';durationInput.oninput();`);check(`node('a').duration_s===1.4&&durationInput.value===''&&history.length===inputHistoryBefore+1`);
run(`durationInput.onblur()`);check(`durationInput.value==='1.4'&&history.length===inputHistoryBefore+1`);
run(`$('nodes').querySelectorAll=actualNodeQueries`);

check(`applyEffectCardField('fx','intensity','2.5')&&board.effects[0].settings.intensity===2.5&&board.effects[0].settings.custom==='keep'&&board.effects[0].target_node_ids.join(',')==='a,draft'`);
check(`applyEffectCardField('fx','intensity','-1')===false&&applyEffectCardField('fx','intensity','bad')===false&&board.effects[0].settings.intensity===2.5`);
check(`applyEffectCardField('fx','enabled',false)&&board.effects[0].enabled===false`);
check(`applyEffectCardField('fx','follow_parent',false)&&board.effects[0].follow_parent===false`);
run(`const actualEffectQueries=$('effects').querySelectorAll;const beforeTypingRender=render;let typingRenders=0;render=()=>{typingRenders++;};const intensityInput={dataset:{cardIntensity:'fx'},type:'number',value:'0.8',blur(){this.onblur?.();}};$('effects').querySelectorAll=selector=>['[data-card-intensity]','[data-card-preset],input'].includes(selector)?[intensityInput]:[];bindInlineEffectEditors();intensityInput.onfocus();const intensityHistoryBefore=history.length;intensityInput.oninput();intensityInput.value='0.9';intensityInput.oninput();`);
check(`board.effects[0].settings.intensity===.9&&history.length===intensityHistoryBefore+1&&typingRenders===0`);
run(`intensityInput.value='';intensityInput.oninput();`);check(`board.effects[0].settings.intensity===.9&&intensityInput.value===''&&history.length===intensityHistoryBefore+1`);
run(`intensityInput.onblur();intensityInput.onchange();`);check(`Number(intensityInput.value)===.9&&history.length===intensityHistoryBefore+1&&typingRenders===0`);
run(`$('effects').querySelectorAll=actualEffectQueries;render=beforeTypingRender;`);

run(`reviewMode=true;const frozen=JSON.stringify(board)`);check(`applyCardField('a','title','No')===false&&applyEffectCardField('fx','enabled',true)===false&&JSON.stringify(board)===frozen`);run(`reviewMode=false`);
check(`cardTitleMarkup(node('a'),'Original').includes('data-card-title-editor')&&cardDurationMarkup(node('a')).includes('min="0.1"')&&draftCardMarkup(node('draft')).includes('data-draft-save')&&effectCardControls(board.effects[0]).includes('data-card-preset')&&effectCardControls(board.effects[0]).includes('data-card-enabled')`);
run(`renderNodes()`);check(`$('nodes').innerHTML.includes('data-card-duration="a"')&&$('nodes').innerHTML.includes('data-draft-description="draft"')`);
check(`inspectorAllowed()===false&&registerCardClick('node','draft')===false`);
// Native double-click defaults settle before replacing the focused title button.
run(`const realQuery=document.querySelector;let titleFocusQueued=null;let titleInputFocus=0;const titleButton={hidden:false},titleInput={hidden:true,focus(){titleInputFocus++},select(){}};document.querySelector=selector=>selector.includes('data-card-title-editor')?titleInput:selector.includes('data-card-title=')?titleButton:realQuery(selector);requestAnimationFrame=callback=>{titleFocusQueued=callback;};beginCardTitle('a');`);
check(`titleInput.hidden===true&&titleButton.hidden===false&&titleInputFocus===0&&typeof titleFocusQueued==='function'`);
run(`titleFocusQueued()`);check(`titleInput.hidden===false&&titleButton.hidden===true&&titleInputFocus===1`);

// Idempotence prevents a duplicate native/delegated event from reselecting the input.
run(`document.activeElement=titleInput;beginCardTitle('a');titleFocusQueued();`);check(`titleInputFocus===1&&titleInput.hidden===false`);run(`document.activeElement=null;`);
run(`document.querySelector=realQuery;requestAnimationFrame=()=>{};`);

run(`populateFilters=()=>{};renderLibrary=()=>{};api=async(url,opts)=>{globalThis.draftPayload=JSON.parse(opts.body);return {item:{id:'draft-result',source_interval:{start_s:0,end_s:4}},request:{id:'request',status:'queued_for_chat'}}};`);
await run(`sendNewScene('draft',{value:'Camera follows subject'},{textContent:''},{disabled:false})`);
check(`draftPayload.kind==='new_scene'&&draftPayload.description==='Camera follows subject'&&draftPayload.scene_id==='scene_d'&&node('draft').reference_id==='draft-result'&&!node('draft').new_draft`);
console.log({status:'PASS',assertions:checks,scope:'Direct on-card fields, validation, undo, multi-target preservation, review protection, rendered markup, draft request payload. Mocked DOM/API only.'});
}
main().catch(e=>{console.error(e);process.exit(1)});
