import {
  AddressBook,
  ChartLineUp,
  ChatCircleText,
  GearSix,
  Kanban,
  Robot,
  UsersThree
} from "@phosphor-icons/react";
import { clsx } from "clsx";
import { NavLink } from "react-router-dom";

const items = [
  { label: "Dashboard", icon: ChartLineUp, to: "/" },
  { label: "Conversas", icon: ChatCircleText, to: "/conversations" },
  { label: "Contatos", icon: AddressBook, to: "/contacts" },
  { label: "Leads", icon: Kanban, to: "/leads" },
  { label: "Organizações", icon: Robot, to: "/organizations" },
  { label: "Workspaces", icon: UsersThree, to: "/workspaces" },
  { label: "Membros", icon: GearSix, to: "/members" },
  { label: "Convites", icon: GearSix, to: "/invites" }
];

export function Sidebar() {
  return (
    <aside className="hidden min-h-screen w-[280px] shrink-0 border-r border-app-border bg-app-bg p-2 lg:flex lg:flex-col">
      <NavLink className="mb-8 flex h-16 items-center px-4 text-lg font-semibold text-white" to="/">
        Silvertech
      </NavLink>
      <nav className="flex flex-1 flex-col gap-1">
        {items.map(({ label, icon: Icon, to }) =>
          to === "/conversations" ? (
            <a
              className={clsx(
                "flex h-10 items-center gap-2 rounded-control px-4 text-base leading-6 text-white transition",
                window.location.pathname === to ? "bg-app-menu" : "hover:bg-app-hover"
              )}
              href={to}
              key={label}
            >
              <Icon size={18} />
              <span>{label}</span>
            </a>
          ) : (
            <NavLink
              key={label}
              to={to}
              className={({ isActive }) =>
                clsx(
                  "flex h-10 items-center gap-2 rounded-control px-4 text-base leading-6 text-white transition",
                  isActive ? "bg-app-menu" : "hover:bg-app-hover"
                )
              }
            >
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          )
        )}
      </nav>
      <div className="rounded-control px-4 py-3 text-sm text-app-muted">
        <span className="block text-white">CRM Omnichannel</span>
        Rotas DRF + UI React
      </div>
    </aside>
  );
}
