import { useRef, useState, type FormEvent } from "react";
import { Plug } from "@phosphor-icons/react";
import { Button } from "../Button";
import { normalizeApiError } from "../../lib/apiErrors";
import type { WhatsAppChannel } from "../../lib/whatsappChannels";

const MAX_CHANNEL_NAME_LENGTH = 128;

type Props = {
  isSubmitting: boolean;
  onCancel: () => void;
  onSubmit: (input: { name: string }) => Promise<WhatsAppChannel>;
};

function normalizeWhatsAppChannelName(value: string) {
  return value.trim().replace(/\s+/g, " ");
}

function hasControlCharacters(value: string) {
  return Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint <= 31 || codePoint === 127;
  });
}

export function CreateWhatsAppChannelForm({ isSubmitting, onCancel, onSubmit }: Props) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string>();
  const submitLocked = useRef(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLocked.current || isSubmitting) return;

    const normalizedName = normalizeWhatsAppChannelName(name);
    if (!normalizedName) {
      setError("Informe um nome para a conexão.");
      return;
    }
    if (normalizedName.length > MAX_CHANNEL_NAME_LENGTH) {
      setError(`Use no máximo ${MAX_CHANNEL_NAME_LENGTH} caracteres.`);
      return;
    }
    if (hasControlCharacters(normalizedName)) {
      setError("O nome contém caracteres não permitidos.");
      return;
    }

    submitLocked.current = true;
    setError(undefined);
    try {
      await onSubmit({ name: normalizedName });
      setName("");
    } catch (requestError) {
      setError(normalizeApiError(requestError).message);
    } finally {
      submitLocked.current = false;
    }
  }

  return (
    <form
      className="border-y border-app-border bg-app-surface py-5"
      onSubmit={handleSubmit}
    >
      <div className="max-w-2xl">
        <h2 className="text-base font-semibold text-white">Nova conexão</h2>
        <p className="mt-1 text-sm leading-6 text-app-muted">
          Dê um nome que ajude sua equipe a reconhecer este WhatsApp.
        </p>

        <label className="mt-5 block text-sm font-medium text-app-text" htmlFor="whatsapp-channel-name">
          Nome da conexão
        </label>
        <input
          autoComplete="off"
          className="mt-2 h-11 w-full rounded-control border border-app-border bg-app-bg px-3 text-sm text-app-text outline-none transition placeholder:text-app-muted focus:border-app-primary focus:ring-4 focus:ring-app-primary/15 disabled:opacity-70"
          disabled={isSubmitting}
          id="whatsapp-channel-name"
          maxLength={MAX_CHANNEL_NAME_LENGTH}
          onChange={(event) => setName(event.target.value)}
          placeholder="WhatsApp principal"
          required
          value={name}
        />
        <p className="mt-2 text-xs text-app-muted">Até 128 caracteres.</p>

        {error ? (
          <p className="mt-3 rounded-control border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-100" role="alert">
            {error}
          </p>
        ) : null}

        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button className="w-full sm:w-auto" disabled={isSubmitting} onClick={onCancel} type="button" variant="ghost">
            Cancelar
          </Button>
          <Button className="w-full sm:w-auto" disabled={isSubmitting} icon={<Plug size={18} />} type="submit">
            {isSubmitting ? "Criando conexão..." : "Criar conexão"}
          </Button>
        </div>
      </div>
    </form>
  );
}
