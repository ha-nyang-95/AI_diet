import { notFound } from "next/navigation";

import { fetchLegalDocument } from "@/lib/legal-fetch";

export const metadata = {
  title: "Privacy Policy — BalanceNote",
};

export default async function PrivacyPageEn() {
  const doc = await fetchLegalDocument("privacy", "en");
  if (!doc) notFound();

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-2xl font-semibold tracking-tight mb-4">{doc.title}</h1>
      <article className="whitespace-pre-line text-sm leading-7 text-zinc-800">
        {doc.body}
      </article>
      <p className="mt-6 text-xs text-zinc-400">
        Last updated: {doc.updated_at.slice(0, 10)} · version {doc.version}
      </p>
    </main>
  );
}
