/** "Install Chakula" prompt. Android/Chrome uses the browser's install event; iPhone gets a hint. */
import { Download, Share, X } from "lucide-react";
import { useEffect, useState } from "react";

import { useT } from "../lib/i18n";

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

const DISMISS_KEY = "install-dismissed-v1";

function dismissedRecently(): boolean {
  try {
    const at = Number(localStorage.getItem(DISMISS_KEY) || 0);
    return Date.now() - at < 7 * 24 * 3600_000;
  } catch {
    return false;
  }
}

export function InstallBanner() {
  const t = useT();
  const [event, setEvent] = useState<InstallEvent | null>(null);
  const [hidden, setHidden] = useState(dismissedRecently());
  const standalone = window.matchMedia?.("(display-mode: standalone)").matches;
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !standalone;

  useEffect(() => {
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setEvent(e as InstallEvent);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (hidden || standalone || (!event && !ios)) return null;

  const dismiss = () => {
    setHidden(true);
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="flex items-center gap-3 rounded-2xl border border-brand/20 bg-brand-soft p-3.5">
      <img src="/icon-192.png" alt="" className="size-11 shrink-0 rounded-xl shadow-sm" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold">{t("Get the Chakula app")}</p>
        <p className="text-xs text-muted">
          {event ? t("Faster ordering, works on slow networks. No Play Store needed.") : <><Share className="inline size-3.5" /> {t("Tap Share, then “Add to Home Screen”.")}</>}
        </p>
      </div>
      {event ? (
        <button
          onClick={async () => {
            await event.prompt();
            await event.userChoice;
            setEvent(null);
          }}
          className="flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-brand px-3.5 text-sm font-semibold text-white"
        >
          <Download className="size-4" /> {t("Install")}
        </button>
      ) : null}
      <button onClick={dismiss} aria-label="Not now" className="flex size-8 shrink-0 items-center justify-center rounded-full text-muted hover:bg-surface">
        <X className="size-4" />
      </button>
    </div>
  );
}
