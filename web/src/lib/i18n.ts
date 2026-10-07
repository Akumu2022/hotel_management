/**
 * English / Kiswahili for the customer app (spec: "English, with Swahili labels").
 * English strings are the keys; a missing translation falls back to English.
 * Placeholders: t("Closes {time}", { time }) .
 * NOTE: have a native speaker review SW before launch.
 */
import { useSyncExternalStore } from "react";

export type Lang = "en" | "sw";

const SW: Record<string, string> = {
  // Header, navigation, journey
  "My orders": "Oda zangu",
  Help: "Msaada",
  Home: "Nyumbani",
  "All hotels": "Hoteli zote",
  "Back to menu": "Rudi kwenye menyu",
  "Choose food": "Chagua chakula",
  Checkout: "Kamilisha oda",
  Pay: "Lipa",
  Track: "Fuatilia",
  "Step {n} of {total}:": "Hatua {n} kati ya {total}:",

  // Home
  "Karibu!": "Karibu!",
  "Hot food from local hotels, delivered or ready for pickup.": "Chakula moto kutoka hoteli za karibu, kuletewa au kuchukua mwenyewe.",
  "Pay by M-Pesa straight to the hotel": "Lipa kwa M-Pesa moja kwa moja kwa hoteli",
  "Today's deals": "Ofa za leo",
  "Hotels near you": "Hoteli zilizo karibu nawe",
  "Order now": "Agiza sasa",
  Close: "Funga",
  "Search food, e.g. pizza": "Tafuta chakula, mf. pizza",
  "No dish matches “{q}”": "Hakuna chakula kinacolingana na “{q}”",
  "No hotels are open right now": "Hakuna hoteli zilizo wazi sasa hivi",
  "New hotels are joining soon. Check back in a little while.": "Hoteli mpya zinakuja hivi karibuni. Rudi baada ya muda mfupi.",
  "View menu": "Ona menyu",
  "Your last order": "Oda yako ya mwisho",
  "Staff login": "Kuingia kwa wafanyakazi",
  "Get the Chakula app": "Pata app ya Chakula",
  Install: "Sakinisha",

  // Hotel status
  "Open now": "Iko wazi sasa",
  "Closes {time}": "Inafunga saa {time}",
  "Opens {time}": "Itafunguliwa saa {time}",
  Closed: "Imefungwa",
  "Not taking orders": "Haipokei oda kwa sasa",
  Delivery: "Kuletewa",
  Pickup: "Kuchukua",
  Call: "Piga simu",
  "{name} isn't taking orders right now. You can still look at the menu.": "{name} haipokei oda kwa sasa. Bado unaweza kuangalia menyu.",
  "Ready in about {min} min": "Itakuwa tayari baada ya dakika {min} hivi",
  "{min} min": "dakika {min}",

  // Menu
  "All Menu": "Menyu yote",
  "Search dishes": "Tafuta chakula",
  "By category": "Kwa aina",
  "Price: low to high": "Bei: chini hadi juu",
  "Price: high to low": "Bei: juu hadi chini",
  "Lowest price first": "Bei ya chini kwanza",
  "Highest price first": "Bei ya juu kwanza",
  Add: "Ongeza",
  "Sold out": "Kimeisha",
  "{n} in order": "{n} kwenye oda",
  "Add to order": "Ongeza kwenye oda",
  optional: "si lazima",
  Free: "Bure",
  "Added {name}": "{name} imeongezwa",
  "No dishes match “{q}”": "Hakuna chakula kinacholingana na “{q}”",
  "Clear search": "Futa utafutaji",
  "No dishes here yet": "Bado hakuna chakula hapa",
  "Start a new order?": "Anza oda mpya?",
  "Your order has dishes from {hotel}. You can order from one hotel at a time, so we'll clear it first.":
    "Oda yako ina chakula kutoka {hotel}. Unaweza kuagiza kutoka hoteli moja kwa wakati, kwa hivyo tutaifuta kwanza.",
  "Start new order": "Anza oda mpya",
  "Keep my order": "Baki na oda yangu",

  // Order panel
  "Your order": "Oda yako",
  "Nothing added yet": "Bado hujaongeza kitu",
  "Clear order": "Futa oda",
  "How do you want your food?": "Ungependa kupata chakula chako vipi?",
  "Deliver to me": "Niletewe",
  "I'll pick it up": "Nitachukua mwenyewe",
  "A rider brings it": "Rider atakuletea",
  from: "kuanzia",
  "Collect at {hotel} · no fee": "Chukua {hotel} · bila ada",
  "Collect it yourself · no fee": "Chukua mwenyewe · bila ada",
  "Not available yet": "Bado haipatikani",
  "Order details": "Maelezo ya oda",
  "Payment details": "Maelezo ya malipo",
  Food: "Chakula",
  Discount: "Punguzo",
  "Service fee": "Ada ya huduma",
  "Free delivery": "Kuletewa bure",
  "Your rider": "Mwendeshaji wako",
  "{name} is on the way": "{name} yuko njiani",
  "{name} is almost there": "{name} amekaribia",
  "{name}'s location is paused": "Mahali pa {name} pamesimama",
  "Get ready with your code": "Jiandae na namba yako",
  "{km} km away · about {min} min": "Umbali wa km {km} · takriban dakika {min}",
  "Last seen {min} min ago": "Alionekana dakika {min} zilizopita",
  "Updated {s}s ago": "Imesasishwa sekunde {s} zilizopita",
  Live: "Moja kwa moja",
  Paused: "Imesimama",
  "Live map of your rider": "Ramani ya mwendeshaji wako",
  "Verified by Chakula": "Amethibitishwa na Chakula",
  "Did you pay the rider {amount}?": "Ulimlipa mwendeshaji {amount}?",
  "The rider says the delivery fee wasn't paid. Please tell us honestly.": "Mwendeshaji anasema ada ya usafiri haikulipwa. Tafadhali tuambie ukweli.",
  "Yes, I paid": "Ndiyo, nililipa",
  "No, I didn't": "Hapana, sikulipa",
  "Stamp card reward": "Zawadi ya kadi ya stempu",
  Orders: "Oda",
  Completed: "Zimekamilika",
  "Total paid": "Jumla uliyolipa",
  "You've saved {amount} with Chakula rewards": "Umeokoa {amount} kwa zawadi za Chakula",
  Active: "Zinaendelea",
  "Any time": "Wakati wowote",
  "Last 30 days": "Siku 30 zilizopita",
  "Last 3 months": "Miezi 3 iliyopita",
  "Search a dish, hotel or order number": "Tafuta chakula, hoteli au namba ya oda",
  "No orders match these filters.": "Hakuna oda zinazolingana na vichujio hivi.",
  Refunded: "Imerudishwa",
  "Your history is kept on this phone. Clearing the browser removes it from here.": "Historia yako imehifadhiwa kwenye simu hii. Ukifuta data ya kivinjari, itaondoka hapa.",
  "Add {amount} more food for free delivery": "Ongeza chakula cha {amount} upate kuletewa bure",
  "Pay delivery by M-Pesa too and it's free": "Lipia usafiri kwa M-Pesa pia, na ni bure",
  "Your stamp card is full!": "Kadi yako ya stempu imejaa!",
  "Stamp card": "Kadi ya stempu",
  "{have} of {every} stamps": "Stempu {have} kati ya {every}",
  "{amount} off this order, on us.": "Punguzo la {amount} kwenye oda hii, ni zawadi yetu.",
  "{left} more completed orders and you get {amount} off.": "Oda {left} zaidi zikikamilika, unapata punguzo la {amount}.",
  Total: "Jumla",
  "Continue to checkout": "Endelea kukamilisha oda",
  "Your order is empty": "Oda yako haina kitu",
  "Tap “Add” on any dish to start your order.": "Bonyeza “Ongeza” kwenye chakula chochote kuanza oda yako.",
  "Clear your order?": "Futa oda yako?",
  "All {n} items from {hotel} will be removed.": "Vitu vyote {n} kutoka {hotel} vitaondolewa.",
  "Yes, clear it": "Ndiyo, ifute",
  "Keep it": "Baki nayo",
  "View your order": "Ona oda yako",

  // Checkout
  "Ordering from {hotel}": "Unaagiza kutoka {hotel}",
  "{done} of 4 steps done": "Hatua {done} kati ya 4 zimekamilika",
  "All set. Ready to place your order": "Kila kitu kiko tayari. Weka oda yako",
  "Your details": "Maelezo yako",
  "So the hotel and rider can reach you": "Ili hoteli na rider waweze kukupata",
  "Your name": "Jina lako",
  "Phone number": "Nambari ya simu",
  "Where should we bring it?": "Tukuletee wapi?",
  "Tap the map on your location, then describe the spot": "Bonyeza ramani mahali ulipo, kisha eleza mahali hapo",
  "Directions for the rider": "Maelekezo kwa rider",
  "Where to collect": "Mahali pa kuchukua",
  "We'll tell you when it's ready": "Tutakujulisha ikiwa tayari",
  "Show your order number at the counter": "Onyesha nambari ya oda yako kaunta",
  "How will you pay?": "Utalipa vipi?",
  "Everything by M-Pesa now": "Lipa yote kwa M-Pesa sasa",
  "Food and delivery in one payment": "Chakula na usafiri kwa malipo moja",
  "Food by M-Pesa, {fee} cash to the rider": "Chakula kwa M-Pesa, {fee} pesa taslimu kwa rider",
  "Pay the delivery fee at your door": "Lipa ada ya usafiri mlangoni",
  "Not available for this number": "Haipatikani kwa nambari hii",
  "M-Pesa now": "M-Pesa sasa",
  "Pay to the hotel's Till before you collect": "Lipa kwa Till ya hoteli kabla ya kuchukua",
  "Cash when I collect": "Pesa taslimu nikichukua",
  "Pay at the counter": "Lipa kaunta",
  "Promo code (optional)": "Nambari ya ofa (si lazima)",
  Apply: "Tumia",
  "Pay by M-Pesa": "Lipa kwa M-Pesa",
  "+ cash to the rider": "+ pesa taslimu kwa rider",
  "Cancel order": "Ghairi oda",
  "Place order": "Weka oda",
  "By ordering you agree to the terms and privacy policy.": "Kwa kuagiza unakubali masharti na sera ya faragha.",
  "Cancel this order?": "Ghairi oda hii?",
  "Yes, cancel order": "Ndiyo, ghairi oda",
  "Keep ordering": "Endelea kuagiza",
  "Keep order": "Baki na oda",
  "Use my location": "Tumia mahali nilipo",
  "or tap the map": "au bonyeza ramani",
  "Pin set. Tap the map to move it.": "Mahali pamewekwa. Bonyeza ramani kubadilisha.",
  "That spot is outside our delivery area. Move the pin inside the dashed line, or choose pickup.":
    "Mahali hapo ni nje ya eneo letu la kuleta. Sogeza alama ndani ya mstari, au chagua kuchukua.",
  "{km} km from {hotel} · delivery {fee}": "km {km} kutoka {hotel} · usafiri {fee}",

  // Pay / tracking
  "Order #{code}": "Oda #{code}",
  "Waiting for payment": "Inasubiri malipo",
  "Checking payment": "Inakagua malipo",
  "Payment received": "Malipo yamepokelewa",
  "Hotel accepted": "Hoteli imekubali",
  "Being prepared": "Inaandaliwa",
  Ready: "Iko tayari",
  "Rider picked up": "Rider amechukua",
  "On the way": "Iko njiani",
  Delivered: "Imefikishwa",
  Collected: "Imechukuliwa",
  "Expired: not paid in time": "Imeisha muda: haikulipwa kwa wakati",
  "The hotel couldn't take this order": "Hoteli haikuweza kupokea oda hii",
  "Order cancelled": "Oda imeghairiwa",
  "Delivery failed": "Imeshindwa kufikishwa",
  "Pay with M-Pesa": "Lipa kwa M-Pesa",
  "Buy Goods Till number": "Nambari ya Till (Buy Goods)",
  Copy: "Nakili",
  Copied: "Imenakiliwa",
  "This page updates by itself once the hotel confirms your payment.": "Ukurasa huu utajisasisha hoteli ikithibitisha malipo yako.",
  "Delivery code": "Nambari ya kupokea",
  "Give it to the rider when your food arrives": "Mpe rider chakula chako kikifika",
  Progress: "Maendeleo",
  "Call hotel": "Piga hoteli",
  "Deliver to:": "Peleka:",
  "Order this again": "Agiza hii tena",
  "Order again": "Agiza tena",
  "Your order is back in the basket": "Oda yako imerudi kwenye kikapu",

  // Orders page
  "No orders yet": "Bado hakuna oda",
  "Orders you place on this phone will show here.": "Oda utakazoweka kwenye simu hii zitaonekana hapa.",
  "Browse hotels": "Angalia hoteli",

  // Order status chips (My orders)
  Paid: "Imelipwa",
  Accepted: "Imekubaliwa",
  "With the rider": "Iko na rider",
  Expired: "Imeisha muda",
  "Not accepted": "Haikukubaliwa",
  Cancelled: "Imeghairiwa",
  "Faster ordering, works on slow networks. No Play Store needed.": "Kuagiza haraka, inafanya kazi hata mtandao ukiwa dhaifu. Huhitaji Play Store.",
  "Tap Share, then “Add to Home Screen”.": "Bonyeza Share, kisha “Add to Home Screen”.",

  // Saved places
  "Saved places": "Maeneo yaliyohifadhiwa",
  "Save this place as": "Hifadhi mahali hapa kama",
  "Don't save": "Usihifadhi",
  Work: "Kazini",
  Other: "Kwingine",
  "Remove {place}": "Ondoa {place}",

  "You're offline. Your order is saved.": "Uko nje ya mtandao. Oda yako imehifadhiwa.",

  "cash to the rider": "pesa taslimu kwa rider",

  "Paid? Enter the M-Pesa code": "Umelipa? Weka nambari ya M-Pesa",
  "It's at the start of your M-Pesa message, e.g. SJK3ABC12D": "Iko mwanzoni mwa ujumbe wako wa M-Pesa, mfano SJK3ABC12D",
  Send: "Tuma",
  "M-Pesa codes have 10 letters and numbers.": "Nambari za M-Pesa zina herufi na tarakimu 10.",
  "Checking your payment": "Tunakagua malipo yako",
  "Code {code}. The hotel is confirming it, usually within a few minutes.": "Nambari {code}. Hoteli inathibitisha, kwa kawaida ndani ya dakika chache.",

  "Already paid?": "Tayari umelipa?",
  "Enter your M-Pesa code and the hotel will check it.": "Weka nambari yako ya M-Pesa na hoteli itaikagua.",

  // Help
  "Need help? Chat with us": "Unahitaji msaada? Ongea nasi",
  "On WhatsApp. We usually reply within minutes.": "Kwenye WhatsApp. Kwa kawaida tunajibu baada ya dakika chache.",
};

const KEY = "lang-v1";
let lang: Lang = (() => {
  try {
    return localStorage.getItem(KEY) === "sw" ? "sw" : "en";
  } catch {
    return "en";
  }
})();
const listeners = new Set<() => void>();

export function setLang(next: Lang) {
  lang = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* ignore */
  }
  document.documentElement.lang = next;
  listeners.forEach((fn) => fn());
}

export function getLang(): Lang {
  return lang;
}

export function tr(s: string, vars?: Record<string, string | number>): string {
  let out = lang === "sw" ? (SW[s] ?? s) : s;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, String(v));
  return out;
}

/** Re-renders the component when the language changes. */
export function useT() {
  useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => lang,
  );
  return tr;
}

export function useLang(): Lang {
  return useSyncExternalStore(
    (fn) => (listeners.add(fn), () => listeners.delete(fn)),
    () => lang,
  );
}
