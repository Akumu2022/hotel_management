import 'dart:convert';
import 'package:http/http.dart' as http;

/// Set with --dart-define=API_BASE=https://your.domain/api/v1 for real builds.
/// 10.0.2.2 is the host machine as seen from the Android emulator.
const apiBase = String.fromEnvironment('API_BASE', defaultValue: 'http://10.0.2.2:8000/api/v1');

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
    final res = await http.Response.fromStream(await req.send().timeout(const Duration(seconds: 20)));
    final text = utf8.decode(res.bodyBytes);
    final data = text.isEmpty ? null : jsonDecode(text);
    if (res.statusCode >= 400) {
      final err = (data is Map ? data['error'] : null) as Map? ?? {};
      final extra = Map<String, dynamic>.from(err)..removeWhere((k, _) => k == 'code' || k == 'message');
      throw ApiError(res.statusCode, (err['code'] ?? 'error').toString(),
          (err['message'] ?? 'Something went wrong').toString(), extra);
    }
    return data;
  } on ApiError {
    rethrow;
  } catch (_) {
    throw ApiError(0, 'network', 'Cannot reach the server. Check your connection.');
  }
}

Future<dynamic> apiGet(String path) => _send('GET', path);
Future<dynamic> apiPost(String path, [Object? body, Map<String, String>? headers]) =>
    _send('POST', path, body: body ?? {}, headers: headers);
