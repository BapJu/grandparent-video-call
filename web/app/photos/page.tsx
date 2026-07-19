import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import PhotoManager from "../components/PhotoManager";

export default async function PhotosPage() {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) redirect("/login");

  // Same RLS gate as the call page: an empty result means "not family".
  const { data: members } = await supabase
    .from("family_members")
    .select("id")
    .limit(1);

  if ((members?.length ?? 0) === 0) redirect("/");

  return <PhotoManager />;
}
