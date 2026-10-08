import 'dart:convert';
import 'package:flutter/foundation.dart' show ValueNotifier;
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

/// The address built into the app: --dart-define=API_BASE=https://your.domain/api/v1.
/// 10.0.2.2 is the PC as seen from the Android emulator.
const defaultApiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://10.0.2.2:8000/api/v1');

/// The server this app talks to. It starts as the built-in address and can be changed on the phone
/// (Server address), so a new Wi-Fi address or a move to the real domain never needs a rebuild.
String apiBase = defaultApiBase;

/// "10.10.35.108:8000" / "http://pc:8000" / "https://chakula.co.ke" -> "http://10.10.35.108:8000/api/v1",
/// or null if it can't be an address.
String? normaliseServer(String input) {
  var s = input.trim();
  if (s.isEmpty || s.contains(RegExp(r'\s'))) return null;
  if (s.contains('://') && !s.startsWith('http://') && !s.startsWith('https://')) return null; // ftp:// etc.
  if (!s.startsWith('http://') && !s.startsWith('https://')) s = 'http://$s';
  while (s.endsWith('/')) {
    s = s.substring(0, s.length - 1);
  }
  if (!s.endsWith('/api/v1')) s = '$s/api/v1';
  final u = Uri.tryParse(s);
  if (u == null || u.host.isEmpty || !(u.scheme == 'http' || u.scheme == 'https')) return null;
  return s;
}

/// Use the address saved on this phone, if any. Call once at start-up.
Future<void> loadServerSetting() async {
  final saved = (await SharedPreferences.getInstance()).getString('server_base');
  if (saved != null && saved.isNotEmpty) apiBase = saved;
}

/// Save a new address (null or empty goes back to the built-in one). False if it isn't a valid address.
Future<bool> saveServerSetting(String? input) async {
  final prefs = await SharedPreferences.getInstance();
  if (input == null || input.trim().isEmpty) {
    await prefs.remove('server_base');
    apiBase = defaultApiBase;
    return true;
  }
  final n = normaliseServer(input);
  if (n == null) return false;
  await prefs.setString('server_base', n);
  apiBase = n;
  return true;
}

class ApiError implements Exception {
  final int status;
  final String code;
  final String message;
  final Map<String, dynamic> extra;
  ApiError(this.status, this.code, this.message, [this.extra = const {}]);
  @override
  String toString() => message;
}

typedef Json = Map<String, dynamic>;

Future<dynamic> _send(String method, String path, {Object? body, Map<String, String>? headers}) async {
  final uri = Uri.parse(apiBase + path);
  final h = {'Content-Type': 'application/json', ...?headers};
  try {
    final req = http.Request(method, uri)..headers.addAll(h);
    if (body != null) req.body = jsonEncode(body);
    final res = await http.Response.fromStream(await req.send().timeout(Duration(seconds: path == '/orders' ? 60 : 20)));
    return decodeResponse(res);
  } on ApiError {
    rethrow;
  } catch (_) {
    throw ApiError(0, 'network', 'Cannot reach the server. Check your connection.');
  }
}

/// The JSON body of a good response; an [ApiError] (with the server's code, message and field) otherwise.
dynamic decodeResponse(http.Response res) {
  final text = utf8.decode(res.bodyBytes);
  dynamic data;
  try {
    data = text.isEmpty ? null : jsonDecode(text);
  } catch (_) {
    data = null;
  }
  if (res.statusCode >= 400) {
    final err = (data is Map ? data['error'] : null) as Map? ?? {};
    final extra = Map<String, dynamic>.from(err)..removeWhere((k, _) => k == 'code' || k == 'message');
    throw ApiError(res.statusCode, (err['code'] ?? 'error').toString(), (err['message'] ?? 'Something went wrong').toString(), extra);
  }
  return data;
}

/// Any call with your own headers (the rider app adds its login token this way).
Future<dynamic> apiSend(String method, String path, {Object? body, Map<String, String>? headers}) =>
    _send(method, path, body: body, headers: headers);

/// A form with photos (rider sign-up and ID photos).
Future<dynamic> apiMultipart(
  String path, {
  Map<String, String> fields = const {},
  Map<String, List<int>> files = const {},
  Map<String, String>? headers,
  http.Response? Function(http.Response)? onResponse,
}) async {
  try {
    final req = http.MultipartRequest('POST', Uri.parse(apiBase + path))
      ..headers.addAll(headers ?? {})
      ..fields.addAll(fields);
    files.forEach((k, bytes) => req.files.add(http.MultipartFile.fromBytes(k, bytes, filename: '$k.jpg')));
    final res = await http.Response.fromStream(await req.send().timeout(const Duration(seconds: 90)));
    onResponse?.call(res);
    return decodeResponse(res);
  } on ApiError {
    rethrow;
  } catch (_) {
    throw ApiError(0, 'network', 'Cannot reach the server. Check your connection.');
  }
}

/// True while the screen is showing saved data because the phone is offline.
final offline = ValueNotifier<bool>(false);

// Hotels, menus, offers and config are saved after every good load and used when the phone is
// offline. Orders, payments and tracking are never cached.
bool _cacheable(String p) => p.startsWith('/hotels') || p == '/offers' || p == '/config';

Future<dynamic> apiGet(String path) async {
  if (!_cacheable(path)) return _send('GET', path);
  final prefs = await SharedPreferences.getInstance();
  try {
    final data = await _send('GET', path);
    offline.value = false;
    prefs.setString('c:$path', jsonEncode(data));
    return data;
  } on ApiError catch (e) {
    final raw = prefs.getString('c:$path');
    if (e.status == 0 && raw != null) {
      offline.value = true;
      return jsonDecode(raw);
    }
    rethrow;
  }
}

Future<dynamic> apiPost(String path, [Object? body, Map<String, String>? headers]) =>
    _send('POST', path, body: body ?? {}, headers: headers);
