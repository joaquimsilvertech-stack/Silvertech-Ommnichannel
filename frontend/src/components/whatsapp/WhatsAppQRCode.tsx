import { ArrowClockwise, QrCode } from "@phosphor-icons/react";
import { Button } from "../Button";

type Props = {
  objectUrl: string | null;
  loading: boolean;
  error?: string;
  onRefresh: () => void;
};

export function WhatsAppQRCode({ objectUrl, loading, error, onRefresh }: Props) {
  return (
    <div className="flex w-full flex-col items-center">
      <div className="flex aspect-square w-full max-w-[320px] items-center justify-center overflow-hidden rounded-control bg-white p-4">
        {objectUrl ? (
          <img
            alt="QR Code para conectar o WhatsApp"
            className="h-full w-full object-contain"
            draggable={false}
            src={objectUrl}
          />
        ) : (
          <div className="flex flex-col items-center gap-3 text-center text-slate-600" aria-live="polite">
            <QrCode size={54} />
            <p className="max-w-[220px] text-sm">
              {loading ? "Buscando um QR Code seguro..." : "O QR Code ainda não está disponível."}
            </p>
          </div>
        )}
      </div>

      {error ? (
        <p className="mt-3 w-full max-w-[320px] rounded-control border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100" role="alert">
          {error}
        </p>
      ) : null}

      <Button
        className="mt-4 w-full max-w-[320px]"
        disabled={loading}
        icon={<ArrowClockwise className={loading ? "animate-spin" : ""} size={18} />}
        onClick={onRefresh}
        type="button"
        variant="surface"
      >
        {loading ? "Atualizando..." : "Atualizar QR Code"}
      </Button>
    </div>
  );
}
