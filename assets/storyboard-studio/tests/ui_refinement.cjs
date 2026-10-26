// Actual functions: socket geometry, current connected order, stable board identity and icons.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{dataset:{},disabled:false,value:'',title:'',textContent:'',innerHTML:'',querySelector:()=>null,querySelectorAll:()=>[],classList:{toggle(){}},setAttribute(){}});return elements.get(id)}
const context={console,crypto:require('crypto').webcrypto,document:{getElementById:el,querySelectorAll:()=>[]},window:{},setTimeout,clearTimeout};vm.createContext(context);vm.runInContext(fs.readFileSync('app.js','utf8').replace(/init\(\);\s*$/,''),context);const run=s=>vm.runInContext(s,context);let checks=0;function check(s){assert.equal(run(s),true,s);checks++}
run(`board={board_id:'a'.repeat(32),nodes:[{id:'start',kind:'start'},{id:'a',title:'A',scene_id:'stable-a'},{id:'b',title:'B',scene_id:'stable-b'},{id:'end',kind:'end'},{id:'alt',title:'Alternative',scene_id:'stable-alt'}],edges:[{from:'start',to:'a'},{from:'a',to:'b'},{from:'b',to:'end'}],chosen_path:['start','a','b','end']};`);
check(`connectedSceneNumber('a')===1&&connectedSceneNumber('b')===2&&connectedSceneNumber('alt')===null`);
run(`board.edges=[{from:'start',to:'b'},{from:'b',to:'a'},{from:'a',to:'end'}];board.chosen_path=['start','b','a','end'];`);check(`connectedSceneNumber('b')===1&&connectedSceneNumber('a')===2&&node('a').scene_id==='stable-a'`);
run(`board.edges=board.edges.filter(edge=>edge.from!=='b')`);check(`connectedSceneNumber('a')===null&&sceneOrderMarkup('a').includes('Alternate')`);
run(`board.chosen_path=['b','a','b'];board.edges=[{from:'b',to:'a'},{from:'a',to:'b'}]`);check(`connectedSceneOrder().size===2&&connectedSceneNumber('b')===1`);
run(`zoom=2;$('world').getBoundingClientRect=()=>({left:100,top:50});const socket={matches:()=>true,getBoundingClientRect:()=>({left:160,top:90,width:20,height:20})};$('card').querySelector=()=>socket;`);
check(`socketPoint('card','[data-output]',{x:0,y:0}).x===35&&socketPoint('card','[data-output]',{x:0,y:0}).y===25`);
run(`socket.getBoundingClientRect=()=>({left:180,top:120,width:20,height:20})`);check(`socketPoint('card','[data-output]',{x:0,y:0}).x===45&&socketPoint('card','[data-output]',{x:0,y:0}).y===40`);
check(`socketPoint('missing','[data-output]',{x:7,y:9}).x===7`);
run(`boardsAvailable=true;boards=[{id:board.board_id,title:'Independent name'}];renderBoardControls()`);
check(`$('board-select').innerHTML.includes('Independent name')&&!$('board-select').innerHTML.includes(board.board_id.slice(0,8)+')')`);
check(`$('board-id').dataset.copyId===board.board_id&&$('board-id').textContent===board.board_id.slice(0,8)`);
check(`playIcon().includes('<svg')&&playIcon().includes('aria-hidden="true"')`);
console.log({status:'PASS',assertions:checks,scope:'Actual functions with mocked DOM; browser geometry and clipboard checked separately.'});
