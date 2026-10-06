const kes = new Intl.NumberFormat("en-KE", { maximumFractionDigits: 0 });

/** Whole shillings, e.g. "KES 1,240". */
export function money(amount: number): string {
  return `KES ${kes.format(amount)}`;
}

export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** "08:00:00" -> "08:00" */
export function hhmm(t: string | null): string {
  return t ? t.slice(0, 5) : "";
}

const dateFmt = new Intl.DateTimeFormat("en-KE", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Africa/Nairobi",
});

export function when(iso: string | null): string {
  return iso ? dateFmt.format(new Date(iso)) : "No end";
}

/** <input type="datetime-local"> value in Nairobi time -> ISO string with offset. */
export function localToIso(value: string): string {
  return `${value}:00+03:00`;
}

export function isoToLocal(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(new Date(iso).getTime() + 3 * 3600_000);
  return d.toISOString().slice(0, 16);
}

/**
 * Shrink a photo on the phone before upload: long side 1600 px, JPEG 85 %.
 * The server re-encodes to WebP anyway; this just saves the hotel's mobile data.
 */
export async function compressImage(file: File): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.85));
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file;
  }
}
