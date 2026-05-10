const canvas = document.getElementById("helixOrb");
const ctx = canvas.getContext("2d");

canvas.width = 560;
canvas.height = 560;

window.HELIX_ORB_MODE = window.HELIX_ORB_MODE || "idle";
window.HELIX_AUDIO_LEVEL = window.HELIX_AUDIO_LEVEL || 0;

const center = { x: canvas.width / 2, y: canvas.height / 2 };

const POINTS = 165;
const RADIUS = 160;

const points = [];

for (let i = 0; i < POINTS; i++) {
  const theta = Math.random() * Math.PI * 2;
  const phi = Math.acos(2 * Math.random() - 1);

  points.push({
    x: RADIUS * Math.sin(phi) * Math.cos(theta),
    y: RADIUS * Math.sin(phi) * Math.sin(theta),
    z: RADIUS * Math.cos(phi),
    size: 1 + Math.random() * 1.9,
    glow: Math.random(),
    offset: Math.random() * Math.PI * 2,
  });
}

const state = {
  speed: 0.004,
  radiusPulse: 1,
  lineAlpha: 0.32,
  pointGlow: 0.6,
  coreGlow: 0.45,
  audio: 0,
};

function lerp(current, target, amount) {
  return current + (target - current) * amount;
}

function getTargetState() {
  const mode = window.HELIX_ORB_MODE;

  if (mode === "listening") {
    return {
      speed: 0.007,
      radiusPulse: 1.08,
      lineAlpha: 0.45,
      pointGlow: 0.8,
      coreGlow: 0.7,
    };
  }

  if (mode === "processing") {
    return {
      speed: 0.012,
      radiusPulse: 1.13,
      lineAlpha: 0.55,
      pointGlow: 0.95,
      coreGlow: 0.9,
    };
  }

  if (mode === "speaking") {
    return {
      speed: 0.016,
      radiusPulse: 1.22,
      lineAlpha: 0.72,
      pointGlow: 1.15,
      coreGlow: 1.25,
    };
  }

  return {
    speed: 0.004,
    radiusPulse: 1.04,
    lineAlpha: 0.34,
    pointGlow: 0.65,
    coreGlow: 0.5,
  };
}

function updateState() {
  const target = getTargetState();
  const audioTarget = Math.min(window.HELIX_AUDIO_LEVEL || 0, 1);

  state.speed = lerp(state.speed, target.speed, 0.05);
  state.radiusPulse = lerp(state.radiusPulse, target.radiusPulse, 0.05);
  state.lineAlpha = lerp(state.lineAlpha, target.lineAlpha, 0.05);
  state.pointGlow = lerp(state.pointGlow, target.pointGlow, 0.05);
  state.coreGlow = lerp(state.coreGlow, target.coreGlow, 0.05);
  state.audio = lerp(state.audio, audioTarget, 0.16);
}

function rotateY(p, angle) {
  return {
    ...p,
    x: p.x * Math.cos(angle) - p.z * Math.sin(angle),
    z: p.x * Math.sin(angle) + p.z * Math.cos(angle),
  };
}

function rotateX(p, angle) {
  return {
    ...p,
    y: p.y * Math.cos(angle) - p.z * Math.sin(angle),
    z: p.y * Math.sin(angle) + p.z * Math.cos(angle),
  };
}

let rotation = 0;

