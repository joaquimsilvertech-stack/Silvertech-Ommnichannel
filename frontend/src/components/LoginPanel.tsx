import { FormEvent, useState } from "react";
import { SignIn } from "@phosphor-icons/react";
import { login } from "../lib/api";
import { Button } from "./Button";

type LoginPanelProps = {
  onLoggedIn: () => void;
};

export function LoginPanel({ onLoggedIn }: LoginPanelProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      onLoggedIn();
    } catch {
      setError("Não foi possível autenticar com a API Django.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="rounded-card border border-app-border bg-app-surface p-6 shadow-soft">
      <div className="mb-6">
        <h2 className="text-base font-semibold leading-6 text-white">Conectar ao back-end</h2>
        <p className="mt-1 text-sm leading-[22px] text-app-muted">
          Use suas credenciais do Django para carregar dados reais do CRM.
        </p>
      </div>
      <form className="space-y-4" onSubmit={handleSubmit}>
        <label className="block text-sm leading-[22px] text-app-muted">
          Usuário ou e-mail
          <input
            className="mt-2 h-10 w-full rounded-control border border-app-border bg-app-bg px-3 text-sm text-app-text outline-none focus:border-app-secondary focus:ring-4 focus:ring-app-primary/20"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="username"
          />
        </label>
        <label className="block text-sm leading-[22px] text-app-muted">
          Senha
          <input
            className="mt-2 h-10 w-full rounded-control border border-app-border bg-app-bg px-3 text-sm text-app-text outline-none focus:border-app-secondary focus:ring-4 focus:ring-app-primary/20"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            autoComplete="current-password"
          />
        </label>
        {error ? <p className="rounded-card border border-[#9C2F27] bg-[#401923] px-4 py-3 text-sm text-[#ffb3b3]">{error}</p> : null}
        <Button className="w-full" disabled={loading} icon={<SignIn size={18} />}>
          {loading ? "Entrando..." : "Entrar"}
        </Button>
      </form>
    </section>
  );
}
