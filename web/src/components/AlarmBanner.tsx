/** Shown until sound is allowed: browsers block sound until the first touch on the page. */
import clsx from "clsx";
import { BellRing } from "lucide-react";

import { unlockAlarm, useAlarmBlocked, useAlarmUnlocked } from "../lib/alarm";

export function AlarmBanner() {
  const unlocked = useAlarmUnlocked();
  const urgent = useAlarmBlocked();
  if (unlocked) return null;
  return (
    <button
      onClick={unlockAlarm}
      className={clsx(
        "flex w-full items-center justify-center gap-2 px-4 py-3 text-[0.9375rem] font-bold",
        urgent ? "animate-pulse bg-bad text-white" : "bg-ink text-surface",
      )}
    >
      <BellRing className="size-5" />
      {urgent ? "Something needs you: tap anywhere to hear the alarm" : "Tap anywhere to turn on sound alerts"}
    </button>
  );
}
