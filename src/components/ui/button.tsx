import * as React from "react";
import { cn } from "@/lib/utils";

// Base button styling for Neo‑Brutalism
const buttonBase = "inline-flex items-center justify-center gap-2 whitespace-nowrap border-4 border-black bg-white text-black font-bold text-sm uppercase tracking-wide transition-all duration-100 active:translate-x-2 active:translate-y-2 hover:shadow-[var(--shadow-sm)]";

// Variant specific classes
const variantClasses = {
  default: "bg-[var(--color-primary)] text-white",
  secondary: "bg-[var(--color-secondary)] text-black",
  outline: "bg-white border-4 border-black text-black",
  destructive: "bg-red-600 text-white",
  ghost: "bg-white text-black hover:bg-[var(--color-primary)] hover:text-white",
};

type Variant = keyof typeof variantClasses;

type Size = "default" | "sm" | "lg" | "icon";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", asChild = false, ...props }, ref) => {
    const sizeClasses = {
      default: "h-12 px-4 py-2",
      sm: "h-8 px-3 text-xs",
      lg: "h-14 px-6 text-base",
      icon: "h-12 w-12",
    }[size];
    const Component = asChild ? "span" : "button";
    return (
      <Component
        className={cn(buttonBase, variantClasses[variant], sizeClasses, className)}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };