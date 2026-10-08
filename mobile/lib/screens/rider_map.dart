import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../api.dart';
import '../i18n.dart';
import '../util.dart';

/// Live map once the food is on the road: the rider glides between position fixes and a dashed
/// line shows the road still to go to the customer's pin.
class RiderMap extends StatefulWidget {
  final String token;
  final Json live; // TrackOut.live
  final String riderName;
  const RiderMap({super.key, required this.token, required this.live, required this.riderName});
  @override
  State<RiderMap> createState() => _RiderMapState();
}

class _RiderMapState extends State<RiderMap> with SingleTickerProviderStateMixin {
  late final AnimationController _glide = AnimationController(vsync: this, duration: const Duration(seconds: 6));
  late LatLng _from = _fix, _to = _fix;
  List<LatLng>? _route;
  LatLng? _routedFrom;
  bool _loadingRoute = true;

  LatLng get _fix => LatLng((widget.live['rider_lat'] as num).toDouble(), (widget.live['rider_lng'] as num).toDouble());
  LatLng get _dest => LatLng((widget.live['dest_lat'] as num).toDouble(), (widget.live['dest_lng'] as num).toDouble());
  LatLng get _shown => LatLng(
        _from.latitude + (_to.latitude - _from.latitude) * _glide.value,
        _from.longitude + (_to.longitude - _from.longitude) * _glide.value,
      );

  @override
  void initState() {
    super.initState();
    _glide.addListener(() => setState(() {}));
    _loadRoute();
  }

  @override
  void didUpdateWidget(RiderMap old) {
    super.didUpdateWidget(old);
    final next = _fix;
    if (next != _to) {
      _from = _shown;
      _to = next;
      _glide.forward(from: 0);
      // A fresh road line only once the rider has moved a fair way (the server caches too).
      final r = _routedFrom;
      if (r == null || const Distance().as(LengthUnit.Meter, r, next) > 300) _loadRoute();
    }
  }

  Future<void> _loadRoute() async {
    _routedFrom = _fix;
    try {
      final r = await apiGet('/track/${widget.token}/route') as Json;
      final pts = r['points'] as List?;
      if (mounted) {
        setState(() {
          _route = pts?.map((p) => LatLng((p[0] as num).toDouble(), (p[1] as num).toDouble())).toList();
          _loadingRoute = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loadingRoute = false);
    }
  }

  /// The road still to go: from the rider's spot on the route to the destination.
  List<LatLng> get _line {
    final rider = _shown;
    final route = _route;
    if (route == null || route.length < 2) return [rider, _dest];
    var best = 0;
    var bestD = double.infinity;
    for (var i = 0; i < route.length; i++) {
      final dx = route[i].latitude - rider.latitude, dy = route[i].longitude - rider.longitude;
      final d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return [rider, ...route.sublist(best + 1)];
  }

  @override
  void dispose() {
    _glide.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final rider = _shown;
    final dest = _dest;
    final line = _line;
    final km = const Distance().as(LengthUnit.Meter, rider, dest) / 1000;
    final mins = (km / 20 * 60).ceil().clamp(1, 999); // a motorbike in town, ~20 km/h
    final live = widget.live['live'] == true;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(children: [
        SizedBox(
          height: 240,
          child: Stack(children: [
            FlutterMap(
              options: MapOptions(
                initialCameraFit: CameraFit.coordinates(coordinates: [rider, dest], padding: const EdgeInsets.all(52), maxZoom: 17),
                interactionOptions: const InteractionOptions(flags: InteractiveFlag.pinchZoom | InteractiveFlag.drag),
              ),
              children: [
                TileLayer(
                  urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                  userAgentPackageName: 'com.hotelapp.hotel_app',
                  maxNativeZoom: 19,
                ),
                PolylineLayer(polylines: [Polyline(points: line, strokeWidth: 5, color: brand, pattern: StrokePattern.dashed(segments: const [10, 8]))]),
                MarkerLayer(markers: [
                  Marker(point: dest, width: 40, height: 40, child: const _Pin(Icons.home_rounded, ink)),
                  Marker(point: rider, width: 46, height: 46, child: const _Pin(Icons.two_wheeler, brand, pulse: true)),
                ]),
              ],
            ),
            if (_loadingRoute) const Positioned(left: 0, right: 0, top: 0, child: LinearProgressIndicator(minHeight: 3)),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            const Icon(Icons.two_wheeler, color: brand),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(live ? tr('{name} is on the way', {'name': widget.riderName}) : tr('Waiting for {name}\'s location…', {'name': widget.riderName}), style: const TextStyle(fontWeight: FontWeight.w800)),
                Text(live ? tr('{km} km away · about {mins} min', {'km': km.toStringAsFixed(1), 'mins': mins}) : tr('Last position is a few minutes old'), style: TextStyle(color: mutedOf(context), fontSize: 13)),
              ]),
            ),
            if (live) const _LiveDot(),
          ]),
        ),
      ]),
    );
  }
}

class _Pin extends StatelessWidget {
  final IconData icon;
  final Color color;
  final bool pulse;
  const _Pin(this.icon, this.color, {this.pulse = false});
  @override
  Widget build(BuildContext context) => Stack(alignment: Alignment.center, children: [
        if (pulse) Container(decoration: BoxDecoration(shape: BoxShape.circle, color: color.withValues(alpha: .22))),
        Container(
          width: 32,
          height: 32,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2.5), boxShadow: const [BoxShadow(blurRadius: 6, color: Colors.black26)]),
          child: Icon(icon, color: Colors.white, size: 18),
        ),
      ]);
}

class _LiveDot extends StatefulWidget {
  const _LiveDot();
  @override
  State<_LiveDot> createState() => _LiveDotState();
}

class _LiveDotState extends State<_LiveDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 1))..repeat(reverse: true);
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
        opacity: _c,
        child: Pill(tr('LIVE'), bg: Color(0xFFDCFCE7), fg: Color(0xFF15803D)),
      );
}
