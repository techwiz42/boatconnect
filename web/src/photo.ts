// Getting a picture ready to upload: the browser scales it down and re-encodes it as a JPEG first, so a 12-megapixel phone photo is a few hundred kilobytes on the way. The server
// checks and re-encodes it again (and removes the camera's location data); this step is for the size of the upload and the person's patience.

export const PHOTO_MAX_SIDE = 1200;
export const PHOTO_MAX_BYTES = 800_000; // the server takes up to 900 000 and the web server in front 1 MB

/** The size a picture of `width` x `height` is scaled to so its longest side is at most `max` (never enlarged), keeping its shape. */
export function fitWithin(width: number, height: number, max: number): { width: number; height: number } {
  const scale = Math.min(1, max / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

export class PictureError extends Error {}

export async function toUploadJpeg(file: File): Promise<Blob> {
  if (!/^image\//.test(file.type)) throw new PictureError("choose a picture file (JPEG, PNG or WebP)");
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file); // applies the photo's own rotation
  } catch {
    throw new PictureError("this browser could not read that picture; try a JPEG or PNG");
  }
  const { width, height } = fitWithin(bitmap.width, bitmap.height, PHOTO_MAX_SIDE);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) throw new PictureError("this browser cannot prepare the picture");
  context.fillStyle = "#ffffff"; // transparent parts of a PNG become white, as they will on the server
  context.fillRect(0, 0, width, height);
  context.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();
  for (const quality of [0.85, 0.75, 0.65, 0.5]) {
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
    if (blob && blob.size <= PHOTO_MAX_BYTES) return blob;
  }
  throw new PictureError("that picture is still too large after shrinking it; choose a smaller one");
}
