import { Camera, Trash2 } from "lucide-react";
import { type FormEvent, useRef, useState } from "react";

import { Badge, Button, ErrorNote, Field, Input, MoneyInput, Select, Sheet, Textarea } from "../components/ui";
import { api } from "../lib/api";
import { compressImage, money } from "../lib/format";
import type { Category, Product, Upload } from "../lib/types";
import { keys, useProducts, useSave } from "./hooks";

function PhotoPicker({
  url,
  onUploaded,
  onRemove,
}: {
  url: string | null;
  onUploaded: (u: Upload) => void;
  onRemove: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const upload = useSave(async (file: File) => {
    const blob = await compressImage(file);
    return api.upload<Upload>("/hotel/uploads/image", blob, file.name.replace(/\.\w+$/, ".jpg"));
  }, []);

  return (
    <div className="flex flex-col gap-2">
      <div className="relative aspect-[4/3] w-full overflow-hidden rounded-card border border-line bg-page">
        {url ? (
          <img src={url} alt="Dish" className="size-full object-cover" />
        ) : (
          <button
            type="button"
            onClick={() => input.current?.click()}
            className="flex size-full flex-col items-center justify-center gap-2 text-muted"
          >
            <Camera className="size-8" />
            <span className="text-sm font-medium">Add a photo</span>
            <span className="text-xs">Daylight, close up, plate filling the frame</span>
          </button>
        )}
        {upload.isPending ? (
          <div className="absolute inset-0 flex items-center justify-center bg-surface/70 text-sm font-medium">Uploading…</div>
        ) : null}
      </div>
      <input
        ref={input}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) upload.mutate(file, { onSuccess: onUploaded });
          e.target.value = "";
        }}
      />
      {url ? (
        <div className="flex gap-2">
          <Button type="button" variant="secondary" size="sm" onClick={() => input.current?.click()}>
            <Camera className="size-4" /> Change photo
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
            Remove
          </Button>
        </div>
      ) : null}
      <ErrorNote error={upload.error} />
    </div>
  );
}

function OptionsEditor({ product }: { product: Product }) {
  const [group, setGroup] = useState(product.options.at(-1)?.group_name ?? "Extras");
  const [name, setName] = useState("");
  const [price, setPrice] = useState<number | "">("");

  const add = useSave(
    () =>
      api.post(`/hotel/products/${product.id}/options`, {
        group_name: group.trim(),
        name: name.trim(),
        price_delta: price === "" ? 0 : price,
      }),
    [keys.products],
  );
  const archive = useSave(
    ({ id, is_archived }: { id: string; is_archived: boolean }) =>
      api.patch(`/hotel/products/${product.id}/options/${id}`, { is_archived }),
    [keys.products],
  );

  const groups = [...new Set(product.options.map((o) => o.group_name))];

  return (
    <section className="flex flex-col gap-3">
      <div>
        <h3 className="font-semibold">Options and extras</h3>
        <p className="text-sm text-muted">e.g. Size: Large +KES 100, Extras: Kachumbari +KES 30</p>
      </div>
      {groups.map((g) => (
        <div key={g} className="rounded-lg border border-line">
          <p className="border-b border-line px-3 py-2 text-sm font-semibold">{g}</p>
          <ul className="divide-y divide-line">
            {product.options
              .filter((o) => o.group_name === g)
              .map((o) => (
                <li key={o.id} className="flex items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span className={o.is_archived ? "text-muted line-through" : ""}>
                    {o.name} <span className="money text-muted">+{money(o.price_delta)}</span>
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => archive.mutate({ id: o.id, is_archived: !o.is_archived })}
                  >
                    {o.is_archived ? "Restore" : <Trash2 className="size-4" aria-label="Remove option" />}
                  </Button>
                </li>
              ))}
          </ul>
        </div>
      ))}
      <div className="grid grid-cols-2 gap-2 rounded-lg bg-page p-3">
        <Input aria-label="Group" placeholder="Group (e.g. Extras)" value={group} onChange={(e) => setGroup(e.target.value)} list="option-groups" />
        <datalist id="option-groups">
          {groups.map((g) => (
            <option key={g} value={g} />
          ))}
        </datalist>
        <Input aria-label="Option name" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <MoneyInput aria-label="Extra price" placeholder="0" value={price} onChange={setPrice} />
        <Button
          type="button"
          variant="secondary"
          disabled={!group.trim() || !name.trim()}
          busy={add.isPending}
          onClick={() =>
            add.mutate(undefined, {
              onSuccess: () => {
                setName("");
                setPrice("");
              },
            })
          }
        >
          Add option
        </Button>
      </div>
      <ErrorNote error={add.error ?? archive.error} />
    </section>
  );
}

