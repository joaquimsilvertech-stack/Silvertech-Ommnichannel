export const QR_IMAGE_ERROR_MESSAGE =
  "Não foi possível exibir este QR Code. Atualize e tente novamente.";

const MAX_QR_CODE_LENGTH = 262_144;
const DATA_URI_PATTERN = /^data:(image\/(?:png|jpeg|jpg|webp));base64,([A-Za-z0-9+/_-]+={0,2})$/i;
const RAW_BASE64_PATTERN = /^[A-Za-z0-9+/_-]+={0,2}$/;

type SupportedMime = "image/png" | "image/jpeg" | "image/webp";

function decodeBase64(value: string): Uint8Array {
  if (!RAW_BASE64_PATTERN.test(value)) throw new Error(QR_IMAGE_ERROR_MESSAGE);
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  let binary: string;
  try {
    binary = atob(padded);
  } catch {
    throw new Error(QR_IMAGE_ERROR_MESSAGE);
  }
  if (!binary.length) throw new Error(QR_IMAGE_ERROR_MESSAGE);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function startsWith(bytes: Uint8Array, signature: number[]) {
  return signature.every((value, index) => bytes[index] === value);
}

function detectImageMime(bytes: Uint8Array): SupportedMime {
  if (startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
    return "image/png";
  }
  if (startsWith(bytes, [0xff, 0xd8, 0xff])) return "image/jpeg";
  if (
    startsWith(bytes, [0x52, 0x49, 0x46, 0x46]) &&
    bytes[8] === 0x57 &&
    bytes[9] === 0x45 &&
    bytes[10] === 0x42 &&
    bytes[11] === 0x50
  ) {
    return "image/webp";
  }
  throw new Error(QR_IMAGE_ERROR_MESSAGE);
}

function normalizeDeclaredMime(value: string): SupportedMime {
  if (value.toLowerCase() === "image/png") return "image/png";
  if (["image/jpeg", "image/jpg"].includes(value.toLowerCase())) return "image/jpeg";
  if (value.toLowerCase() === "image/webp") return "image/webp";
  throw new Error(QR_IMAGE_ERROR_MESSAGE);
}

export function createQRCodeObjectURL(
  qrCode: string,
  format: "base64" | "data_uri"
): string {
  if (typeof qrCode !== "string" || !qrCode || qrCode.length > MAX_QR_CODE_LENGTH) {
    throw new Error(QR_IMAGE_ERROR_MESSAGE);
  }

  let encoded = qrCode;
  let declaredMime: SupportedMime | undefined;
  if (format === "data_uri") {
    const match = DATA_URI_PATTERN.exec(qrCode);
    if (!match) throw new Error(QR_IMAGE_ERROR_MESSAGE);
    declaredMime = normalizeDeclaredMime(match[1]);
    encoded = match[2];
  }

  const bytes = decodeBase64(encoded);
  const detectedMime = detectImageMime(bytes);
  if (declaredMime && declaredMime !== detectedMime) {
    throw new Error(QR_IMAGE_ERROR_MESSAGE);
  }
  const data = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  return URL.createObjectURL(new Blob([data], { type: detectedMime }));
}

export function revokeQRCodeObjectURL(objectUrl: string | null | undefined) {
  if (objectUrl) URL.revokeObjectURL(objectUrl);
}
