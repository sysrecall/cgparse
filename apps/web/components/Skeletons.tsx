export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="card overflow-hidden">
      <div className="border-b border-line bg-surface-alt px-5 py-3">
        <div className="skeleton h-4 w-40" />
      </div>
      <div className="divide-y divide-line">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-5 py-4">
            <div className="skeleton h-4 flex-1" />
            <div className="skeleton h-5 w-24" />
            <div className="skeleton h-4 w-16" />
            <div className="skeleton h-4 w-28" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="container-page grid gap-6 py-10 lg:grid-cols-[1.35fr_1fr]">
      <div className="space-y-6">
        <div className="card space-y-4 p-6">
          <div className="skeleton h-5 w-32" />
          <div className="grid gap-4 sm:grid-cols-2">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <div className="skeleton h-3 w-24" />
                <div className="skeleton h-9 w-full" />
              </div>
            ))}
          </div>
        </div>
        <div className="card space-y-3 p-6">
          <div className="skeleton h-5 w-28" />
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="skeleton h-10 w-full" />
          ))}
        </div>
      </div>
      <div className="space-y-6">
        <div className="card space-y-3 p-6">
          <div className="skeleton h-5 w-36" />
          <div className="skeleton h-20 w-full" />
        </div>
        <div className="card space-y-3 p-6">
          <div className="skeleton h-5 w-28" />
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton h-4 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}
