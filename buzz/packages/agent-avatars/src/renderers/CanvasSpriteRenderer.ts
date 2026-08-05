import { AvatarStateEvent } from "../AvatarStateMachine";

export class CanvasSpriteRenderer {
  private ctx: CanvasRenderingContext2D | null = null;
  private animationFrameId: number | null = null;
  private currentState: AvatarStateEvent = { s: "idle", e: "neutral", i: 1, t: 0 };
  private currentEmotion = "neutral";
  private emotionIntensity = 1.0;
  private lastFrameTime = 0;
  
  // Animation Easing Variables
  private currentMouthWidth = 40;
  private currentMouthHeight = 8;
  private targetMouthWidth = 40;
  private targetMouthHeight = 8;
  
  private currentEyebrowTilt = 0;
  private targetEyebrowTilt = 0;

  // Viseme state
  private currentViseme = "rest";
  private visemeTimeoutId: any = null;

  // Idle movement cycles
  private blinkState = 0; // 0 = open, 1 = closed
  private blinkTimer = 0;
  private breatheCycle = 0;

  async mount(el: HTMLElement) {
    const canvas = document.createElement("canvas");
    canvas.width = 400; canvas.height = 400;
    el.appendChild(canvas);
    this.ctx = canvas.getContext("2d");
    this.startRenderLoop();
  }

  applyState(e: AvatarStateEvent) {
    this.currentState = e;
    this.currentEmotion = e.e || "neutral";
    this.emotionIntensity = e.i || 1.0;
    // Force a blink on state transitions to simulate eye refocusing
    this.triggerBlink();
  }

  applyViseme(viseme: string, durationMs: number) {
    this.currentViseme = viseme;
    if (this.visemeTimeoutId) {
      clearTimeout(this.visemeTimeoutId);
    }
    this.visemeTimeoutId = setTimeout(() => {
      this.currentViseme = "rest";
    }, durationMs);
  }

  applyEmotion(emotion: string, intensity: number) {
    this.currentEmotion = emotion;
    this.emotionIntensity = intensity;
  }

  private triggerBlink() {
    this.blinkState = 1;
    setTimeout(() => {
      this.blinkState = 0;
    }, 120);
  }

  private startRenderLoop() {
    const loop = (timestamp: number) => {
      const elapsed = timestamp - this.lastFrameTime;
      if (elapsed > 16) { // Draw at ~60fps
        this.updatePhysics(elapsed);
        this.render(timestamp);
        this.lastFrameTime = timestamp;
      }
      this.animationFrameId = requestAnimationFrame(loop);
    };
    this.animationFrameId = requestAnimationFrame(loop);
  }

  private updatePhysics(elapsed: number) {
    const { s } = this.currentState;
    
    // 1. Natural Random Blinking
    this.blinkTimer += elapsed;
    if (this.blinkTimer > 3000 + Math.random() * 4000) {
      this.triggerBlink();
      this.blinkTimer = 0;
    }

    // 2. Set Target Mouth Dimensions based on Visemes & State
    if (s === "speaking") {
      switch (this.currentViseme) {
        case "A":
          this.targetMouthWidth = 35;
          this.targetMouthHeight = 40;
          break;
        case "E":
          this.targetMouthWidth = 55;
          this.targetMouthHeight = 12;
          break;
        case "I":
          this.targetMouthWidth = 48;
          this.targetMouthHeight = 18;
          break;
        case "O":
          this.targetMouthWidth = 30;
          this.targetMouthHeight = 35;
          break;
        case "U":
          this.targetMouthWidth = 20;
          this.targetMouthHeight = 20;
          break;
        case "MBP":
          this.targetMouthWidth = 38;
          this.targetMouthHeight = 2; // Flat closed line
          break;
        case "FV":
          this.targetMouthWidth = 38;
          this.targetMouthHeight = 6; // Thin closed F shape
          break;
        case "wide":
          this.targetMouthWidth = 55;
          this.targetMouthHeight = 6;
          break;
        case "narrow":
          this.targetMouthWidth = 20;
          this.targetMouthHeight = 10;
          break;
        case "rest":
        default:
          this.targetMouthWidth = 40;
          this.targetMouthHeight = 5;
          break;
      }
    } else if (s === "thinking") {
      this.targetMouthWidth = 30;
      this.targetMouthHeight = 3;
    } else {
      this.targetMouthWidth = 40;
      this.targetMouthHeight = 6;
    }

    // 3. Set Eyebrow target tilts based on Emotion
    switch (this.currentEmotion) {
      case "happy":
        this.targetEyebrowTilt = -0.15; // Raised, happy curve
        break;
      case "sad":
        this.targetEyebrowTilt = 0.2; // Drooping sad slant
        break;
      case "focused":
      case "curious":
        this.targetEyebrowTilt = 0.1; // Serious slant
        break;
      default:
        this.targetEyebrowTilt = 0.0;
        break;
    }

    // 4. Smooth Easing Interpolations (No snapping)
    this.currentMouthWidth += (this.targetMouthWidth - this.currentMouthWidth) * 0.35;
    this.currentMouthHeight += (this.targetMouthHeight - this.currentMouthHeight) * 0.35;
    this.currentEyebrowTilt += (this.targetEyebrowTilt - this.currentEyebrowTilt) * 0.2;
  }

