// Approximate lat/lng for major Indian metros, used to drop lead pins on the
// stylized India map in the Live Agent Theater. Coordinates are projected into
// the map's viewBox by IndiaMap.tsx — only relative position matters.
export const CITY_COORDS: Record<string, { lat: number; lng: number }> = {
  mumbai: { lat: 19.076, lng: 72.877 },
  navimumbai: { lat: 19.033, lng: 73.029 },
  thane: { lat: 19.218, lng: 72.978 },
  pune: { lat: 18.52, lng: 73.857 },
  nashik: { lat: 19.997, lng: 73.789 },
  nagpur: { lat: 21.146, lng: 79.088 },
  aurangabad: { lat: 19.876, lng: 75.343 },
  delhi: { lat: 28.704, lng: 77.102 },
  newdelhi: { lat: 28.614, lng: 77.209 },
  noida: { lat: 28.535, lng: 77.391 },
  gurgaon: { lat: 28.46, lng: 77.026 },
  gurugram: { lat: 28.46, lng: 77.026 },
  ghaziabad: { lat: 28.669, lng: 77.453 },
  bengaluru: { lat: 12.972, lng: 77.595 },
  bangalore: { lat: 12.972, lng: 77.595 },
  chennai: { lat: 13.083, lng: 80.27 },
  coimbatore: { lat: 11.017, lng: 76.956 },
  madurai: { lat: 9.925, lng: 78.119 },
  hyderabad: { lat: 17.385, lng: 78.487 },
  vijayawada: { lat: 16.507, lng: 80.648 },
  visakhapatnam: { lat: 17.687, lng: 83.218 },
  vizag: { lat: 17.687, lng: 83.218 },
  kolkata: { lat: 22.573, lng: 88.364 },
  bhubaneswar: { lat: 20.296, lng: 85.825 },
  patna: { lat: 25.594, lng: 85.138 },
  ranchi: { lat: 23.344, lng: 85.31 },
  guwahati: { lat: 26.145, lng: 91.736 },
  ahmedabad: { lat: 23.023, lng: 72.572 },
  surat: { lat: 21.17, lng: 72.831 },
  vadodara: { lat: 22.307, lng: 73.181 },
  rajkot: { lat: 22.303, lng: 70.802 },
  jaipur: { lat: 26.912, lng: 75.787 },
  jodhpur: { lat: 26.238, lng: 73.024 },
  udaipur: { lat: 24.585, lng: 73.712 },
  lucknow: { lat: 26.847, lng: 80.946 },
  kanpur: { lat: 26.45, lng: 80.332 },
  varanasi: { lat: 25.318, lng: 82.973 },
  indore: { lat: 22.72, lng: 75.857 },
  bhopal: { lat: 23.26, lng: 77.413 },
  chandigarh: { lat: 30.733, lng: 76.779 },
  ludhiana: { lat: 30.901, lng: 75.857 },
  amritsar: { lat: 31.634, lng: 74.873 },
  dehradun: { lat: 30.317, lng: 78.032 },
  kochi: { lat: 9.932, lng: 76.267 },
  cochin: { lat: 9.932, lng: 76.267 },
  thiruvananthapuram: { lat: 8.524, lng: 76.937 },
  goa: { lat: 15.299, lng: 74.124 },
  panaji: { lat: 15.491, lng: 73.827 },
  raipur: { lat: 21.251, lng: 81.629 },
  mysuru: { lat: 12.295, lng: 76.639 },
  mysore: { lat: 12.295, lng: 76.639 },
}

const INDIA_CENTER = { lat: 22.5, lng: 79.0 }

/** Resolve a location/address string to coords; falls back to India centroid
 *  jittered by a stable hash so unknown cities still scatter believably. */
export function geocode(text?: string | null, seed = 0): { lat: number; lng: number } {
  const t = (text || '').toLowerCase().replace(/[^a-z]/g, '')
  for (const city of Object.keys(CITY_COORDS)) {
    if (t.includes(city)) return CITY_COORDS[city]
  }
  // deterministic jitter around the centroid
  const h = hash(text || String(seed))
  return {
    lat: INDIA_CENTER.lat + ((h % 1000) / 1000 - 0.5) * 9,
    lng: INDIA_CENTER.lng + (((h >> 10) % 1000) / 1000 - 0.5) * 12,
  }
}

