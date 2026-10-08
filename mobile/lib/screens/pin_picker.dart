import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';
import '../api.dart';
import '../i18n.dart';
import '../util.dart';

const _bungoma = LatLng(0.5635, 34.5606);

/// Full-screen map: drag the map under the fixed pin, or search a place, then confirm the spot.
/// Pops with the chosen [LatLng].
class PinPickerScreen extends StatefulWidget {
  final LatLng? start;
  final String? hotelSlug;
  const PinPickerScreen({super.key, this.start, this.hotelSlug});
  @override
  State<PinPickerScreen> createState() => _PinPickerScreenState();
}

class _PinPickerScreenState extends State<PinPickerScreen> {
  final _map = MapController();
  final _search = TextEditingController();
  Timer? _debounce;
  late LatLng _center = widget.start ?? _bungoma;
  LatLng? _hotel;
  bool _satellite = false, _locating = false, _searching = false;
  List<Json> _results = [];

  @override
  void initState() {
    super.initState();
    _loadHotel();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  Future<void> _loadHotel() async {
    final slug = widget.hotelSlug;
    if (slug == null) return;
    try {
      final hotels = (await apiGet('/hotels') as List).cast<Json>();
      final h = hotels.firstWhere((h) => h['slug'] == slug, orElse: () => {});
      if (h['lat'] == null || h['lng'] == null || !mounted) return;
      final p = LatLng((h['lat'] as num).toDouble(), (h['lng'] as num).toDouble());
      setState(() => _hotel = p);
      if (widget.start == null) _map.move(p, 16);
    } catch (_) {}
  }

  void _onSearch(String q) {
    _debounce?.cancel();
    if (q.trim().length < 3) {
      setState(() => _results = []);
      return;
    }
    _debounce = Timer(const Duration(milliseconds: 550), () async {
      setState(() => _searching = true);
      try {
        final uri = Uri.https('nominatim.openstreetmap.org', '/search', {'q': q.trim(), 'format': 'json', 'limit': '6', 'countrycodes': 'ke'});
        final res = await http.get(uri, headers: {'User-Agent': 'ChakulaApp/1.0 (com.hotelapp.hotel_app)'}).timeout(const Duration(seconds: 10));
        final list = (jsonDecode(res.body) as List).cast<Json>();
        if (mounted) setState(() => _results = list);
      } catch (_) {
        if (mounted) toast(context, tr('Search is unavailable. Drag the map instead.'));
      } finally {
        if (mounted) setState(() => _searching = false);
      }
    });
  }

  Future<void> _myLocation() async {
    setState(() => _locating = true);
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) throw tr('Allow location access, or search for your place');
      final p = await Geolocator.getCurrentPosition(locationSettings: const LocationSettings(accuracy: LocationAccuracy.high))
          .timeout(const Duration(seconds: 15), onTimeout: () => throw tr('Could not get your location. Turn on GPS or search for your place'));
      _map.move(LatLng(p.latitude, p.longitude), 17);
    } catch (e) {
      if (mounted) toast(context, '$e');
    } finally {
      if (mounted) setState(() => _locating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final km = _hotel == null ? null : const Distance().as(LengthUnit.Meter, _hotel!, _center) / 1000;
    return Scaffold(
      body: Stack(children: [
        FlutterMap(
          mapController: _map,
          options: MapOptions(
            initialCenter: _center,
            initialZoom: 16,
            minZoom: 4,
            maxZoom: 19,
            onPositionChanged: (cam, _) => setState(() => _center = cam.center),
          ),
          children: [
            TileLayer(
              urlTemplate: _satellite
                  ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
                  : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'com.hotelapp.hotel_app',
              maxNativeZoom: 19,
            ),
            if (_hotel != null)
              MarkerLayer(markers: [
                Marker(point: _hotel!, width: 40, height: 40, child: const Icon(Icons.store_rounded, color: brand, size: 34)),
              ]),
          ],
        ),
        // The pin stays in the middle; its tip is the chosen spot.
        const IgnorePointer(child: Center(child: Padding(padding: EdgeInsets.only(bottom: 44), child: Icon(Icons.location_on, size: 48, color: brand)))),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(children: [
              Material(
                elevation: 3,
                borderRadius: BorderRadius.circular(28),
                color: cs.surface,
                child: TextField(
                  controller: _search,
                  onChanged: _onSearch,
                  textInputAction: TextInputAction.search,
                  decoration: InputDecoration(
                    hintText: tr('Search a place, e.g. Bungoma stage'),
                    prefixIcon: IconButton(icon: const Icon(Icons.arrow_back), onPressed: () => Navigator.pop(context)),
                    suffixIcon: _searching
                        ? const Padding(padding: EdgeInsets.all(14), child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2)))
                        : (_search.text.isEmpty ? null : IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() { _search.clear(); _results = []; }))),
                    border: InputBorder.none,
                    enabledBorder: InputBorder.none,
                    focusedBorder: InputBorder.none,
                    filled: false,
                  ),
                ),
              ),
              if (_results.isNotEmpty)
                Material(
                  elevation: 3,
                  borderRadius: BorderRadius.circular(18),
                  color: cs.surface,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 260),
                    child: ListView(shrinkWrap: true, padding: EdgeInsets.zero, children: [
                      for (final r in _results)
                        ListTile(
                          dense: true,
                          leading: const Icon(Icons.place_outlined),
                          title: Text('${r['display_name']}', maxLines: 2, overflow: TextOverflow.ellipsis),
                          onTap: () {
                            FocusScope.of(context).unfocus();
                            _map.move(LatLng(double.parse('${r['lat']}'), double.parse('${r['lon']}')), 17);
                            setState(() => _results = []);
                          },
                        ),
                    ]),
                  ),
                ),
            ]),
          ),
        ),
        Positioned(
          right: 12,
          bottom: 150,
          child: Column(children: [
            FloatingActionButton.small(
              heroTag: 'sat',
              onPressed: () => setState(() => _satellite = !_satellite),
              child: Icon(_satellite ? Icons.map_outlined : Icons.satellite_alt_outlined),
            ),
            const SizedBox(height: 10),
            FloatingActionButton.small(
              heroTag: 'loc',
              onPressed: _locating ? null : _myLocation,
              child: _locating ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.my_location),
            ),
          ]),
        ),
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: Container(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 16),
            decoration: BoxDecoration(color: cs.surface, borderRadius: const BorderRadius.vertical(top: Radius.circular(24)), boxShadow: const [BoxShadow(blurRadius: 12, color: Colors.black26)]),
            child: SafeArea(
              top: false,
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr('Drag the map to put the pin on your door'), style: kSection),
                if (km != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(tr('About {km} km from the hotel (in a straight line)', {'km': km.toStringAsFixed(1)}), style: labelOf(context))),
                const SizedBox(height: 12),
                FilledButton(style: fullWidthFilled, onPressed: () => Navigator.pop(context, _center), child: Text(tr('Confirm this spot'))),
              ]),
            ),
          ),
        ),
      ]),
    );
  }
}
