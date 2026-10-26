"""Explicit local native-render return admission. No renderer is started here."""
import hashlib,json,math,re,shutil,struct,zlib
from pathlib import Path
from storyboard_conformance import digest as contract_digest

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def bound_file(value):
    if not isinstance(value,dict) or not isinstance(value.get('path'),str) or not re.fullmatch('[a-f0-9]{64}',value.get('sha256','')):raise ValueError('Provide an actual local file path and SHA256.')
    path=Path(value['path']).expanduser().resolve()
    if not path.is_file() or digest(path)!=value['sha256']:raise ValueError('An actual render file or its SHA256 is missing or changed.')
    return path

def actual_png(path):
    data=Path(path).read_bytes()
    if len(data)>64*1024*1024 or data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Rendered frame must be an actual PNG.')
    pos=8;image=None;idat=[];ended=False
    while pos+12<=len(data):
        n=struct.unpack('>I',data[pos:pos+4])[0];typ=data[pos+4:pos+8];chunk=data[pos+8:pos+8+n]
        if pos+12+n>len(data) or zlib.crc32(typ+chunk)&0xffffffff!=struct.unpack('>I',data[pos+8+n:pos+12+n])[0]:raise ValueError('Rendered PNG has invalid chunks or CRC.')
        if typ==b'IHDR':
            if image or n!=13:raise ValueError('Invalid PNG image header.')
            image=struct.unpack('>IIBBBBB',chunk)
        if typ==b'IDAT':idat.append(chunk)
        pos+=n+12
        if typ==b'IEND':ended=True;break
    if not ended or pos!=len(data) or not image or not idat:raise ValueError('Rendered PNG is incomplete.')
    width,height,depth,color,comp,filt,interlace=image
    channels={0:1,2:3,3:1,4:2,6:4}.get(color)
    if not channels or depth not in (1,2,4,8,16) or comp or filt or interlace or not 0<width<=16384 or not 0<height<=16384:raise ValueError('Unsupported native PNG layout.')
    expected=(1+math.ceil(width*channels*depth/8))*height
    decoder=zlib.decompressobj();raw=decoder.decompress(b''.join(idat),expected+1)
    if len(raw)!=expected or not decoder.eof:raise ValueError('Rendered PNG pixel data is invalid or incomplete.')
    row=1+math.ceil(width*channels*depth/8)
    if any(raw[i] not in range(5) for i in range(0,len(raw),row)):raise ValueError('Invalid PNG scanline filter.')
    return [width,height]

def model_version(reference):
    return reference.get('model_version') or next((t[len('latest-model-'):] for t in reference.get('tags',[]) if t.startswith('latest-model-')),None)

