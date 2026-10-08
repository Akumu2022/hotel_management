import '../api.dart';
import '../util.dart';

/// Letters and digits only, upper case: "kmfb 123c" -> "KMFB123C".
String tidyPlate(String raw) => raw.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');

/// 5 to 10 characters with at least one letter and one digit (the server checks the same).
bool validPlate(String raw) {
  final p = tidyPlate(raw);
  return p.length >= 5 && p.length <= 10 && RegExp(r'\d').hasMatch(p) && RegExp(r'[A-Z]').hasMatch(p);
}

bool twoNames(String s) => s.trim().split(RegExp(r'\s+')).where((w) => w.isNotEmpty).length >= 2;

/// What the rider types on the first sign-up step.
class Applicant {
  String name = '', nationalId = '', phone = '', residence = '';
  String bikePlate = '', bikeDescription = '', kin = '', kinPhone = '', password = '';
}

/// Problems with the details, keyed by the server's field names (empty map = all good).
/// The rules mirror the server and the web sign-up so a rider is never told "no" only after sending.
Map<String, String> checkApplicant(Applicant a, {bool needPassword = true}) {
  final e = <String, String>{};
  if (!twoNames(a.name)) e['name'] = 'Write your full name as on your ID: at least two names.';
  if (!RegExp(r'^\d{6,9}$').hasMatch(a.nationalId.trim())) e['national_id'] = 'ID numbers are 6 to 9 digits.';
  final mine = kenyanNumber(a.phone);
  if (mine == null) e['phone'] = 'Enter a phone number like 0712 345 678.';
  if (a.residence.trim().length < 3) e['residence_area'] = 'Write your estate or area, e.g. Kanduyi.';
  if (!validPlate(a.bikePlate)) e['bike_plate'] = 'Enter the number plate as on the bike, e.g. KMFB 123C.';
  if (a.bikeDescription.trim().length < 3) e['bike_description'] = 'Describe the bike, e.g. Red Boxer 150 with a black box.';
  if (!twoNames(a.kin)) e['next_of_kin'] = 'Write their full name: at least two names.';
  final kin = kenyanNumber(a.kinPhone);
  if (kin == null) {
    e['next_of_kin_phone'] = 'Enter a phone number like 0712 345 678.';
  } else if (kin == mine) {
    e['next_of_kin_phone'] = "Use your next of kin's own number, not yours.";
  }
  if (needPassword && a.password.length < 8) e['password'] = 'Use at least 8 characters.';
  return e;
}

/// Which sign-up step a server field belongs to (to jump back to the right page on an error).
int stepOfField(String field) => switch (field) {
      'id_front' || 'id_back' || 'selfie' || 'logbook' => 2,
      'consent' => 3,
      _ => 1,
    };

/// The login cookie's value from a Set-Cookie header ("chakula_refresh=abc; Path=/; HttpOnly"), or null.
String? refreshFromSetCookie(String? header) {
  if (header == null) return null;
  final m = RegExp(r'chakula_refresh=([^;,\s]+)').firstMatch(header);
  return m?.group(1);
}

enum JobStage { open, toHotel, readyAtHotel, toCustomer, atDoor }

/// Where a job is in the rider's journey, from the server's job record.
JobStage jobStage(Json j) {
  if (j['mine'] != true) return JobStage.open;
  return switch (j['status']) {
    'ready' => JobStage.readyAtHotel,
    'picked_up' => JobStage.toCustomer,
    'on_the_way' => JobStage.atDoor,
    _ => JobStage.toHotel, // accepted, preparing
  };
}

/// 1..4 for the progress bar on a rider's own job (hotel, pick up, on the road, delivered).
int jobStep(JobStage s) => switch (s) {
      JobStage.open => 0,
      JobStage.toHotel => 1,
      JobStage.readyAtHotel => 2,
      JobStage.toCustomer => 3,
      JobStage.atDoor => 3,
    };

/// A job on the road: the rider should be sharing their location more often.
bool onTheRoad(Iterable<Json> jobs) => jobs.any((j) => j['mine'] == true && (j['status'] == 'picked_up' || j['status'] == 'on_the_way'));

/// KES earned from deliveries finished today (local date).
int earnedToday(Iterable<Json> history, DateTime now) {
  var total = 0;
  for (final j in history) {
    if (j['status'] != 'delivered' || j['closed_at'] == null) continue;
    final d = DateTime.parse('${j['closed_at']}').toLocal();
    if (d.year == now.year && d.month == now.month && d.day == now.day) total += (j['rider_fee'] as num).toInt();
  }
  return total;
}

/// Google Maps directions to a point (opens the Maps app on the phone).
Uri directionsTo(double lat, double lng) => Uri.parse('https://www.google.com/maps/dir/?api=1&destination=$lat,$lng&travelmode=driving');

const failReasons = {
  'customer_unreachable': "Customer can't be reached",
  'customer_refused': 'Customer refused the order',
  'wrong_location': 'Wrong or missing location',
  'accident': 'I had an accident',
  'other': 'Something else',
};
