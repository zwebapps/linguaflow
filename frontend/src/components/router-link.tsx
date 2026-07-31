"use client";

import NextLink from "next/link";
import type { ComponentProps, ReactNode } from "react";

type LinkProps = {
  to: string;
  children: ReactNode;
  className?: string;
  search?: Record<string, string | undefined>;
  params?: Record<string, string>;
  activeProps?: { className?: string };
  activeOptions?: { exact?: boolean };
} & Omit<ComponentProps<typeof NextLink>, "href">;

function hrefFromTo(to: string, params?: Record<string, string>, search?: Record<string, string | undefined>) {
  let path = to;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      path = path.replace(`$${k}`, v).replace(`:${k}`, v);
    }
  }
  if (search) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(search)) {
      if (v !== undefined) q.set(k, v);
    }
    const qs = q.toString();
    if (qs) path += `?${qs}`;
  }
  return path;
}

/** Drop-in for TanStack `<Link to=…>` in the Next app. */
export function Link({ to, children, className, search, params, ...rest }: LinkProps) {
  const href = hrefFromTo(to, params, search);
  return (
    <NextLink href={href} className={className} {...rest}>
      {children}
    </NextLink>
  );
}

export { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
