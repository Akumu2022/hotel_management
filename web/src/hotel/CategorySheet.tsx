import { type FormEvent, useState } from "react";

import { Button, ErrorNote, Field, Input, Sheet } from "../components/ui";
import { api } from "../lib/api";
import { hhmm } from "../lib/format";
import type { Category } from "../lib/types";
import { keys, useSave } from "./hooks";

export function CategorySheet({ category, onClose }: { category: Category | null; onClose: () => void }) {
  const [name, setName] = useState(category?.name ?? "");
  const [sortOrder, setSortOrder] = useState(String(category?.sort_order ?? 0));
  const [timed, setTimed] = useState(!!category?.available_from);
  const [from, setFrom] = useState(hhmm(category?.available_from ?? "06:00"));
  const [to, setTo] = useState(hhmm(category?.available_to ?? "11:00"));

  const save = useSave(async () => {
    const body = {
      name: name.trim(),
      sort_order: Number(sortOrder) || 0,
      available_from: timed ? from : null,
      available_to: timed ? to : null,
    };
    return category ? api.patch(`/hotel/categories/${category.id}`, body) : api.post("/hotel/categories", body);
  }, [keys.categories]);

  const remove = useSave(() => api.del(`/hotel/categories/${category!.id}`), [keys.categories]);

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate(undefined, { onSuccess: onClose });
  }

  return (
    <Sheet
      open
      title={category ? "Edit category" : "New category"}
      onClose={onClose}
      footer={
        <div className="flex gap-2">
          {category ? (
            <Button
              variant="danger"
              busy={remove.isPending}
              onClick={() => remove.mutate(undefined, { onSuccess: onClose })}
            >
              Delete
            </Button>
          ) : null}
          <Button className="flex-1" type="submit" form="category-form" busy={save.isPending}>
            Save
          </Button>
        </div>
      }
    >
      <form id="category-form" onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Name">
          {(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} required maxLength={80} />}
        </Field>
        <Field label="Position" hint="Lower numbers are shown first.">
          {(id) => (
            <Input id={id} inputMode="numeric" value={sortOrder} onChange={(e) => setSortOrder(e.target.value.replace(/\D/g, ""))} />
          )}
        </Field>
        <label className="flex items-center gap-2 text-sm font-medium">
          <input type="checkbox" checked={timed} onChange={(e) => setTimed(e.target.checked)} />
          Only show at certain times (e.g. breakfast)
        </label>
        {timed ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="From">{(id) => <Input id={id} type="time" value={from} onChange={(e) => setFrom(e.target.value)} />}</Field>
            <Field label="To">{(id) => <Input id={id} type="time" value={to} onChange={(e) => setTo(e.target.value)} />}</Field>
          </div>
        ) : null}
        <ErrorNote error={save.error ?? remove.error} />
      </form>
    </Sheet>
  );
}
