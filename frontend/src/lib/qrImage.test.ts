import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createQRCodeObjectURL,
  QR_IMAGE_ERROR_MESSAGE,
  revokeQRCodeObjectURL
} from "./qrImage";

const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00];
const JPEG = [0xff, 0xd8, 0xff, 0xe0, 0x00];
const WEBP = [0x52, 0x49, 0x46, 0x46, 0x00, 0x00, 0x00, 0x00, 0x57, 0x45, 0x42, 0x50];

function base64(bytes: number[]) {
  return btoa(String.fromCharCode(...bytes));
}

describe("createQRCodeObjectURL", () => {
  const createObjectURL = vi.fn((blob: Blob) => {
    void blob;
    return "blob:qr-image";
  });
  const revokeObjectURL = vi.fn((objectUrl: string) => {
    void objectUrl;
  });

  beforeEach(() => {
    vi.stubGlobal("URL", {
      createObjectURL,
      revokeObjectURL
    });
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it.each([
    ["image/png", PNG],
    ["image/jpeg", JPEG],
    ["image/jpg", JPEG],
    ["image/webp", WEBP]
  ])("aceita data URI segura %s", (mime, bytes) => {
    expect(createQRCodeObjectURL(`data:${mime};base64,${base64(bytes)}`, "data_uri")).toBe("blob:qr-image");
    expect(createObjectURL).toHaveBeenCalledOnce();
  });

  it.each([
    [PNG, "image/png"],
    [JPEG, "image/jpeg"],
    [WEBP, "image/webp"]
  ])("detecta magic bytes em base64 bruto", (bytes, mime) => {
    createQRCodeObjectURL(base64(bytes), "base64");
    const blob = createObjectURL.mock.calls[0]?.[0];
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe(mime);
  });

  it.each([
    "data:image/svg+xml;base64,PHN2Zz4=",
    "data:text/html;base64,PGh0bWw+",
    "data:application/octet-stream;base64,AAAA",
    "data:image/png,not-base64"
  ])("rejeita data URI insegura", (value) => {
    expect(() => createQRCodeObjectURL(value, "data_uri")).toThrow(QR_IMAGE_ERROR_MESSAGE);
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("rejeita MIME que nao corresponde aos magic bytes", () => {
    expect(() => createQRCodeObjectURL(`data:image/png;base64,${base64(JPEG)}`, "data_uri"))
      .toThrow(QR_IMAGE_ERROR_MESSAGE);
  });

  it.each(["%%%%", base64([0x01, 0x02, 0x03, 0x04]), ""])(
    "rejeita base64 invalido ou formato desconhecido",
    (value) => {
      expect(() => createQRCodeObjectURL(value, "base64")).toThrow(QR_IMAGE_ERROR_MESSAGE);
    }
  );

  it("rejeita QR acima do limite", () => {
    const oversized = "A".repeat(262_145);
    expect(() => createQRCodeObjectURL(oversized, "base64")).toThrow(QR_IMAGE_ERROR_MESSAGE);
  });

  it("nao inclui o QR na mensagem de erro", () => {
    const secret = "private-qr-sentinel";
    try {
      createQRCodeObjectURL(secret, "base64");
    } catch (error) {
      expect(String(error)).not.toContain(secret);
      expect(String(error)).toContain(QR_IMAGE_ERROR_MESSAGE);
    }
  });

  it("revoga Blob URL explicitamente", () => {
    revokeQRCodeObjectURL("blob:qr-image");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:qr-image");
  });

  it("nao grava QR em localStorage ou sessionStorage", () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    createQRCodeObjectURL(base64(PNG), "base64");
    expect(local).not.toHaveBeenCalled();
  });
});
