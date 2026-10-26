// Board changes run against the actual frontend with a DOM that has no retired .tools element.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const workspace={inert:false},toolbar={inert:false},state={textContent:'',classList:{toggle(){}}},detail={open:false};
const context={console,crypto:require('crypto').webcrypto,setTimeout,clearTimeout,document:{activeElement:null,getElementById:id=>({workspace,'save-state':state,detail})[id],querySelector:selector=>selector==='.toolbar'?toolbar:null}};
vm.createContext(context);vm.runInContext(fs.readFileSync('app.js','utf8').replace(/init\(\);\s*$/,''),context);
const run=source=>vm.runInContext(source,context);
(async()=>{
 run(`boardsAvailable=true;renderBoardControls=()=>{};updateBoardIdentity=()=>{};refreshBoards=async()=>{};flushBoard=async()=>{};`);
 await run(`boardAction(async()=>{if(!$('workspace').inert||!document.querySelector('.toolbar').inert)throw Error('Editing unlocked');globalThis.completed=true;})`);
 assert.equal(context.completed,true);assert.equal(workspace.inert,false);assert.equal(toolbar.inert,false);assert.equal(run('boardBusy'),false);
 await run(`boardAction(async()=>{throw Error('Fixture API unavailable');})`);
 assert.match(state.textContent,/Fixture API unavailable/);assert.equal(workspace.inert,false);assert.equal(toolbar.inert,false);assert.equal(run('boardBusy'),false);
 toolbar.inert=true;
 await run(`boardAction(async()=>{})`);assert.equal(toolbar.inert,true);assert.equal(workspace.inert,false);
 console.log('PASS: board action executes, recovers errors and restores prior locks without a .tools element');
})().catch(error=>{console.error(error);process.exitCode=1;});
