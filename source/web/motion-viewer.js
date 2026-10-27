import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';

export function createMotionViewer(container,metadataUrl,framesUrl,onTime=()=>{}){
 const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0xf0f3f8);renderer.outputColorSpace=THREE.SRGBColorSpace;
 container.replaceChildren(renderer.domElement);
 const scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xffffff,0x687589,2.1));
 const light=new THREE.DirectionalLight(0xffffff,2.7);light.position.set(3,5,4);scene.add(light);
 const camera=new THREE.PerspectiveCamera(35,1,.001,100);
 const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
 const ground=new THREE.GridHelper(6,30,0xb7c3d5,0xd6dee9);scene.add(ground);
 let disposed=false,model=null,nodes=[],metadata=null,frames=null,time=0,playing=true,speed=1,loop=true,last=performance.now();
 let cameraReady=false;const morphMeshes=[];
 const tmpQ=new THREE.Quaternion(),nextQ=new THREE.Quaternion();
 function reset(){if(!model)return;model.updateMatrixWorld(true);const box=new THREE.Box3(),point=new THREE.Vector3();
  // Measure the deformed vertices, not the imported mesh's cached bind-pose box.
  model.traverse(o=>{if(o.isSkinnedMesh){for(let i=0;i<o.geometry.attributes.position.count;i++){o.getVertexPosition(i,point);o.localToWorld(point);box.expandByPoint(point);}}});
  const size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3()),radius=size.length()*.5;
  const tangent=Math.tan(THREE.MathUtils.degToRad(camera.fov/2));const distance=Math.max(size.y*.5/tangent,size.x*.5/(tangent*camera.aspect))+size.z*.5;
  controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(0,0,distance*1.25));camera.near=Math.max(radius/1000,.0001);camera.far=100;camera.updateProjectionMatrix();controls.update();cameraReady=true;ground.position.y=box.min.y-.005;
 }
 function resize(){renderer.setSize(Math.max(1,container.clientWidth),Math.max(1,container.clientHeight));camera.aspect=container.clientWidth/Math.max(1,container.clientHeight);camera.updateProjectionMatrix();}
 const observer=new ResizeObserver(resize);observer.observe(container);resize();
 function pose(){if(!metadata||!frames)return;const index=Math.min(metadata.frameCount-1,time*metadata.fps),a=Math.floor(index),b=Math.min(a+1,metadata.frameCount-1),u=index-a;
  for(let i=0;i<metadata.boneCount;i++){
   const bone=nodes[metadata.nodes[i]],left=(a*metadata.boneCount+i)*7,right=(b*metadata.boneCount+i)*7;
   bone.position.set(-(frames[left]*(1-u)+frames[right]*u),frames[left+1]*(1-u)+frames[right+1]*u,frames[left+2]*(1-u)+frames[right+2]*u);
   tmpQ.set(frames[left+3],-frames[left+4],-frames[left+5],frames[left+6]);nextQ.set(frames[right+3],-frames[right+4],-frames[right+5],frames[right+6]);bone.quaternion.copy(tmpQ.slerp(nextQ,u));
  }
  if(metadata.kind==='lip'){
   const left=metadata.vowels[a],right=metadata.vowels[b];
   for(const mesh of morphMeshes)for(const [name,index] of Object.entries(mesh.morphTargetDictionary||{})){
    if('AIUEO'.includes(name)&&name.length===1)mesh.morphTargetInfluences[index]=(left[name.toLowerCase()]||0)*(1-u)+(right[name.toLowerCase()]||0)*u;
   }
  }
  model.updateMatrixWorld(true);onTime(time,metadata.duration,playing);
 }
 function disposeObject(root){const textures=new Set();root.traverse(o=>{o.geometry?.dispose();for(const m of o.material?(Array.isArray(o.material)?o.material:[o.material]):[]){if(m.map)textures.add(m.map);if(m.userData.eyeHighlight)textures.add(m.userData.eyeHighlight);m.dispose();}});textures.forEach(t=>t.dispose());}
 const ready=Promise.all([fetch('/api/motion-model?v=expressions3').then(r=>{if(!r.ok)throw new Error('预览模型读取失败');return r.json();}),fetch(metadataUrl).then(r=>{if(!r.ok)throw new Error('动作信息读取失败');return r.json();}),fetch(framesUrl).then(r=>{if(!r.ok)throw new Error('动作帧读取失败');return r.arrayBuffer();})]).then(async ([rig,meta,buffer])=>{
  if(disposed)return;
  if(!rig.humanoid||rig.id!==meta.model)throw new Error('预览模型与动作骨架版本不一致');
  if(buffer.byteLength!==meta.frameCount*meta.boneCount*28)throw new Error('动作帧数据不完整');
  metadata=meta;frames=new Float32Array(buffer);model=new THREE.Group();model.name=rig.name;
  nodes=rig.nodes.map(n=>{const bone=new THREE.Bone();bone.name=n.name;bone.position.set(-n.position[0],n.position[1],n.position[2]);bone.quaternion.set(n.rotation[0],-n.rotation[1],-n.rotation[2],n.rotation[3]);bone.scale.fromArray(n.scale);return bone;});
  rig.nodes.forEach((n,i)=>(n.parent>=0?nodes[n.parent]:model).add(nodes[i]));
  const reflection=new THREE.Matrix4().makeScale(-1,1,1),loader=new THREE.TextureLoader(),textureLoads=[];
  for(const source of rig.meshes){
   const geometry=new THREE.BufferGeometry(),positions=new Float32Array(source.positions),normals=new Float32Array(source.normals),indices=new Uint32Array(source.indices);
   for(let i=0;i<positions.length;i+=3)positions[i]*=-1;for(let i=0;i<normals.length;i+=3)normals[i]*=-1;
   for(let i=0;i<indices.length;i+=3){const temp=indices[i+1];indices[i+1]=indices[i+2];indices[i+2]=temp;}
   geometry.setAttribute('position',new THREE.BufferAttribute(positions,3));geometry.setIndex(new THREE.BufferAttribute(indices,1));
   if(normals.length===positions.length)geometry.setAttribute('normal',new THREE.BufferAttribute(normals,3));else geometry.computeVertexNormals();
   if(source.uv)geometry.setAttribute('uv',new THREE.Float32BufferAttribute(source.uv,2));
   geometry.setAttribute('skinIndex',new THREE.Uint16BufferAttribute(source.joints,4));geometry.setAttribute('skinWeight',new THREE.Float32BufferAttribute(source.weights,4));
   if(source.morphs?.length){
    geometry.morphTargetsRelative=true;
    geometry.morphAttributes.position=source.morphs.map(shape=>{const values=new Float32Array(shape.positions);for(let i=0;i<values.length;i+=3)values[i]*=-1;const attribute=new THREE.BufferAttribute(values,3);attribute.name=shape.name;return attribute;});
   }
   const materials=(source.materials||[{color:0xb7c5db}]).map(info=>{
    const material=new THREE.MeshBasicMaterial({color:info.color,side:THREE.DoubleSide,alphaTest:info.alphaTest||0});
    if(info.texture)textureLoads.push(loader.loadAsync('/api/motion-textures/'+info.texture).then(map=>{map.colorSpace=THREE.SRGBColorSpace;map.wrapS=map.wrapT=THREE.ClampToEdgeWrapping;map.anisotropy=Math.min(4,renderer.capabilities.getMaxAnisotropy());if(info.offset)map.offset.fromArray(info.offset);material.map=map;material.needsUpdate=true;}));
    if(info.eye){
     if(info.highlight)textureLoads.push(loader.loadAsync('/api/motion-textures/'+info.highlight).then(map=>{map.colorSpace=THREE.SRGBColorSpace;map.wrapS=map.wrapT=THREE.ClampToEdgeWrapping;material.userData.eyeHighlight=map;}));
     material.onBeforeCompile=shader=>{
      shader.uniforms.scspEyeHigh={value:material.userData.eyeHighlight};shader.uniforms.scspEyeHighDelta={value:new THREE.Vector2((info.highlightOffset?.[0]||0)-(info.offset?.[0]||0),(info.highlightOffset?.[1]||0)-(info.offset?.[1]||0))};
      shader.fragmentShader='uniform sampler2D scspEyeHigh;\nuniform vec2 scspEyeHighDelta;\n'+shader.fragmentShader;
      shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>','#ifdef USE_MAP\nvec4 eyeTexel=texture2D(map,vMapUv);vec4 eyeHigh=texture2D(scspEyeHigh,vMapUv+scspEyeHighDelta);vec3 eyeBase=mix(vec3(1.0),eyeTexel.rgb,eyeTexel.a);diffuseColor*=vec4(mix(eyeBase,eyeHigh.rgb,eyeHigh.a),1.0);\n#endif');
     };material.customProgramCacheKey=()=>"scsp-eye-basic-v2";
    }
    return material;
   });
   for(const group of source.groups||[])geometry.addGroup(group.start,group.count,group.material);
   const mesh=new THREE.SkinnedMesh(geometry,materials.length===1?materials[0]:materials);mesh.name=source.name;mesh.frustumCulled=false;if(source.morphs?.length){mesh.updateMorphTargets();morphMeshes.push(mesh);}nodes[source.node].add(mesh);model.updateMatrixWorld(true);
   const inverses=source.bones.map((_,i)=>new THREE.Matrix4().fromArray(source.bindPoses,i*16).premultiply(reflection).multiply(reflection));
   // Unity bindposes already include the renderer's bind transform, as glTF IBMs do.
   const skeleton=new THREE.Skeleton(source.bones.map(i=>nodes[i]),inverses);mesh.bind(skeleton,new THREE.Matrix4());mesh.normalizeSkinWeights();
  }
  scene.add(model);await Promise.all(textureLoads);if(disposed){disposeObject(model);return;}pose();reset();if(meta.kind==='lip'){const box=new THREE.Box3().setFromObject(model),size=box.getSize(new THREE.Vector3());controls.target.set(0,box.max.y-size.y*.12,0);camera.position.set(0,controls.target.y,size.y*.55);controls.update();}last=performance.now();
  return metadata;
 });
 renderer.setAnimationLoop(()=>{if(disposed)return;const now=performance.now(),dt=Math.min((now-last)/1000,.1);last=now;
  if(metadata&&playing){time+=dt*speed;if(time>=metadata.duration){if(loop)time%=metadata.duration;else{time=metadata.duration;playing=false;}}pose();}
  if(cameraReady){controls.update();renderer.render(scene,camera);}
 });
 return {ready,reset,setPlaying(v){playing=v;onTime(time,metadata?.duration||0,playing);},seek(v){time=Math.max(0,Math.min(metadata?.duration||0,v));pose();},setSpeed(v){speed=v;},setLoop(v){loop=v;},dispose(){if(disposed)return;disposed=true;renderer.setAnimationLoop(null);observer.disconnect();controls.dispose();disposeObject(scene);renderer.dispose();renderer.forceContextLoss();frames=null;nodes=[];container.replaceChildren();}};
}