function drawBackgroundGlow(time, pulse) {
  const glow = ctx.createRadialGradient(
    center.x,
    center.y,
    10,
    center.x,
    center.y,
    265
  );

  const alpha = 0.16 + state.coreGlow * 0.22 + state.audio * 0.28;

  glow.addColorStop(0, `rgba(120, 245, 255, ${alpha})`);
  glow.addColorStop(0.35, `rgba(0, 160, 255, ${alpha * 0.55})`);
  glow.addColorStop(1, "rgba(0, 0, 0, 0)");

  ctx.beginPath();
  ctx.fillStyle = glow;
  ctx.arc(center.x, center.y, 250 * pulse, 0, Math.PI * 2);
  ctx.fill();

  ctx.beginPath();
  ctx.arc(center.x, center.y, 175 * pulse, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(90, 230, 255, ${0.12 + state.coreGlow * 0.12})`;
  ctx.lineWidth = 1.2 + state.audio * 1.4;
  ctx.stroke();

  ctx.beginPath();
  ctx.arc(center.x, center.y, 205 * pulse, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(0, 225, 255, ${0.06 + state.audio * 0.22})`;
  ctx.lineWidth = 1;
  ctx.stroke();
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  updateState();

  const time = Date.now() * 0.003;

  const idleBreathing = Math.sin(time * 1.4) * 0.04;
  const speakWave =
    window.HELIX_ORB_MODE === "speaking"
      ? Math.sin(time * 8.5) * 0.055
      : 0;

  const audioPulse = state.audio * 0.26;

  const pulse = state.radiusPulse + idleBreathing + speakWave + audioPulse;

  rotation += state.speed;

  drawBackgroundGlow(time, pulse);

  const projected = points.map((p) => {
    let r = rotateY(p, rotation);
    r = rotateX(r, Math.sin(rotation * 0.45) * 0.22);

    const perspective = 420 / (420 + r.z);
    const nodeBreath = 1 + Math.sin(time * 1.5 + p.offset) * 0.055;

    return {
      x: center.x + r.x * perspective * pulse * nodeBreath,
      y: center.y + r.y * perspective * pulse * nodeBreath,
      z: r.z,
      size: p.size * perspective,
      alpha: Math.max(0.25, perspective),
      glow: p.glow,
    };
  });

  for (let i = 0; i < projected.length; i++) {
    for (let j = i + 1; j < projected.length; j++) {
      const dx = projected[i].x - projected[j].x;
      const dy = projected[i].y - projected[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (dist < 72) {
        const alpha = state.lineAlpha * (1 - dist / 72);

        ctx.beginPath();
        ctx.moveTo(projected[i].x, projected[i].y);
        ctx.lineTo(projected[j].x, projected[j].y);
        ctx.strokeStyle = `rgba(120, 220, 255, ${alpha})`;
        ctx.lineWidth = 0.8 + state.audio * 0.9;
        ctx.stroke();
      }
    }
  }

  projected.forEach((p) => {
    const flicker = 0.75 + Math.sin(time * 2.3 + p.glow * 10) * 0.35;
    const pointSize = Math.max(1.4, p.size * (2 + state.audio * 1.8));

    ctx.beginPath();
    ctx.arc(p.x, p.y, pointSize, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(205, 250, 255, ${p.alpha * 0.9})`;
    ctx.shadowBlur = 8 + state.pointGlow * 14 * flicker + state.audio * 18;
    ctx.shadowColor = "#35eaff";
    ctx.fill();
  });

  for (let i = 0; i < projected.length; i += 19) {
    const p = projected[i];
    const glowSize = 5 + state.coreGlow * 4 + state.audio * 9;

    ctx.beginPath();
    ctx.arc(p.x, p.y, glowSize, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(80, 235, 255, ${0.32 + state.coreGlow * 0.24})`;
    ctx.shadowBlur = 24 + state.coreGlow * 15 + state.audio * 28;
    ctx.shadowColor = "#00eaff";
    ctx.fill();
  }

  const corePulse =
    1 +
    Math.sin(time * 3) * 0.12 +
    state.audio * 0.55 +
    (window.HELIX_ORB_MODE === "speaking" ? Math.sin(time * 10) * 0.12 : 0);

  ctx.beginPath();
  ctx.arc(center.x, center.y, 8 * corePulse, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(235, 255, 255, ${0.8 + state.coreGlow * 0.18})`;
  ctx.shadowBlur = 28 + state.coreGlow * 28 + state.audio * 45;
  ctx.shadowColor = "#00eaff";
  ctx.fill();

  ctx.shadowBlur = 0;

  requestAnimationFrame(draw);
}

draw();