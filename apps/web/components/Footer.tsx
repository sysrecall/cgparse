import Link from "next/link";

const COLUMNS = [
  {
    title: "Product",
    links: [
      { href: "/", label: "Overview" },
      { href: "/documents", label: "Documents" },
      { href: "/review", label: "Review queue" },
      { href: "/search", label: "Search" },
    ],
  },
  {
    title: "Pipeline",
    links: [
      { href: "/documents", label: "Ingestion" },
      { href: "/documents", label: "Extraction" },
      { href: "/review", label: "Validation" },
      { href: "/search", label: "Indexing" },
    ],
  },
  {
    title: "Formats",
    links: [
      { href: "/#upload", label: "PDF" },
      { href: "/#upload", label: "JPG / PNG" },
      { href: "/#upload", label: "XLSX / XLS" },
      { href: "/#upload", label: "CSV" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="mt-auto bg-ink text-white">
      <div className="container-page grid gap-10 py-16 md:grid-cols-[1.6fr_1fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2.5">
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
            <span className="font-heading text-[19px] font-bold text-white">
              CareGuide<span className="text-primary">.</span>
            </span>
          </div>
          <p className="mt-5 max-w-sm text-[15px] leading-relaxed text-white/65">
            AI-powered ingestion, extraction, validation and search for financial
            documents — built for human review, not blind automation.
          </p>
          <p className="mt-5 text-[13px] text-white/45">
            No invented data. Uncertain values stay empty and land in the review
            queue.
          </p>
        </div>

        {COLUMNS.map((column) => (
          <div key={column.title}>
            <h6 className="text-[13px] uppercase tracking-[0.12em] text-white/80">
              {column.title}
            </h6>
            <ul className="mt-4 space-y-2.5">
              {column.links.map((link) => (
                <li key={link.label}>
                  <Link
                    href={link.href}
                    className="text-[15px] text-white/60 transition-colors hover:text-primary"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="border-t border-white/10">
        <div className="container-page flex flex-col items-center justify-between gap-3 py-5 text-[13px] text-white/45 sm:flex-row">
          <p>© 2026 CareGuide all rights reserved.</p>
          <p className="flex items-center gap-2">
            <span className="inline-block h-2 w-2 rounded-full bg-success" />
            Keyword and hybrid semantic search live
          </p>
        </div>
      </div>
    </footer>
  );
}
