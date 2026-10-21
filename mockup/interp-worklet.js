/* 통역용 마이크 탭(AudioWorklet).
   메인 스레드에서 하던 리샘플·PCM 변환·음량 계산을 오디오 스레드로 옮긴다 —
   자막이 갱신되거나 대화 기록이 길어져도 입력이 끊기지 않는다.
   - 16 kHz 모노 PCM16 을 100 ms(1600 샘플)씩 잘라 보낸다.
   - 음량(RMS)은 128프레임마다 알린다. 화면은 requestAnimationFrame 에서만 읽는다(그리기 폭주 방지). */
class InterpTap extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = (options && options.processorOptions) || {};
    this.inRate = o.inRate || sampleRate;
    this.ratio = this.inRate / 16000;
    this.need = Math.round(1600 * this.ratio);
    this.buf = new Float32Array(this.need * 2);
    this.len = 0;
    this.muted = false;
    this.port.onmessage = e => { this.muted = e.data === 'mute'; };
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    let sum = 0;
    for (let i = 0; i < ch.length; i++) sum += ch[i] * ch[i];
    this.port.postMessage({ level: Math.sqrt(sum / ch.length) });
    if (this.muted) return true;                       // 음소거: 올리지도, 보내지도 않는다
    if (this.len + ch.length > this.buf.length) {      // 넘치면 앞을 버린다(메모리 고정)
      const keep = this.buf.subarray(this.len - this.need, this.len);
      this.buf.set(keep, 0); this.len = keep.length;
    }
    this.buf.set(ch, this.len); this.len += ch.length;
    while (this.len >= this.need) {
      const out = new Int16Array(1600);
      for (let i = 0; i < 1600; i++) {
        const v = Math.max(-1, Math.min(1, this.buf[Math.floor(i * this.ratio)] || 0));
        out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
      }
      this.port.postMessage({ pcm: out.buffer }, [out.buffer]);
      this.buf.copyWithin(0, this.need, this.len); this.len -= this.need;
    }
    return true;
  }
}
registerProcessor('interp-tap', InterpTap);
