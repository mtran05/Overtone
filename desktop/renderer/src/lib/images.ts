// Preset artwork is stored as a data URL in localStorage, which holds only a few
// megabytes in total. A full-size photo can fill that on its own, so imported
// images are scaled down to what the UI shows (64px at most) with headroom for
// high-DPI screens.
export const PRESET_IMAGE_SIZE = 192;

// The size that fits inside a max x max square without upscaling or changing the aspect ratio.
export function fitWithin(width: number, height: number, max: number): { width: number; height: number } {
  if (width <= 0 || height <= 0) return { width: 0, height: 0 };
  const scale = Math.min(1, max / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

// Re-encode an image data URL as a small WebP. Falls back to the original when
// the browser cannot decode it, or when shrinking would not make it smaller.
export async function shrinkImage(dataUrl: string, max = PRESET_IMAGE_SIZE): Promise<string> {
  const image = new Image();
  image.src = dataUrl;
  try {
    await image.decode();
  } catch {
    return dataUrl;
  }
  const size = fitWithin(image.naturalWidth, image.naturalHeight, max);
  if (!size.width) return dataUrl;
  const canvas = document.createElement("canvas");
  canvas.width = size.width;
  canvas.height = size.height;
  const context = canvas.getContext("2d");
  if (!context) return dataUrl;
  context.drawImage(image, 0, 0, size.width, size.height);
  const shrunk = canvas.toDataURL("image/webp", 0.85);
  return shrunk.length < dataUrl.length ? shrunk : dataUrl;
}
