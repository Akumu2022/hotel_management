/** Map pictures. With a MapTiler key (VITE_MAPTILER_KEY) every map uses MapTiler's street and
 * satellite tiles; without one it falls back to the free OpenStreetMap server, which is only
 * fine for testing (its policy forbids heavy use). */
import L from "leaflet";

const KEY = (import.meta.env.VITE_MAPTILER_KEY as string | undefined)?.trim();

export function streetTiles(): L.TileLayer {
  if (KEY) {
    return L.tileLayer(`https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}.png?key=${KEY}`, {
      maxZoom: 20,
      attribution: '© <a href="https://www.maptiler.com/copyright/" target="_blank" rel="noreferrer">MapTiler</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>',
    });
  }
  return L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" });
}

export function satelliteTiles(): L.TileLayer {
  if (KEY) {
    return L.tileLayer(`https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg?key=${KEY}`, {
      maxZoom: 20,
      attribution: '© <a href="https://www.maptiler.com/copyright/" target="_blank" rel="noreferrer">MapTiler</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>',
    });
  }
  return L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Imagery © Esri" });
}
