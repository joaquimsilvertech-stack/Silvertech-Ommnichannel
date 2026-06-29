import { Icon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { ResourceTable } from "../components/ResourceTable";

type ResourcePageProps<T extends { id: string | number }> = {
  title: string;
  description: string;
  endpoint: string;
  icon: Icon;
  queryKey: string;
  queryFn: () => Promise<T[]>;
  columns: Array<{
    header: string;
    render: (item: T) => string | number | boolean | null | undefined;
  }>;
};

export function ResourcePage<T extends { id: string | number }>({
  title,
  description,
  endpoint,
  icon: IconComponent,
  queryKey,
  queryFn,
  columns
}: ResourcePageProps<T>) {
  const query = useQuery({
    queryKey: [queryKey],
    queryFn
  });

  return (
    <section className="rounded-card border border-app-border bg-app-surface p-6 shadow-soft">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex gap-4">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-app-infoBg text-app-secondary">
            <IconComponent size={24} weight="bold" />
          </span>
          <div>
            <h1 className="text-[30px] font-semibold leading-[38px] text-app-text">{title}</h1>
            <p className="mt-2 max-w-3xl text-sm leading-[22px] text-app-muted">{description}</p>
          </div>
        </div>
        <span className="rounded-pill bg-app-menu px-4 py-2 text-sm text-app-muted">{endpoint}</span>
      </div>

      {query.isLoading ? (
        <div className="rounded-card border border-app-border bg-app-bg p-6 text-sm text-app-muted">Carregando dados da API...</div>
      ) : query.isError ? (
        <div className="rounded-card border border-[#9C2F27] bg-[#401923] p-6 text-sm text-[#ffb3b3]">
          Não foi possível carregar este endpoint. Verifique se você está autenticado e se o Django está em `127.0.0.1:8000`.
        </div>
      ) : (
        <ResourceTable columns={columns} emptyText="A API respondeu sem registros para este recurso." items={query.data ?? []} />
      )}
    </section>
  );
}
