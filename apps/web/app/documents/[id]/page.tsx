import { Suspense } from "react";

import { DetailSkeleton } from "@/components/Skeletons";

import { DocumentDetail } from "./document-detail";

export default function DocumentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return (
    <Suspense fallback={<DetailSkeleton />}>
      <DocumentLoader params={params} />
    </Suspense>
  );
}

async function DocumentLoader({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DocumentDetail id={id} />;
}
