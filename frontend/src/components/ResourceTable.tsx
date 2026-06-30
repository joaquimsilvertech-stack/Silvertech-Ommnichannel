type ResourceTableProps<T extends { id: string | number }> = {
  columns: Array<{
    header: string;
    render: (item: T) => string | number | boolean | null | undefined;
  }>;
  emptyText: string;
  items: T[];
};

export function ResourceTable<T extends { id: string | number }>({ columns, emptyText, items }: ResourceTableProps<T>) {
  if (!items.length) {
    return (
      <div className="flex min-h-[260px] items-center justify-center rounded-card border border-dashed border-app-border bg-app-bg px-6 text-center">
        <p className="max-w-md text-sm leading-[22px] text-app-muted">{emptyText}</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-card border border-app-border">
      <table className="w-full min-w-[680px] border-collapse text-left text-sm">
        <thead className="bg-app-menu text-white">
          <tr>
            {columns.map((column) => (
              <th className="px-4 py-3 font-semibold" key={column.header}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr className="border-t border-app-border hover:bg-app-hover" key={item.id}>
              {columns.map((column) => (
                <td className="px-4 py-3 text-app-text" key={column.header}>
                  {String(column.render(item) ?? "-")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
