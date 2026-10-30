import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-none text-[15px] font-action focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-border-focus)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        default:
          "border-[3px] border-black bg-[var(--color-accent)] text-[var(--color-text-on-accent)] shadow-[var(--shadow)] hover:bg-[var(--color-accent-hover)] active:translate-x-[4px] active:translate-y-[4px] active:shadow-none",
        destructive:
          "border-[3px] border-black bg-black text-white shadow-[var(--shadow)] hover:bg-[var(--color-error)] active:translate-x-[4px] active:translate-y-[4px] active:shadow-none",
        outline:
          "border-[3px] border-black bg-[var(--color-bg-primary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)] shadow-[var(--shadow)] active:translate-x-[4px] active:translate-y-[4px] active:shadow-none",
        secondary:
          "border-[3px] border-black bg-[var(--color-accent-light)] text-[var(--color-accent)] hover:bg-[var(--color-accent-light)]/80 shadow-[var(--shadow)] active:translate-x-[4px] active:translate-y-[4px] active:shadow-none",
        ghost:
          "hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]",
        link: "text-[var(--color-accent)] underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 rounded-none px-3 text-xs",
        lg: "h-12 rounded-none px-8 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
