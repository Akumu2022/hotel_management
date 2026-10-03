/** Same rules as the server (backend services/orders.point_in_zone, settings.distance_km). */

export type LngLat = [number, number];

export function pointInZone(lat: number, lng: number, zone: LngLat[]): boolean {
  if (zone.length < 3) return false;
  let inside = false;
  for (let i = 0, j = zone.length - 1; i < zone.length; j = i++) {
    const [xi, yi] = zone[i];
    const [xj, yj] = zone[j];
    if (yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function distanceKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const r = 6371;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dp = rad(lat2 - lat1);
  const dl = rad(lng2 - lng1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

/** A circle as a polygon ring of [lng, lat] points (what the zone setting stores). */
export function circleZone(lat: number, lng: number, radiusKm: number, points = 48): LngLat[] {
  const out: LngLat[] = [];
  const dLat = radiusKm / 110.574;
  const dLng = radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180));
  for (let i = 0; i < points; i++) {
    const t = (2 * Math.PI * i) / points;
    out.push([+(lng + dLng * Math.cos(t)).toFixed(6), +(lat + dLat * Math.sin(t)).toFixed(6)]);
  }
  return out;
}