export function ProductSheet({
  product,
  categories,
  defaultCategory,
  onClose,
}: {
  product: Product | null;
  categories: Category[];
  defaultCategory?: string;
  onClose: () => void;
}) {
  // After creating a dish the sheet stays open in edit mode so options can be added.
  const [created, setCreated] = useState<Product | null>(product);
  const { data: all } = useProducts(true);
  const current = created ? (all?.find((p) => p.id === created.id) ?? created) : null;
  const [name, setName] = useState(product?.name ?? "");
  const [categoryId, setCategoryId] = useState(product?.category_id ?? defaultCategory ?? "");
  const [price, setPrice] = useState<number | "">(product?.price ?? "");
  const [description, setDescription] = useState(product?.description ?? "");
  const [prep, setPrep] = useState(String(product?.prep_minutes ?? 15));
  const [photoUrl, setPhotoUrl] = useState(product?.image_url ?? null);
  const [imageKey, setImageKey] = useState<string | null | undefined>(undefined); // undefined = unchanged

  const save = useSave(async () => {
    const body: Record<string, unknown> = {
      name: name.trim(),
      category_id: categoryId,
      price: price === "" ? 0 : price,
      description: description.trim(),
      prep_minutes: Number(prep) || 15,
    };
    if (imageKey !== undefined) body.image_key = imageKey;
    return current
      ? api.patch<Product>(`/hotel/products/${current.id}`, body)
      : api.post<Product>("/hotel/products", body);
  }, [keys.products]);

  const archive = useSave(
    (is_archived: boolean) => api.patch<Product>(`/hotel/products/${current!.id}`, { is_archived }),
    [keys.products],
  );

  function submit(e: FormEvent) {
    e.preventDefault();
    const wasNew = !current;
    save.mutate(undefined, {
      onSuccess: (saved) => {
        setImageKey(undefined);
        if (wasNew) setCreated(saved);
        else onClose();
      },
    });
  }

  return (
    <Sheet
      open
      title={current ? `Edit ${current.name}` : "New dish"}
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          {current ? (
            <Button
              variant={current.is_archived ? "secondary" : "danger"}
              busy={archive.isPending}
              onClick={() => archive.mutate(!current.is_archived, { onSuccess: onClose })}
            >
              {current.is_archived ? "Restore" : "Archive"}
            </Button>
          ) : null}
          <Button className="flex-1" type="submit" form="product-form" busy={save.isPending}>
            {current ? "Save" : "Create dish"}
          </Button>
        </div>
      }
    >
      <form id="product-form" onSubmit={submit} className="flex flex-col gap-4">
        {current?.is_archived ? <Badge tone="warn">Archived: hidden from customers</Badge> : null}
        <PhotoPicker
          url={photoUrl}
          onUploaded={(u) => {
            setImageKey(u.image_key);
            setPhotoUrl(u.image_url);
          }}
          onRemove={() => {
            setImageKey(null);
            setPhotoUrl(null);
          }}
        />
        <Field label="Dish name">
          {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Price" hint="Same as your walk-in price">
            {(id) => <MoneyInput id={id} value={price} onChange={setPrice} required />}
          </Field>
          <Field label="Prep time (min)">
            {(id) => (
              <Input id={id} inputMode="numeric" value={prep} onChange={(e) => setPrep(e.target.value.replace(/\D/g, ""))} />
            )}
          </Field>
        </div>
        <Field label="Category">
          {(id) => (
            <Select id={id} value={categoryId} onChange={(e) => setCategoryId(e.target.value)} required>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Description" hint="Optional. What's in it, portion size.">
          {(id) => (
            <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} />
          )}
        </Field>
        <ErrorNote error={save.error ?? archive.error} />
      </form>

      {current ? (
        <div className="mt-6 border-t border-line pt-4">
          <OptionsEditor product={current} />
        </div>
      ) : (
        <p className="mt-4 text-sm text-muted">You can add options and extras after creating the dish.</p>
      )}
    </Sheet>
  );
}
