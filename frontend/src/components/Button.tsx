import type { ButtonHTMLAttributes, ReactNode } from "react";
import { clsx } from "clsx";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon?: ReactNode;
  variant?: "primary" | "ghost" | "surface";
};

export function Button({ children, icon, className, variant = "primary", ...props }: ButtonProps) {
  return (
    <button
      className={clsx(
        "inline-flex min-h-10 items-center justify-center gap-2 rounded-pill px-4 py-2 text-sm font-medium transition focus:outline-none focus:ring-4 focus:ring-app-primary/20 disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "border border-app-primary bg-app-primary text-white hover:bg-app-secondary hover:border-app-secondary",
        variant === "ghost" && "border border-transparent bg-transparent text-app-text hover:bg-app-hover hover:text-white",
        variant === "surface" && "border border-app-border bg-app-surface text-app-text hover:bg-app-hover",
        className
      )}
      {...props}
    >
      {icon}
      {children}
    </button>
  );
}