  private render(timestamp: number) {
    if (!this.ctx) return;
    const { s } = this.currentState;
    this.ctx.clearRect(0, 0, 400, 400);

    // 1. Subtle Idle Breathing / Head Sway using Sine Waves
    const breatheOffset = Math.sin(timestamp / 400) * 3;
    const headSway = Math.cos(timestamp / 800) * 2;
    
    const centerX = 200 + headSway;
    const centerY = 150 + breatheOffset;

    // Face base colors matches emotion
    const colors: Record<string, string> = { neutral: "#4A90E2", happy: "#7ED321", sad: "#9013FE", focused: "#F5A623" };
    this.ctx.fillStyle = colors[this.currentEmotion] || colors.neutral;

    // Draw Head
    this.ctx.beginPath();
    this.ctx.arc(centerX, centerY, 80, 0, Math.PI * 2);
    this.ctx.fill();

    // 2. Draw Eyes
    this.ctx.fillStyle = "#fff";
    const leftEyeX = centerX - 25;
    const rightEyeX = centerX + 25;
    const eyeY = centerY - 15;
    const eyeRadius = 10;

    if (this.blinkState === 1) {
      // Draw closed eye slits (blinking)
      this.ctx.strokeStyle = "#000";
      this.ctx.lineWidth = 3;
      // Left eye slit
      this.ctx.beginPath();
      this.ctx.moveTo(leftEyeX - 10, eyeY);
      this.ctx.lineTo(leftEyeX + 10, eyeY);
      this.ctx.stroke();
      // Right eye slit
      this.ctx.beginPath();
      this.ctx.moveTo(rightEyeX - 10, eyeY);
      this.ctx.lineTo(rightEyeX + 10, eyeY);
      this.ctx.stroke();
    } else {
      // Draw open eyes matching emotion shapes
      this.ctx.beginPath();
      this.ctx.arc(leftEyeX, eyeY, eyeRadius, 0, Math.PI * 2);
      this.ctx.arc(rightEyeX, eyeY, eyeRadius, 0, Math.PI * 2);
      this.ctx.fill();

      // Draw Pupil pupils
      this.ctx.fillStyle = "#000";
      this.ctx.beginPath();
      this.ctx.arc(leftEyeX, eyeY, 4, 0, Math.PI * 2);
      this.ctx.arc(rightEyeX, eyeY, 4, 0, Math.PI * 2);
      this.ctx.fill();
    }

    // 3. Draw Eyebrows (Driven by emotion angles)
    this.ctx.strokeStyle = "#000";
    this.ctx.lineWidth = 4;
    this.ctx.lineCap = "round";

    // Left Eyebrow
    this.ctx.beginPath();
    this.ctx.moveTo(leftEyeX - 12, eyeY - 18 - this.currentEyebrowTilt * 10);
    this.ctx.lineTo(leftEyeX + 12, eyeY - 18 + this.currentEyebrowTilt * 10);
    this.ctx.stroke();

    // Right Eyebrow
    this.ctx.beginPath();
    this.ctx.moveTo(rightEyeX - 12, eyeY - 18 + this.currentEyebrowTilt * 10);
    this.ctx.lineTo(rightEyeX + 12, eyeY - 18 - this.currentEyebrowTilt * 10);
    this.ctx.stroke();

    // 4. Draw Mouth (Interpolated dimensions)
    this.ctx.fillStyle = "#000";
    const xPos = centerX - this.currentMouthWidth / 2;
    const yPos = centerY + 35 - this.currentMouthHeight / 2;
    
    // Draw rounded rectangle for smoother mouth shape feel
    this.ctx.beginPath();
    this.ctx.roundRect(xPos, yPos, this.currentMouthWidth, this.currentMouthHeight, 4);
    this.ctx.fill();

    // Draw state label
    this.ctx.fillStyle = "#fff";
    this.ctx.font = "14px sans-serif";
    this.ctx.fillText(s.toUpperCase(), centerX - 30, centerY + 130);
  }

  unmount() {
    if (this.animationFrameId) cancelAnimationFrame(this.animationFrameId);
    if (this.visemeTimeoutId) clearTimeout(this.visemeTimeoutId);
    this.ctx = null;
  }
}
