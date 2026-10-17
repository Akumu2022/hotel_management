/// Map pictures. Build with --dart-define=MAPTILER_KEY=... to use MapTiler; without a key the
/// free OpenStreetMap server is used, which is only fine for testing.
const mapTilerKey = String.fromEnvironment('MAPTILER_KEY');

String get streetTilesUrl => mapTilerKey.isEmpty
    ? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
    : 'https://api.maptiler.com/maps/streets-v2/{z}/{x}/{y}.png?key=$mapTilerKey';

String get satelliteTilesUrl => mapTilerKey.isEmpty
    ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
    : 'https://api.maptiler.com/tiles/satellite-v2/{z}/{x}/{y}.jpg?key=$mapTilerKey';
