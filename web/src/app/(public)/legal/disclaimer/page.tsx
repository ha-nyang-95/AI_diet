import { notFound } from "next/navigation";

import DisclaimerFooter from "@/features/legal/DisclaimerFooter";
import { fetchLegalDocument } from "@/lib/legal-fetch";

export const metadata = {
  title: "면책 조항 — BalanceNote",
};

export default async function DisclaimerPage() {
  const doc = await fetchLegalDocument("disclaimer", "ko");
  if (!doc) notFound();

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold tracking-tight mb-4">{doc.title}</h1>
      <article className="whitespace-pre-line text-sm leading-7 text-zinc-800">
        {doc.body}
      </article>
      <p className="mt-6 text-xs text-zinc-400">
        최근 갱신일: {doc.updated_at.slice(0, 10)} · 버전 {doc.version}
      </p>
      <DisclaimerFooter />
    </main>
  );
}
