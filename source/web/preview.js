import * as THREE from 'three';
import { GLTFLoader } from './vendor/GLTFLoader.js';
import { OrbitControls } from './vendor/OrbitControls.js';

export function createViewer(container, url) {
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5));
  renderer.setClearColor(0xeff0f6);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.replaceChildren(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.001, 10000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  let disposed = false, model;
  function resize() {
    renderer.setSize(container.clientWidth, container.clientHeight);
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
  }
  function release(object) {
    const textures = new Set();
    object.traverse(o => {
      o.geometry?.dispose();
      for (const material of o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : []) {
        for (const value of Object.values(material)) if(value?.isTexture) textures.add(value);
        material.dispose();
      }
    });
    textures.forEach(texture => texture.dispose());
  }
  function reset() {
    if (!model) return;
    const box = new THREE.Box3().setFromObject(model), size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3()), radius = size.length() * .5;
    const distance = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 1.15;
    controls.target.copy(center);
    camera.position.copy(center).add(new THREE.Vector3(0, radius * .1, distance));
    camera.near = Math.max(radius / 1000, .0001);camera.far = Math.max(distance * 100, 10);
    camera.updateProjectionMatrix();controls.minDistance = radius * .15;controls.maxDistance = distance * 10;controls.update();
  }
  const observer = new ResizeObserver(resize);observer.observe(container);resize();
  renderer.setAnimationLoop(() => {if (!disposed) {controls.update();renderer.render(scene, camera);}});
  const ready = new GLTFLoader().loadAsync(url).then(gltf => {
    if(disposed) {release(gltf.scene);return;}
    model = gltf.scene;scene.add(model);reset();
  });
  return {ready, reset, dispose() {
    if (disposed) return;
    disposed = true;renderer.setAnimationLoop(null);observer.disconnect();controls.dispose();
    if(model) release(model);
    renderer.dispose();renderer.forceContextLoss();container.replaceChildren();
  }};
}
