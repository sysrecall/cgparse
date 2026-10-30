import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="border-b border-line bg-surface-alt">
      <div className="container-page flex flex-col gap-5 py-10 md:flex-row md:items-end md:justify-between">
        <div className="max-w-2xl">
          {eyebrow ? <p className="eyebrow mb-2">{eyebrow}</p> : null}
          <h1 className="text-[32px] md:text-[40px]">{title}</h1>
          {description ? (
            <p className="mt-3 text-[16px] leading-relaxed text-body">
              {description}
            </p>
          ) : null}
          {children}
        </div>
        {actions ? (
          <div className="flex flex-wrap items-center gap-3">{actions}</div>
        ) : null}
      </div>
    </div>
  );
}
