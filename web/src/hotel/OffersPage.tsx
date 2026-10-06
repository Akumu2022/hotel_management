import { Camera, Plus } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";

import { Badge, Button, Card, EmptyState, ErrorNote, Field, Input, Select, Sheet, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { compressImage, isoToLocal, localToIso, when } from "../lib/format";
import type { Offer, Product, Upload } from "../lib/types";
import { keys, useIsAdmin, useOffers, useProducts, useSave } from "./hooks";

function OfferSheet({ offer, products, onClose }: { offer: Offer | null; products: Product[]; onClose: () => void }) {
  const [headline, setHeadline] = useState(offer?.title.split("\n")[0] ?? "");
  const [subline, setSubline] = useState(offer?.title.split("\n").slice(1).join(" ") ?? "");
  const title = subline.trim() ? `${headline.trim()}\n${subline.trim()}` : headline.trim();
  const [productId, setProductId] = useState(offer?.product_id ?? "");
  const [starts, setStarts] = useState(isoToLocal(offer?.starts_at ?? new Date().toISOString()));
  const [ends, setEnds] = useState(isoToLocal(offer?.ends_at ?? null));
  const [imageUrl, setImageUrl] = useState(offer?.image_url ?? null);
  const [imageKey, setImageKey] = useState<string | null | undefined>(undefined);
  const file = useRef<HTMLInputElement>(null);

  const upload = useSave(async (f: File) => {
    const blob = await compressImage(f);
    return api.upload<Upload>("/hotel/uploads/image", blob, "banner.jpg");
  }, []);
  const save = useSave(async () => {
    const body: Record<string, unknown> = {
      title: title.trim(),
      product_id: productId || null,
      starts_at: localToIso(starts),
      ends_at: ends ? localToIso(ends) : null,
    };
    if (imageKey !== undefined) body.image_key = imageKey;
    return offer ? api.patch(`/hotel/offers/${offer.id}`, body) : api.post("/hotel/offers", body);
  }, [keys.offers]);
  const remove = useSave(() => api.del(`/hotel/offers/${offer!.id}`), [keys.offers]);

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(undefined, { onSuccess: onClose });
  }

  return (
    <Sheet
      open
      title={offer ? "Edit offer" : "New offer"}
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          {offer ? (
            <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate(undefined, { onSuccess: onClose })}>
              Delete
            </Button>
          ) : null}
          <Button className="flex-1" type="submit" form="offer-form" busy={save.isPending}>
            Save
          </Button>
        </div>
      }
    >
      <form id="offer-form" onSubmit={submit} className="flex flex-col gap-4">
        <p className="text-sm text-muted">Offers appear as banners on the customer home screen: the headline in big letters, the highlight line in a yellow tag. Use a photo with the dish on the right.</p>
        <button
          type="button"
          onClick={() => file.current?.click()}
          className="relative flex aspect-[2/1] w-full items-center justify-center overflow-hidden rounded-card border border-line bg-page text-muted"
        >
          {imageUrl ? <img src={imageUrl} alt="" className="size-full object-contain" /> : (
            <span className="flex flex-col items-center gap-1 text-sm"><Camera className="size-6" />Banner photo</span>
          )}
          {upload.isPending ? <span className="absolute inset-0 flex items-center justify-center bg-surface/70">Uploading…</span> : null}
        </button>
        <input
          ref={file}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f)
              upload.mutate(f, {
                onSuccess: (u) => {
                  setImageKey(u.image_key);
                  setImageUrl(u.image_url);
                },
              });
            e.target.value = "";
          }}
        />
        <Field label="Headline" hint='e.g. "PIZZA WEDNESDAY"'>
          {(id) => <Input id={id} value={headline} onChange={(e) => setHeadline(e.target.value)} required minLength={2} maxLength={40} />}
        </Field>
        <Field label="Highlight line" hint='e.g. "Buy one Get One Free!"'>
          {(id) => <Input id={id} value={subline} onChange={(e) => setSubline(e.target.value)} maxLength={60} />}
        </Field>
        <Field label="Links to dish" hint="Optional">
          {(id) => (
            <Select id={id} value={productId} onChange={(e) => setProductId(e.target.value)}>
              <option value="">No dish</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </Select>
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Starts">{(id) => <Input id={id} type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} required />}</Field>
          <Field label="Ends" hint="Optional">{(id) => <Input id={id} type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} />}</Field>
        </div>
        <ErrorNote error={save.error ?? upload.error ?? remove.error} />
      </form>
    </Sheet>
  );
}

export function OffersPage() {
  const isAdmin = useIsAdmin();
  const offers = useOffers();
  const products = useProducts();
  const [editing, setEditing] = useState<Offer | "new" | null>(null);

  if (offers.isLoading) return <Skeleton className="h-40" />;
  if (offers.error) return <ErrorNote error={offers.error} />;
  const list = offers.data!;
  const now = Date.now();

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-muted">Banners and deals shown on the customer home screen.</p>
        {isAdmin ? (
          <Button onClick={() => setEditing("new")}>
            <Plus className="size-4" /> Offer
          </Button>
        ) : null}
      </div>
      {list.length === 0 ? (
        <EmptyState
          title="No offers yet"
          body="Banners and deals of the day show on the customer home screen."
          action={isAdmin ? <Button onClick={() => setEditing("new")}>Create an offer</Button> : null}
        />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {list.map((o) => {
            const live = new Date(o.starts_at).getTime() <= now && (!o.ends_at || new Date(o.ends_at).getTime() > now);
            return (
              <Card key={o.id} className="overflow-hidden">
                <div className="aspect-[2/1] bg-page">
                  {o.image_url ? <img src={o.image_url} alt="" loading="lazy" className="size-full object-contain" /> : null}
                </div>
                <div className="flex items-start justify-between gap-2 p-3">
                  <div>
                    <p className="font-semibold whitespace-pre-line">{o.title}</p>
                    <p className="text-sm text-muted">{when(o.starts_at)} → {when(o.ends_at)}</p>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <Badge tone={live ? "ok" : "neutral"}>{live ? "Live" : "Not live"}</Badge>
                    {isAdmin ? <Button variant="ghost" size="sm" onClick={() => setEditing(o)}>Edit</Button> : null}
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
      {editing ? (
        <OfferSheet offer={editing === "new" ? null : editing} products={products.data ?? []} onClose={() => setEditing(null)} />
      ) : null}
    </div>
  );
}
