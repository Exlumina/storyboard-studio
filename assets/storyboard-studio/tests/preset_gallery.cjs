// Actual Studio functions, isolated mocked DOM and API. No live board mutation.
async function main(){
const fs=require('fs'),vm=require('vm'),assert=require('assert'),crypto=require('crypto');
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{id,hidden:true,style:{setProperty(){}},dataset:{},innerHTML:'',textContent:'',value:'',clientWidth:1200,clientHeight:700,classList:{toggle(){},add(){},remove(){}},querySelectorAll:()=>[],querySelector:()=>el('dummy'),setAttribute(){},getBoundingClientRect:()=>({left:0,top:0,width:1200,height:700}),focus(){},click(){}});return elements.get(id)}
const context={console,crypto,performance:{now:()=>1000},CSS:{escape:s=>s},URL,location:{href:'http://127.0.0.1:8840/'},document:{documentElement:{style:{setProperty(){}}},getElementById:el,querySelectorAll:()=>[],querySelector:()=>el('dummy')},window:{matchMedia:()=>({matches:false}),addEventListener(){}},localStorage:{setItem(){},getItem(){return null}},setTimeout:()=>1,clearTimeout(){},requestAnimationFrame(){},FormData:class{append(name,value){this[name]=value}},fetch:()=>{throw Error('Unexpected network access')}};vm.createContext(context);vm.runInContext(fs.readFileSync('app.js','utf8').replace(/init\(\);\s*$/,''),context);const run=s=>vm.runInContext(s,context);let checks=0;function check(s){assert.equal(run(s),true,s);checks++}

run(`render=()=>{};project={id:'test'};catalog=[{id:'source',frames:{start:'/original.png'}}];board={board_id:'board',nodes:[{id:'scene',reference_id:'source',duration_s:5}],effects:[{id:'effect',kind:'lens_flare',preset_id:'old',settings:{intensity:1.75,custom:'preserved'},enabled:true,follow_parent:true,target_node_ids:['scene'],x:1,y:2}],edges:[],chosen_path:['scene']};effectRegistry=[{id:'lens_flare',title:'Anamorphic flare',presets:[{id:'old',title:'Old',settings:{intensity:1}},{id:'new',title:'Blue anamorphic',settings:{intensity:2},preview_image:'/assets/new.png',preview_label:'Native preset reference',preview_kind:'actual_native',preview_source:'Local rendered preview'},{id:'missing',title:'Amber',settings:{},preview_label:'No output yet'}]}];const sourceBefore=JSON.stringify(catalog),targetsBefore=JSON.stringify(board.effects[0].target_node_ids),settingsBefore=JSON.stringify(board.effects[0].settings);`);
check(`presetPreviewMarkup(effectRegistry[0].presets[1]).includes('/assets/new.png')&&presetPreviewMarkup(effectRegistry[0].presets[1]).includes('Native preset reference')`);
check(`presetPreviewMarkup(effectRegistry[0].presets[2]).includes('Preview pending')&&!presetPreviewMarkup(effectRegistry[0].presets[2]).includes('<img')`);
check(`chooseEffectPreset('effect','new')===true&&board.effects[0].preset_id==='new'`);
check(`JSON.stringify(board.effects[0].settings)===settingsBefore&&JSON.stringify(board.effects[0].target_node_ids)===targetsBefore&&JSON.stringify(catalog)===sourceBefore`);
check(`chooseEffectPreset('effect','invented')===false&&board.effects[0].preset_id==='new'`);
run(`history=[];chooseEffectPreset('effect','new');`);check(`history.length===0`);
run(`openDialog=html=>{$('detail-content').innerHTML=html};showPresetGallery('effect');`);
check(`$('detail-content').innerHTML.includes('<button class="preset-choice selected" data-preset-choice="new" aria-pressed="true"')&&$('detail-content').innerHTML.includes('Preview pending')&&$('detail-content').innerHTML.includes('Choose Anamorphic flare preset')`);
check(`!$('detail-content').innerHTML.includes('completed render')`);
console.log({status:'PASS',assertions:checks,scope:'Actual preset helpers with mocked DOM; native buttons supply keyboard semantics. No visual asset or browser hit-testing claim.'});
}
main().catch(e=>{console.error(e);process.exitCode=1});
