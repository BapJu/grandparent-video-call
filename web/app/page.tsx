import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import CallPanel from "./components/CallPanel";
import SignOutButton from "./components/SignOutButton";

export default async function Home() {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  // RLS: only allowlisted family members can read this table, so an empty
  // result means "not a family member".
  const { data: members } = await supabase
    .from("family_members")
    .select("id")
    .limit(1);

  const isMember = (members?.length ?? 0) > 0;

  if (!isMember) {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-6 p-6 text-center">
        <h1 className="text-2xl font-bold">Accès réservé à la famille</h1>
        <p className="max-w-sm text-slate-400">
          Le compte {user.email} n’est pas autorisé. Demande à Baptiste de
          l’ajouter.
        </p>
        <SignOutButton />
      </main>
    );
  }

  return <CallPanel userEmail={user.email!} />;
}
