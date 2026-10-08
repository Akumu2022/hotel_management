import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../api.dart';
import 'logic.dart';

/// The rider's login. The access token lives in memory (15 minutes); the long-lived refresh token is
/// kept on the phone so the rider stays signed in, and is swapped for a new access token on demand.
class RiderSession extends ChangeNotifier {
  String? _access, _refresh;
  Json? me; // /rider/me: the application, bike details and status
  bool booting = true;
  bool mustChangePassword = false;

  bool get signedIn => _refresh != null || _access != null;
  String get status => '${me?['kyc_status'] ?? 'draft'}';

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    _refresh = prefs.getString('rider_refresh');
    if (_refresh != null && await _renew()) {
      try {
        await loadMe();
      } catch (_) {}
    }
    booting = false;
    notifyListeners();
  }

  Map<String, String> get _headers => {if (_access != null) 'Authorization': 'Bearer $_access'};

  Future<void> _store(String? refresh) async {
    _refresh = refresh;
    final prefs = await SharedPreferences.getInstance();
    refresh == null ? await prefs.remove('rider_refresh') : await prefs.setString('rider_refresh', refresh);
  }

  /// Swap the refresh token for a fresh access token. False means "sign in again".
  Future<bool> _renew() async {
    if (_refresh == null) return false;
    try {
      final res = await http
          .post(Uri.parse('$apiBase/auth/refresh'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'refresh_token': _refresh}))
          .timeout(const Duration(seconds: 20));
      final data = decodeResponse(res) as Map;
      _access = data['access_token'];
      final next = refreshFromSetCookie(res.headers['set-cookie']);
      if (next != null) await _store(next);
      return true;
    } on ApiError catch (e) {
      if (e.status == 401) await _clear();
      return false;
    } catch (_) {
      return false; // offline: keep the refresh token and try again later
    }
  }

  Future<void> _clear() async {
    _access = null;
    me = null;
    await _store(null);
  }

  /// A call with the login attached; one silent re-login if the access token has expired.
  Future<dynamic> call(String method, String path, {Object? body}) async {
    try {
      return await apiSend(method, path, body: body, headers: _headers);
    } on ApiError catch (e) {
      if (e.status == 401 && await _renew()) return apiSend(method, path, body: body, headers: _headers);
      if (e.status == 401) notifyListeners(); // signed out
      rethrow;
    }
  }

  Future<dynamic> upload(String path, Map<String, List<int>> files) async {
    try {
      return await apiMultipart(path, files: files, headers: _headers);
    } on ApiError catch (e) {
      if (e.status == 401 && await _renew()) return apiMultipart(path, files: files, headers: _headers);
      rethrow;
    }
  }

  Future<void> signIn(String phone, String password) async {
    final res = await http
        .post(Uri.parse('$apiBase/auth/login'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'phone': phone, 'password': password}))
        .timeout(const Duration(seconds: 20))
        .catchError((_) => throw ApiError(0, 'network', 'Cannot reach the server. Check your connection.'));
    await _adopt(res);
  }

  /// Take the login from a sign-in or sign-up response.
  Future<void> _adopt(http.Response res) async {
    final data = decodeResponse(res) as Map;
    final user = data['user'] as Map;
    if (user['role'] != 'rider') {
      throw ApiError(403, 'not_rider', 'This app is for riders. Customers use the Chakula app; hotels use their web page.');
    }
    _access = data['access_token'];
    mustChangePassword = user['must_change_password'] == true;
    await _store(refreshFromSetCookie(res.headers['set-cookie']));
    try {
      await loadMe();
    } finally {
      notifyListeners();
    }
  }

  /// Sign up: details and photos in one form. Signs the new rider in on success.
  Future<void> apply(Map<String, String> fields, Map<String, List<int>> files) async {
    http.Response? last;
    await apiMultipart('/riders/apply', fields: fields, files: files, onResponse: (r) {
      last = r;
      return null;
    });
    await _adopt(last!);
  }

  Future<Json> loadMe() async {
    me = Map<String, dynamic>.from(await call('GET', '/rider/me') as Map);
    notifyListeners();
    return me!;
  }

  Future<void> setOnline(bool v) async {
    me = Map<String, dynamic>.from(await call('POST', '/rider/online', body: {'online': v}) as Map);
    notifyListeners();
  }

  /// Change the password; the server signs every other session out and hands back fresh tokens.
  Future<void> changePassword(String current, String next) async {
    final res = await http
        .post(Uri.parse('$apiBase/auth/change-password'),
            headers: {'Content-Type': 'application/json', ..._headers}, body: jsonEncode({'current_password': current, 'new_password': next}))
        .timeout(const Duration(seconds: 20))
        .catchError((_) => throw ApiError(0, 'network', 'Cannot reach the server. Check your connection.'));
    final data = decodeResponse(res) as Map;
    _access = data['access_token'];
    await _store(refreshFromSetCookie(res.headers['set-cookie']) ?? _refresh);
    mustChangePassword = false;
    notifyListeners();
  }

  Future<void> signOut() async {
    try {
      await apiSend('POST', '/auth/logout', body: {'refresh_token': _refresh}, headers: _headers);
    } catch (_) {}
    mustChangePassword = false;
    await _clear();
    notifyListeners();
  }
}