function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return Math.abs(h)
}

// Map India's lng/lat range into a 0..100 viewBox space.
export const MAP_BOUNDS = { minLng: 68, maxLng: 97.5, minLat: 6.5, maxLat: 37.5 }
export function project(lat: number, lng: number): { x: number; y: number } {
  const x = ((lng - MAP_BOUNDS.minLng) / (MAP_BOUNDS.maxLng - MAP_BOUNDS.minLng)) * 100
  const y = (1 - (lat - MAP_BOUNDS.minLat) / (MAP_BOUNDS.maxLat - MAP_BOUNDS.minLat)) * 100
  return { x, y }
}

// Real (simplified) India mainland boundary as [lng, lat] waypoints, traced
// clockwise from Kashmir. Projected with project() so the outline and the city
// pins share ONE coordinate system — pins always land on the correct spot.
export const INDIA_BORDER: [number, number][] = [
  // North border (Kashmir → Arunachal), W→E
  [74.3, 34.3], [75.0, 34.6], [76.5, 34.7], [78.0, 35.5], [78.9, 34.3],
  [79.2, 33.0], [79.0, 32.0], [80.0, 30.8], [81.0, 30.2], [82.0, 29.6],
  [83.5, 29.1], [84.8, 28.5], [86.0, 27.9], [88.0, 27.2], [88.8, 27.4],
  [89.7, 28.1], [91.6, 27.8], [92.0, 27.5], [93.0, 28.3], [94.5, 29.3],
  [95.5, 29.0], [96.6, 29.4], [97.4, 28.2], [96.9, 27.5], [97.3, 24.4],
  // Northeast (Manipur/Mizoram/Tripura) + Bangladesh outline
  [95.1, 23.8], [94.0, 24.0], [93.3, 23.0], [93.4, 22.2], [92.7, 22.0],
  [92.2, 23.7], [91.6, 22.9], [91.4, 24.1], [92.4, 24.9], [91.9, 25.2],
  [90.0, 25.2], [89.8, 26.0], [88.6, 26.5], [88.1, 26.6], [88.7, 24.2],
  [88.5, 23.5], [88.9, 22.0],
  // East coast (Bay of Bengal), N→S
  [87.0, 21.5], [86.5, 20.8], [85.9, 20.2], [84.8, 19.3], [83.3, 17.8],
  [82.2, 16.9], [80.9, 15.9], [80.3, 15.5], [80.2, 13.5], [80.3, 13.1],
  [79.9, 11.9], [79.8, 11.4], [79.4, 10.8],
  // Southern tip (Kanyakumari)
  [78.9, 9.5], [78.2, 8.8], [77.5, 8.08],
  // West coast (Arabian Sea), S→N
  [76.6, 8.9], [76.0, 10.3], [75.7, 11.8], [74.8, 13.0], [74.4, 14.8],
  [73.8, 15.7], [73.3, 17.7], [72.9, 18.9], [72.8, 19.8], [72.7, 20.8],
  [72.6, 21.7], [72.9, 22.4], [72.2, 22.3], [70.9, 22.5], [69.7, 22.4],
  [68.9, 22.1], [68.2, 23.6], [68.7, 23.9], [70.0, 24.0], [71.0, 24.3],
  // Rajasthan/Punjab border back up to Kashmir
  [70.6, 25.7], [70.1, 27.0], [71.9, 27.9], [73.0, 28.5], [73.9, 29.9],
  [74.6, 31.0], [74.5, 31.7], [75.3, 32.3], [74.0, 32.5], [74.3, 34.3],
]

/** SVG path string for the India outline in the 0..100 projected space. */
export function indiaPath(): string {
  return (
    INDIA_BORDER.map(([lng, lat], i) => {
      const { x, y } = project(lat, lng)
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
    }).join(' ') + ' Z'
  )
}
