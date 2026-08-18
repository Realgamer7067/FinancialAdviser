import { ButtonHTMLAttributes } from "react";

const VARIANTS = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-50",
  secondary: "border text-slate-700 hover:bg-slate-50 disabled:opacity-50",
};

export default function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof VARIANTS }) {
  return <button className={`rounded px-4 py-2 text-sm ${VARIANTS[variant]} ${className}`} {...props} />;
}
