/**
 * A simultaneous A/B: both takes downmixed to mono and hard-panned, A left and B right.
 *
 * Playing two players at once is not a comparison — they start at different moments and the ear
 * cannot tell which take it is hearing. One track with A on one side and B on the other is a real
 * comparison: the balance control picks a side, and the centre is the sum of the two.
 *
 * It all happens in the page. The clips are already sitting in ComfyUI's temp directory and the page
 * has no server to process them, so the mixer fetches them, decodes them with the Web Audio API, and
 * hands back a WAV the ordinary player can play. The arithmetic that decides what lands in each
 * channel is plain and is tested without a browser; only the decode needs one.
 */

/** Downmix a set of channels to one by averaging, so a clip panned to one side does not favour it. */
export function monoFrom(channels: Float32Array[]): Float32Array {
  const frames = channels[0]?.length ?? 0;
  const mono = new Float32Array(frames);
  for (const channel of channels) {
    const count = Math.min(frames, channel.length);
    for (let i = 0; i < count; i++) mono[i] += channel[i];
  }
  if (channels.length > 1) {
    for (let i = 0; i < frames; i++) mono[i] /= channels.length;
  }
  return mono;
}

/** A decoded clip as a single mono channel. */
export function toMono(buffer: AudioBuffer): Float32Array {
  return monoFrom(
    Array.from({ length: buffer.numberOfChannels }, (_, channel) => buffer.getChannelData(channel)),
  );
}

/** A 16-bit PCM WAV of the given channels, so a plain `<audio>` element can play the result. */
export function encodeWav(channels: Float32Array[], sampleRate: number): ArrayBuffer {
  const count = channels.length;
  const frames = channels[0]?.length ?? 0;
  const bytes = 44 + frames * count * 2;
  const view = new DataView(new ArrayBuffer(bytes));
  const text = (offset: number, value: string): void => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };

  text(0, "RIFF");
  view.setUint32(4, bytes - 8, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true); // the fmt chunk is the 16-byte PCM one
  view.setUint16(20, 1, true); // format 1: uncompressed PCM
  view.setUint16(22, count, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * count * 2, true); // byte rate
  view.setUint16(32, count * 2, true); // block align
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, frames * count * 2, true);

  let offset = 44;
  for (let frame = 0; frame < frames; frame++) {
    for (let channel = 0; channel < count; channel++) {
      const sample = Math.max(-1, Math.min(1, channels[channel][frame] ?? 0));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
  }
  return view.buffer;
}

/**
 * Fetch two clips, downmix each to mono, and return an object URL for one stereo WAV with the first
 * on the left and the second on the right.
 *
 * An offline context does the decoding: it needs no user gesture and opens no output device, and it
 * resamples both clips to one rate so the two sides line up.
 */
export async function splitStereo(aUrl: string, bUrl: string): Promise<string> {
  const [aBytes, bBytes] = await Promise.all([readClip(aUrl), readClip(bUrl)]);
  const context = new OfflineAudioContext(1, 1, 44100);
  const [a, b] = await Promise.all([
    context.decodeAudioData(aBytes),
    context.decodeAudioData(bBytes),
  ]);
  const left = toMono(a);
  const right = toMono(b);
  // The two takes are the same length by construction; the shorter one wins if they ever are not,
  // because a side that runs on after the other ends would be silence pretending to be a difference.
  const frames = Math.min(left.length, right.length);
  const wav = encodeWav([left.subarray(0, frames), right.subarray(0, frames)], a.sampleRate);
  return URL.createObjectURL(new Blob([wav], { type: "audio/wav" }));
}

async function readClip(url: string): Promise<ArrayBuffer> {
  let response: Response;
  try {
    response = await fetch(url);
  } catch {
    throw new Error("could not read the clip; the renderer has to allow this page's origin");
  }
  if (!response.ok) throw new Error(`${response.status} ${response.statusText} reading a clip`);
  return response.arrayBuffer();
}
