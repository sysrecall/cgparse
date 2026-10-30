"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useState } from "react";

const LINKS = [
  { href: "/", label: "Overview" },
  { href: "/documents", label: "Documents" },
  { href: "/review", label: "Review" },
  { href: "/search", label: "Search" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Pure link list. `pathname` is null in the prerender fallback, so the static
 * shell renders the same markup without an active state; the real value streams
 * in from <ActiveLinks/> at runtime.
 */
function LinkList({
  pathname,
  variant,
  onNavigate,
}: {
  pathname: string | null;
  variant: "desktop" | "mobile";
  onNavigate?: () => void;
}) {
  return (
    <>
      {LINKS.map((link) => {
        const active = pathname !== null && isActive(pathname, link.href);
        if (variant === "mobile") {
          return (
            <Link
              key={link.href}
              href={link.href}
              onClick={onNavigate}
              className={`rounded-md px-3 py-3 text-[15px] font-medium ${
                active ? "bg-primary-soft text-primary" : "text-heading"
              }`}
            >
              {link.label}
            </Link>
          );
        }
        return (
          <Link
            key={link.href}
            href={link.href}
            className={`relative rounded-md px-3.5 py-2 text-[15px] font-medium transition-colors ${
              active ? "text-primary" : "text-heading hover:text-primary"
            }`}
          >
            {link.label}
            {active ? (
              <span className="absolute inset-x-3.5 -bottom-px h-0.5 rounded-full bg-primary" />
            ) : null}
          </Link>
        );
      })}
    </>
  );
}

function ActiveLinks({
  variant,
  onNavigate,
}: {
  variant: "desktop" | "mobile";
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  return (
    <LinkList pathname={pathname} variant={variant} onNavigate={onNavigate} />
  );
}

export function Nav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-line bg-surface/95 backdrop-blur">
      <div className="container-page flex h-[74px] items-center justify-between gap-6">
        <Link
          href="/"
          className="flex items-center gap-2.5"
          onClick={() => setOpen(false)}
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-white">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <path d="M14 2v6h6" />
              <path d="M8 13h8M8 17h5" />
            </svg>
          </span>
          <span className="leading-tight">
            <span className="block font-heading text-[19px] font-bold text-heading">
              CareGuide
              <span className="text-primary">.</span>
            </span>
            <span className="block text-[10px] font-medium uppercase tracking-[0.16em] text-muted">
              Document Intelligence
            </span>
          </span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex" aria-label="Main">
          <Suspense fallback={<LinkList pathname={null} variant="desktop" />}>
            <ActiveLinks variant="desktop" />
          </Suspense>
        </nav>

        <div className="hidden md:block">
          <Link href="/#upload" className="btn-primary !px-5 !py-2.5 !text-[15px]">
            Upload
          </Link>
        </div>

        <button
          type="button"
          className="flex h-11 w-11 items-center justify-center rounded-md border border-line text-heading md:hidden"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            {open ? (
              <path d="M6 6l12 12M18 6L6 18" />
            ) : (
              <path d="M4 7h16M4 12h16M4 17h16" />
            )}
          </svg>
        </button>
      </div>

      {open ? (
        <div className="border-t border-line bg-surface md:hidden">
          <nav className="container-page flex flex-col py-3" aria-label="Mobile">
            <Suspense
              fallback={
                <LinkList
                  pathname={null}
                  variant="mobile"
                  onNavigate={() => setOpen(false)}
                />
              }
            >
              <ActiveLinks
                variant="mobile"
                onNavigate={() => setOpen(false)}
              />
            </Suspense>
            <Link
              href="/#upload"
              onClick={() => setOpen(false)}
              className="btn-primary mt-3"
            >
              Upload documents
            </Link>
          </nav>
        </div>
      ) : null}
    </header>
  );
}
