// Browser-side proctoring. Everything runs on the student's device; only events and small JPEG snapshots are uploaded.
//  - Always (when camera is required): periodic snapshots, camera-blocked detection.
//  - Mic enabled: simple voice-activity detection (volume above the room's baseline for a few seconds).
//  - AI proctoring enabled: face absent / several faces / head turned away / different person (face-api.js) and
//    mobile phone in view (COCO-SSD). Models load from a CDN; if they cannot load, proctoring continues without AI
//    and an informational "ai_unavailable" event is recorded.
const FACE_API = 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.13/dist/face-api.js';
const FACE_MODELS = 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.13/model/';
const TFJS = 'https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js';
const COCO = 'https://cdn.jsdelivr.net/npm/@tensorflow-models/coco-ssd@2.2.3/dist/coco-ssd.min.js';

const loadScript = (src) => new Promise((res, rej) => {
  if (document.querySelector(`script[src="${src}"]`)) return res();
  const s = document.createElement('script'); s.src = src; s.async = true; s.onload = res; s.onerror = () => rej(new Error('load ' + src)); document.head.appendChild(s);
});

export async function checkCamera({ mic = false } = {}) {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser cannot access the camera (HTTPS or localhost is required).');
  const s = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: mic });
  return s;
}

export class Proctor {
  constructor({ exam, report, snapshot, onStatus }) {
    Object.assign(this, { exam, report, snapshot, onStatus: onStatus || (() => {}) });
    this.timers = []; this.stream = null; this.video = null; this.last = {}; this.strikes = {};
    this.enrolled = null; this.models = false; this.coco = null; this.stopped = false;
  }
  emit(type, detail, minGap = 8000) {   // throttled so one long incident does not flood the log
    const now = Date.now();
    if (this.last[type] && now - this.last[type] < minGap) return;
    this.last[type] = now; this.report(type, detail); if (this.exam.camera_required) this.shot(type);
  }
  async start(host) {
    this.stream = await checkCamera({ mic: this.exam.mic_enabled });
    this.video = document.createElement('video');
    Object.assign(this.video, { muted: true, playsInline: true, autoplay: true, srcObject: this.stream });
    await this.video.play().catch(() => {});
    if (host) { host.innerHTML = '<span class="dot" aria-hidden="true"></span>'; host.appendChild(this.video); }
    this.stream.getVideoTracks().forEach((t) => t.addEventListener('ended', () => this.emit('camera_blocked', 'camera stopped', 15000)));
    this.report('camera_ready');
    const every = Math.max(10, this.exam.snapshot_interval || 30) * 1000;
    this.timers.push(setInterval(() => this.shot('periodic'), every));
    setTimeout(() => this.shot('start'), 1500);
    if (this.exam.mic_enabled) this.startVoice();
    if (this.exam.ai_proctoring) this.startAI();
  }
  shot(label) {
    if (!this.video || this.stopped || !this.video.videoWidth) return;
    const c = document.createElement('canvas'); c.width = 320; c.height = Math.round(320 * this.video.videoHeight / this.video.videoWidth);
    const g = c.getContext('2d'); g.drawImage(this.video, 0, 0, c.width, c.height);
    this.snapshot(c.toDataURL('image/jpeg', 0.6), label);
  }
  // ----------------------------------------------------------- voice
  startVoice() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)(); this.ctx = ctx;
      const an = ctx.createAnalyser(); an.fftSize = 1024; ctx.createMediaStreamSource(this.stream).connect(an);
      const buf = new Float32Array(an.fftSize); let base = 0, n = 0, loud = 0;
      this.timers.push(setInterval(() => {
        an.getFloatTimeDomainData(buf); const rms = Math.sqrt(buf.reduce((a, v) => a + v * v, 0) / buf.length);
        if (n < 5) { base = (base * n + rms) / (n + 1); n++; return; }       // first 5 s calibrate room noise
        loud = rms > Math.max(0.05, base * 3) ? loud + 1 : 0;
        if (loud >= 3) { this.emit('voice', 'sustained speech/noise', 20000); loud = 0; }
      }, 1000));
    } catch { /* no audio: ignore */ }
  }
  // ----------------------------------------------------------- AI
  async startAI() {
    try {
      this.onStatus('Loading AI proctoring…');
      await loadScript(FACE_API);
      const fa = window.faceapi; this.fa = fa;
      await Promise.all([fa.nets.tinyFaceDetector.loadFromUri(FACE_MODELS), fa.nets.faceLandmark68TinyNet.loadFromUri(FACE_MODELS), fa.nets.faceRecognitionNet.loadFromUri(FACE_MODELS)]);
      this.models = true;
      this.timers.push(setInterval(() => this.faceTick(), 2000));
      this.onStatus('AI proctoring active');
    } catch (e) { this.report('ai_unavailable', 'face models failed to load'); this.onStatus('AI models unavailable — basic proctoring only'); }
    try {                                    // phone detection is optional and heavier
      await loadScript(TFJS); await loadScript(COCO);
      this.coco = await window.cocoSsd.load({ base: 'lite_mobilenet_v2' });
      this.timers.push(setInterval(() => this.phoneTick(), 5000));
    } catch { this.coco = null; }
  }
  strike(key, cond, need = 2) { this.strikes[key] = cond ? (this.strikes[key] || 0) + 1 : 0; return this.strikes[key] >= need; }
  async faceTick() {
    if (!this.models || this.stopped || !this.video || this.video.readyState < 2) return;
    const fa = this.fa;
    let faces;
    try { faces = await fa.detectAllFaces(this.video, new fa.TinyFaceDetectorOptions({ inputSize: 224, scoreThreshold: 0.5 })).withFaceLandmarks(true).withFaceDescriptors(); } catch { return; }
    if (this.strike('none', faces.length === 0)) this.emit('face_lost', 'no face visible');
    if (this.strike('multi', faces.length > 1, 1)) this.emit('multi_face', `${faces.length} faces`);
    if (faces.length !== 1) return;
    const f = faces[0];
    const jaw = f.landmarks.getJawOutline(), nose = f.landmarks.getNose();
    const ratio = (nose[3].x - jaw[0].x) / Math.max(1, jaw[jaw.length - 1].x - jaw[0].x);      // 0.5 = facing the screen
    if (this.strike('gaze', ratio < 0.3 || ratio > 0.7, 3)) this.emit('gaze_away', `head turned (${ratio.toFixed(2)})`);
    if (!this.enrolled) { this.enrolled = f.descriptor; return; }                               // first clear face = the candidate
    const d = fa.euclideanDistance(this.enrolled, f.descriptor);
    if (this.strike('id', d > 0.6, 3)) this.emit('identity_mismatch', `distance ${d.toFixed(2)}`, 30000);
  }
  async phoneTick() {
    if (!this.coco || this.stopped || !this.video || this.video.readyState < 2) return;
    try { const preds = await this.coco.detect(this.video); if (preds.some((p) => p.class === 'cell phone' && p.score > 0.55)) this.emit('phone', 'mobile phone in view', 20000); } catch { /* ignore */ }
  }
  stop() {
    this.stopped = true; this.timers.forEach(clearInterval); this.timers = [];
    this.stream?.getTracks().forEach((t) => t.stop()); this.ctx?.close?.().catch(() => {}); this.video = null;
  }
}
