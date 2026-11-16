import * as THREE from 'three';
import { STLLoader } from './vendor/STLLoader.js';
import { gripperMetrics, gripperPartPose } from './gripper-kinematics.mjs';

export async function loadGripperModel(baseUrl = './models/custom_gripper/') {
  const response = await fetch(baseUrl + 'model.json');
  if (!response.ok) throw new Error('无法读取夹爪模型清单');
  const model = await response.json();
  const loader = new STLLoader();
  const geometries = new Map();
  await Promise.all(Object.entries(model.geometry).map(async ([key, path]) => {
    const geometry = await loader.loadAsync(baseUrl + path);
    geometry.computeVertexNormals();
    geometries.set(key, geometry);
  }));
  const group = new THREE.Group();
  group.name = 'ZCJD reconstructed gripper';
  const objects = model.parts.map(part => {
    const metal = part.geometry === 'link' || part.geometry.includes('bolt');
    const material = new THREE.MeshStandardMaterial({ color: part.color,
      roughness: metal ? .28 : .58, metalness: metal ? .72 : .12 });
    const object = new THREE.Mesh(geometries.get(part.geometry), material);
    object.castShadow = true;
    object.receiveShadow = true;
    object.name = part.name;
    group.add(object);
    return { part, object };
  });
  function setOpening(opening, explode = 0) {
    const metrics = gripperMetrics(model.parameters, opening);
    for (const { part, object } of objects) {
      const state = gripperPartPose(part, model.parameters, opening, explode);
      object.position.set(...state.position);
      object.rotation.z = state.rotation;
    }
    return metrics;
  }
  setOpening(model.parameters.default_open_fraction);
  return { model, group, objects, setOpening };
}
