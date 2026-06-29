import { Bell, MagnifyingGlass, Question } from "@phosphor-icons/react";
import { Button } from "./Button";

export function Topbar() {
  return (
    <header className="sticky top-0 z-20 flex min-h-[62px] items-center justify-between border-b border-app-border bg-app-bg/95 px-4 backdrop-blur lg:px-9">
      <div className="flex items-center gap-2 text-sm leading-[22px] text-app-muted">
        <span>Silvertech</span>
        <span>/</span>
        <span className="text-app-text">Omnichannel</span>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="ghost" aria-label="Buscar" icon={<MagnifyingGlass size={18} />} />
        <Button variant="ghost" aria-label="Notificações" icon={<Bell size={18} />} />
        <Button variant="ghost" aria-label="Suporte" icon={<Question size={18} />} />
      </div>
    </header>
  );
}
