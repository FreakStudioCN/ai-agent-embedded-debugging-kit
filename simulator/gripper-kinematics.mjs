// Shared by the independent gripper viewer and the mounted robot assembly.
export function gripperMetrics(parameters, opening) {
  if (!Number.isFinite(opening) || opening < 0 || opening > 1) {
    throw new Error('夹爪开度应在 0–100% 内');
  }
  const p = parameters;
  const half = p.pivot_spacing / 2;
  const closed = Math.asin((p.jaw_inner_offset - half) / p.crank_length);
  const angle = closed + opening * (p.open_angle_degrees * Math.PI / 180 - closed);
  return {
    angle,
    gap: Math.max(0, p.pivot_spacing + 2 * p.crank_length * Math.sin(angle) - 2 * p.jaw_inner_offset),
    reach: p.pivot_forward + p.crank_length * Math.cos(angle) + (p.jaw_length + 5) / 2,
    contactHeight: (p.jaw_bottom ?? 0) + p.jaw_height / 2,
  };
}

export function gripperPartPose(part, parameters, opening, explode = 0) {
  const p = parameters;
  const half = p.pivot_spacing / 2;
  const { angle } = gripperMetrics(p, opening);
  const side = part.side || 0;
  let position;
  let rotation = 0;
  let layer = 0;
  switch (part.motion) {
    case 'fixed':
      position = [...part.position];
      layer = part.geometry === 'base' ? 0 : 3.2;
      break;
    case 'gear':
      position = [side * half, p.pivot_forward, p.gear_bottom];
      rotation = -side * angle;
      layer = 1;
      break;
    case 'link':
      position = [side * (half + p.parallel_offset), p.pivot_forward, p.outer_link_bottom];
      rotation = -side * angle;
      layer = 2.4;
      break;
    case 'finger':
    case 'pin':
      position = [side * (half + p.crank_length * Math.sin(angle)),
        p.pivot_forward + p.crank_length * Math.cos(angle), (p.jaw_bottom ?? 0) + (part.motion === 'pin' ? -.5 : 0)];
      if (part.motion === 'pin') position[0] += side * (part.outer || 0) * p.parallel_offset;
      layer = part.motion === 'pin' ? 3.8 : 1.7;
      break;
    default: throw new Error('未知零件运动类型');
  }
  position[2] += layer * explode * 12;
  return { position, rotation };
}

// CAD arm axes: +X forward, +Y across the wrist, +Z up.
// Gripper axes: +X lateral, +Y toward the fingers, +Z normal to its plate.
// This mounting orientation keeps the photographed fingers pointing downward.
export const GRIPPER_MOUNT_BASIS = Object.freeze([
  [0, -1, 0], [0, 0, -1], [1, 0, 0],
]);
