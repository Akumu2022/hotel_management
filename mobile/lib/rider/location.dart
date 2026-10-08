import 'dart:async';
import 'package:geolocator/geolocator.dart';
import 'session.dart';

/// Shares the rider's position with dispatch while they are online: every ~30 s, every ~10 s while a
/// delivery is on the road. An Android foreground service (with a notification) keeps it going when
/// the screen is locked or another app is in front, which a web page cannot do.
class LocationReporter {
  final RiderSession session;
  LocationReporter(this.session);

  StreamSubscription<Position>? _sub;
  Timer? _tick;
  Position? _pos;
  DateTime _sentAt = DateTime.fromMillisecondsSinceEpoch(0);
  bool onTheRoad = false;

  bool get running => _sub != null;

  /// Starts sharing. Returns a message to show the rider if it could not start, else null.
  Future<String?> start() async {
    if (running) return null;
    if (!await Geolocator.isLocationServiceEnabled()) return 'Turn on your phone\'s location (GPS) to take jobs.';
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
    if (perm == LocationPermission.denied) return 'Allow location so dispatch and customers can see where you are.';
    if (perm == LocationPermission.deniedForever) return 'Location is blocked for this app. Allow it in the phone settings.';
    _sub = Geolocator.getPositionStream(
      locationSettings: AndroidSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 15,
        intervalDuration: const Duration(seconds: 10),
        foregroundNotificationConfig: const ForegroundNotificationConfig(
          notificationTitle: 'Chakula Rider',
          notificationText: "Sharing your location while you're online",
          enableWakeLock: true,
          setOngoing: true,
        ),
      ),
    ).listen((p) {
      _pos = p;
      _maybeSend();
    }, onError: (_) {});
    // The stream can take a while to give its first fix (or never does indoors/on an emulator), so
    // ask for one straight away. Without it customers would see no rider on their map.
    unawaited(_seed());
    // Standing still gives no movement events; resend the last spot so dispatch doesn't think we left.
    _tick = Timer.periodic(const Duration(seconds: 10), (_) => _maybeSend());
    return null;
  }

  Future<void> _seed() async {
    try {
      _pos ??= await Geolocator.getLastKnownPosition();
      _pos ??= await Geolocator.getCurrentPosition(locationSettings: const LocationSettings(accuracy: LocationAccuracy.high, timeLimit: Duration(seconds: 20)));
    } catch (_) {}
    _maybeSend();
  }

  void _maybeSend() {
    final p = _pos;
    if (p == null) return;
    final gap = Duration(seconds: onTheRoad ? 10 : 30);
    if (DateTime.now().difference(_sentAt) < gap) return;
    _sentAt = DateTime.now();
    session.call('POST', '/rider/location', body: {'lat': p.latitude, 'lng': p.longitude, 'accuracy_m': p.accuracy.round().clamp(0, 100000)}).catchError((_) => null);
  }

  Future<void> stop() async {
    await _sub?.cancel();
    _tick?.cancel();
    _sub = null;
    _tick = null;
    _pos = null;
  }
}