def prepare_result(value,request,root):
    manifest=value.get('manifest',value)
    if manifest.get('schema_version')!=1 or manifest.get('request_id')!=request['id']:raise ValueError('Result manifest does not match this immutable request.')
    if request.get('status') not in ('received_by_render_owner','actual_rendered_preview_published') or manifest.get('owner')!=request.get('received_by'):raise ValueError('The explicit render owner must receive this request before publishing.')
    if manifest.get('asset_policy')!='latest-approved' or request['brief'].get('asset_policy')!='latest-approved':raise ValueError('Render results must use the latest approved asset policy.')
    approval=request['brief'].get('production_approval',{})
    if approval.get('asset_policy')!='latest-approved' or not approval.get('model_version'):raise ValueError('This immutable request needs an explicit production-approved model version. Set project approved_model_version and create a new request.')
    source=manifest.get('source_sha256','');version=manifest.get('model_version')
    if version!=approval['model_version']:raise ValueError('Rendered model version differs from the immutable production approval contract.')
    if not re.fullmatch('[a-f0-9]{64}',source) or not isinstance(version,str) or not version:raise ValueError('Bind the actual source SHA256 and approved model version.')
    native_source=bound_file(manifest.get('native_source'))
    if manifest['native_source']['sha256']!=source:raise ValueError('Actual native source file differs from the declared source SHA256.')
    receipt_path=bound_file(manifest.get('completion_receipt'));receipt=json.loads(receipt_path.read_text())
    if receipt.get('request_id')!=request['id'] or receipt.get('brief_sha256')!=contract_digest(request['brief']):raise ValueError('Native completion receipt must bind this frozen request and exact brief hash.')
    if receipt.get('status')!='ACTUAL_NATIVE_RENDER_COMPLETE' or receipt.get('native_jobs_terminal_exit0') is not True:raise ValueError('Actual native terminal completion is required; queued/saved sources are not rendered results.')
    if receipt.get('source_sha256')!=source or receipt.get('model_version')!=version:raise ValueError('Native receipt source/model binding disagrees with the result.')
    proof_frames={(str(Path(f['path']).expanduser().resolve()),f['sha256']) for f in receipt.get('frames',[])}
    scenes={v['scene_id']:v for v in request['brief']['scenes']};results=manifest.get('results')
    if not isinstance(results,list) or not results or len(results)>1000:raise ValueError('Return actual scene frames, not an empty result.')
    prepared=[];all_paths=set();seen=set()
    for result in results:
        scene=scenes.get(result.get('scene_id'))
        if not scene or result.get('node_id')!=scene['node']['id'] or result['scene_id'] in seen:raise ValueError('Result node/scene identities do not match the request snapshot.')
        seen.add(result['scene_id']);reference=scene.get('reference') or {}
        # Donor reference source/model is historical camera/staging evidence.
        # New camera/source hashes are allowed when actual completion binds them
        # and the immutable production approval authorizes the rendered model.
        if not result.get('version') or not result.get('quality_label'):raise ValueError('Label the actual rendered version and preview quality.')
        bindings = result.get('rendered_effect_bindings')
        if scene.get('effects') and bindings is None:raise ValueError('Return rendered effect bindings for every requested effect, including its enabled state.')
        if bindings is not None:
            expected = [{k:e.get(k) for k in ('kind','preset_id','enabled','settings')} for e in scene.get('effects', [])]
            if bindings != expected:raise ValueError('Rendered effect bindings differ from the immutable scene request.')
            if receipt.get('rendered_effect_bindings_by_scene', {}).get(result['scene_id']) != bindings:raise ValueError('Rendered effects are not bound to the native completion receipt.')
        phases=result.get('frames',{})
        if set(phases)!=set(('start','middle','end')):raise ValueError('Return real start, middle and end PNGs.')
        admitted={}
        for phase in ('start','middle','end'):
            frame=phases[phase];path=bound_file(frame)
            if (str(path),frame['sha256']) not in proof_frames:raise ValueError('Frame is not bound by the actual native completion receipt.')
            receipt_frame=receipt.get('scene_frames',{}).get(result['scene_id'],{}).get(phase,{})
            if not receipt_frame.get('path') or str(Path(receipt_frame['path']).expanduser().resolve())!=str(path) or receipt_frame.get('sha256')!=frame['sha256']:raise ValueError('Native receipt must bind each frame to its exact scene and start/middle/end phase.')
            if str(path) in all_paths:raise ValueError('Use distinct actual frame paths for every sample, not duplicated previews.')
            all_paths.add(str(path));size=actual_png(path);admitted[phase]={'path':path,'sha256':frame['sha256'],'size':size}
        if len({tuple(f['size']) for f in admitted.values()})!=1:raise ValueError('One returned view must have consistent native frame dimensions.')
        prepared.append((result,scene,admitted))
    if receipt.get('actual_frame_count')!=len(all_paths) or len(proof_frames)!=len(all_paths):raise ValueError('Actual native completion frame count does not match the returned samples.')
    if set(scenes)!=seen:raise ValueError('Return every scene in the frozen request; create a scoped request for a partial preview.')
    manifest_hash=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    identical=request.get('result_manifest_sha256')==manifest_hash
    items=[]
    for result,scene,frames in prepared:
        rid='rendered-'+request['id']+'-'+result['scene_id'];urls={};hashes={};sizes={}
        folder=Path(root)/'assets'/'render-results'/request['id'];folder.mkdir(parents=True,exist_ok=True)
        for phase,f in frames.items():
            dest=folder/(result['scene_id']+'_'+phase+'_'+f['sha256'][:12]+'.png')
            if dest.exists() and digest(dest)!=f['sha256']:raise ValueError('A previously published preview changed; preserve it and use a new request.')
            if not dest.exists():
                temp=dest.with_suffix('.tmp');shutil.copyfile(f['path'],temp)
                if digest(temp)!=f['sha256']:raise ValueError('Rendered frame changed during local publication.')
                temp.replace(dest)
            urls[phase]='/assets/render-results/'+request['id']+'/'+dest.name;hashes[phase]=f['sha256'];sizes[phase]=f['size']
        items.append({'id':rid,'title':result.get('title') or scene['node'].get('title'),'version':result['version'],'orientation':'horizontal' if frames['start']['size'][0]>=frames['start']['size'][1] else 'vertical','status':'actual_rendered_preview','status_reason':result['quality_label'],'tags':['actual-native-render','returned-preview','latest-model-'+version],'model_version':version,'geometry_policy':'latest-approved','picture_source_sha256':source,'native_source':str(native_source),'brief_sha256':contract_digest(request['brief']),'source':str(receipt_path),'sha256':manifest['completion_receipt']['sha256'],'frames':urls,'image':urls['middle'],'frame_sha256':hashes,'native_frame_size':sizes,'source_interval':{'start_s':0,'end_s':scene['node']['duration_s']},'reference_source_interval':reference.get('source_interval'), 'requested_duration_s':scene['node']['duration_s'],'sample_global_frames':result.get('sample_global_frames'),'producer':manifest['owner'],'request_id':request['id'],'request_scene_id':result['scene_id'],'request_node_id':result['node_id'],'provenance_receipt':str(receipt_path),'provenance_receipt_sha256':manifest['completion_receipt']['sha256'],'notes':'Actual native rendered preview returned by the explicit owner. '+result['quality_label']+'. Original source frames and user board arrangement preserved.'})
    for item, result in zip(items, results):
        if 'rendered_effect_bindings' in result:
            item['rendered_effect_bindings'] = result['rendered_effect_bindings']
        item['requires_native_review'] = bool(result.get('requires_native_review', False))
        if result.get('native_source_plan'):
            item['native_source_plan'] = result['native_source_plan']
    return (None if identical else items),manifest_hash
