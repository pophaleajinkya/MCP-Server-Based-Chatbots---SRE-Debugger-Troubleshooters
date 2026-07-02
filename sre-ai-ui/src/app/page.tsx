import { redirect } from "next/navigation";
import { MainLayout } from "@/components/MainLayout";
import { loadAgents } from "@/lib/agents";

interface HomeProps {
  searchParams: Promise<{ code?: string; state?: string; error?: string; error_description?: string; session?: string }>;
}

export default async function Home({ searchParams }: HomeProps) {
  const params = await searchParams;

  // PingFed redirects back to / with OAuth params — forward to the callback handler
  if (params.code && params.state) {
    const qs = new URLSearchParams({
      code: params.code,
      state: params.state,
    }).toString();
    redirect(`/api/auth/callback?${qs}`);
  }

  if (params.error) {
    const qs = new URLSearchParams({
      error: params.error,
      ...(params.error_description ? { error_description: params.error_description } : {}),
    }).toString();
    redirect(`/api/auth/callback?${qs}`);
  }

  const initialAgents = loadAgents();

  return (
    <main className="h-screen overflow-hidden">
      <MainLayout initialSessionId={params.session} initialAgents={initialAgents} />
    </main>
  );
}
