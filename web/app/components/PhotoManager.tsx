"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

const BUCKET = "photos";
const CHANNEL = "visio-tv-calls";
const MAX_EDGE = 1920; // the Pi's screen is far smaller; this keeps 4G cheap
const JPEG_QUALITY = 0.82;

type Photo = { name: string; url: string };

/** iPhone photos are HEIC, which only Safari can decode natively. Convert them
 *  first so they work from any browser — the libheif/WASM bundle is imported
 *  lazily, so anyone uploading ordinary JPEGs never downloads it. */
async function toDecodable(file: File): Promise<Blob> {
  const { isHeic, heicTo } = await import("heic-to");
  if (!(await isHeic(file))) return file;
  return heicTo({ blob: file, type: "image/jpeg", quality: JPEG_QUALITY });
}

/** Downscale to a sane size before upload: a 4 MB phone photo becomes ~300 KB,
 *  which the Pi then downloads once over 4G. */
async function shrink(file: File): Promise<Blob> {
  const source = await toDecodable(file);
  const bitmap = await createImageBitmap(source);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvas indisponible");
  ctx.drawImage(bitmap, 0, 0, width, height);
  bitmap.close();

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY)
  );
  if (!blob) throw new Error("conversion impossible");
  return blob;
}

export default function PhotoManager() {
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const supabase = createClient();

  const load = useCallback(async () => {
    const { data, error } = await supabase.storage
      .from(BUCKET)
      .list("", { limit: 200, sortBy: { column: "created_at", order: "desc" } });

    if (error) {
      setError("Impossible de charger les photos.");
      setLoading(false);
      return;
    }

    const items = (data ?? []).filter((f) => f.name && !f.name.startsWith("."));
    const withUrls = await Promise.all(
      items.map(async (f) => {
        const { data: signed } = await supabase.storage
          .from(BUCKET)
          .createSignedUrl(f.name, 3600);
        return { name: f.name, url: signed?.signedUrl ?? "" };
      })
    );
    setPhotos(withUrls.filter((p) => p.url));
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    load();
  }, [load]);

  /** Tell the Pi to re-sync straight away instead of waiting for its next poll. */
  const notifyPi = useCallback(async () => {
    await supabase.realtime.setAuth();
    const channel = supabase.channel(CHANNEL, { config: { private: true } });
    await new Promise<void>((resolve) => {
      channel.subscribe((status) => {
        if (status === "SUBSCRIBED") resolve();
        else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") resolve();
      });
    });
    await channel.send({
      type: "broadcast",
      event: "photos_changed",
      payload: {},
    });
    await supabase.removeChannel(channel);
  }, [supabase]);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;

    setBusy(true);
    setError(null);
    let failed = 0;

    for (const [i, file] of files.entries()) {
      setProgress(`Envoi ${i + 1}/${files.length}…`);
      try {
        // HEIC conversion is the slow step, so say so rather than looking stuck.
        if (/\.hei[cf]$/i.test(file.name)) {
          setProgress(`Conversion ${i + 1}/${files.length}…`);
        }
        const blob = await shrink(file);
        const { error } = await supabase.storage
          .from(BUCKET)
          .upload(`${crypto.randomUUID()}.jpg`, blob, {
            contentType: "image/jpeg",
          });
        if (error) throw error;
      } catch {
        failed++;
      }
    }

    if (failed > 0) {
      setError(
        `${failed} photo(s) n'ont pas pu être envoyées. Vérifie qu'il s'agit bien d'images.`
      );
    }

    setProgress(null);
    setBusy(false);
    if (fileRef.current) fileRef.current.value = "";
    await load();
    await notifyPi();
  }

  async function onDelete(name: string) {
    setBusy(true);
    const { error } = await supabase.storage.from(BUCKET).remove([name]);
    if (error) setError("Suppression impossible.");
    setBusy(false);
    await load();
    await notifyPi();
  }

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col gap-5 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Photos de Mamie</h1>
        <Link
          href="/"
          className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 transition hover:bg-slate-900"
        >
          ← Appels
        </Link>
      </header>

      <p className="text-sm text-slate-400">
        Ces photos défilent sur l’écran de Mamie quand il n’y a pas d’appel.
      </p>

      <label className="cursor-pointer rounded-2xl bg-emerald-600 px-6 py-5 text-center text-lg font-semibold transition hover:bg-emerald-500 aria-disabled:opacity-50">
        {busy ? progress ?? "Envoi…" : "＋ Ajouter des photos"}
        <input
          ref={fileRef}
          type="file"
          accept="image/*,.heic,.heif"
          multiple
          disabled={busy}
          onChange={onUpload}
          className="hidden"
        />
      </label>

      {error && (
        <p className="rounded-lg bg-red-950 px-4 py-3 text-sm text-red-300">{error}</p>
      )}

      {loading ? (
        <p className="text-center text-slate-500">Chargement…</p>
      ) : photos.length === 0 ? (
        <p className="text-center text-slate-500">
          Aucune photo pour l’instant.
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {photos.map((p) => (
            <div key={p.name} className="group relative aspect-square">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={p.url}
                alt=""
                loading="lazy"
                className="h-full w-full rounded-lg object-cover"
              />
              <button
                onClick={() => onDelete(p.name)}
                disabled={busy}
                aria-label="Supprimer cette photo"
                className="absolute right-1.5 top-1.5 rounded-full bg-black/70 px-2.5 py-1 text-sm text-white transition hover:bg-red-600 disabled:opacity-50"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      <p className="pb-2 text-center text-xs text-slate-500">
        {photos.length} photo{photos.length > 1 ? "s" : ""}
      </p>
    </main>
  );
}
