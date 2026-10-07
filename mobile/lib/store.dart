import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show ThemeMode;
import 'package:shared_preferences/shared_preferences.dart';

class CartLine {
  final String productId;
  final List<String> optionIds;
  final String name, optionsLabel;
  final int unitPrice; // display only; the server re-prices everything
  int quantity;
  CartLine(this.productId, this.optionIds, this.name, this.optionsLabel, this.unitPrice, this.quantity);
  String get key => ([productId, ...([...optionIds]..sort())]).join(':');
  Map<String, dynamic> toJson() => {
        'p': productId, 'o': optionIds, 'n': name, 'l': optionsLabel, 'u': unitPrice, 'q': quantity,
      };
  factory CartLine.fromJson(Map j) => CartLine(j['p'], List<String>.from(j['o']), j['n'], j['l'], j['u'], j['q']);
}

/// Cart, profile and recent orders, all kept on the phone. One hotel per cart.
class AppState extends ChangeNotifier {
  late SharedPreferences _p;
  String? hotelSlug, hotelName;
  List<CartLine> lines = [];
  String name = '', phone = '', landmark = '';
  double? lat, lng;
  List<Map<String, dynamic>> recent = []; // {token, code, hotel_name, at}
  List<Map<String, dynamic>> places = []; // {label, lat, lng, landmark}: Home / Work / Other
  String mode = 'delivery'; // order type the checkout opens with
  ThemeMode themeMode = ThemeMode.system;

  Future<void> load() async {
    _p = await SharedPreferences.getInstance();
    try {
      final c = jsonDecode(_p.getString('cart') ?? '{}') as Map;
      hotelSlug = c['slug'];
      hotelName = c['hname'];
      lines = [for (final l in (c['lines'] ?? []) as List) CartLine.fromJson(l)];
      final pr = jsonDecode(_p.getString('profile') ?? '{}') as Map;
      name = pr['name'] ?? '';
      phone = pr['phone'] ?? '';
      landmark = pr['landmark'] ?? '';
      lat = (pr['lat'] as num?)?.toDouble();
      lng = (pr['lng'] as num?)?.toDouble();
      recent = [for (final r in (jsonDecode(_p.getString('recent') ?? '[]') as List)) Map<String, dynamic>.from(r)];
      places = [for (final r in (jsonDecode(_p.getString('places') ?? '[]') as List)) Map<String, dynamic>.from(r)];
      mode = _p.getString('mode') ?? 'delivery';
      themeMode = ThemeMode.values.firstWhere((m) => m.name == _p.getString('theme'), orElse: () => ThemeMode.system);
    } catch (_) {}
  }

  void _save() {
    _p.setString('cart', jsonEncode({'slug': hotelSlug, 'hname': hotelName, 'lines': lines.map((l) => l.toJson()).toList()}));
    _p.setString('profile', jsonEncode({'name': name, 'phone': phone, 'landmark': landmark, 'lat': lat, 'lng': lng}));
    _p.setString('recent', jsonEncode(recent));
    _p.setString('places', jsonEncode(places));
    _p.setString('mode', mode);
    _p.setString('theme', themeMode.name);
    notifyListeners();
  }

  int get count => lines.fold(0, (n, l) => n + l.quantity);
  int get estimate => lines.fold(0, (n, l) => n + l.unitPrice * l.quantity);

  /// False when the cart holds another hotel's items (caller asks to clear first).
  bool add(String slug, String hname, CartLine line) {
    if (hotelSlug != null && hotelSlug != slug && lines.isNotEmpty) return false;
    hotelSlug = slug;
    hotelName = hname;
    final i = lines.indexWhere((l) => l.key == line.key);
    if (i >= 0) {
      lines[i].quantity = (lines[i].quantity + line.quantity).clamp(1, 20);
    } else {
      lines.add(line);
    }
    _save();
    return true;
  }

  void setQty(CartLine l, int q) {
    if (q <= 0) {
      lines.remove(l);
    } else {
      l.quantity = q.clamp(1, 20);
    }
    if (lines.isEmpty) hotelSlug = hotelName = null;
    _save();
  }

  void clear() {
    lines = [];
    hotelSlug = hotelName = null;
    _save();
  }

  void saveProfile(String n, String ph, String lm, double? la, double? ln) {
    name = n; phone = ph; landmark = lm; lat = la; lng = ln;
    _save();
  }

  void remember(String token, String code, String hotel) {
    recent = [
      {'token': token, 'code': code, 'hotel_name': hotel, 'at': DateTime.now().toIso8601String()},
      ...recent.where((r) => r['token'] != token),
    ].take(200).toList();
    _save();
  }

  void setTheme(ThemeMode m) {
    themeMode = m;
    _save();
  }

  void savePlace(String label, double lat, double lng, String landmark) {
    places = [
      {'label': label, 'lat': lat, 'lng': lng, 'landmark': landmark},
      ...places.where((p) => p['label'] != label),
    ];
    _save();
  }

  void removePlace(String label) {
    places = places.where((p) => p['label'] != label).toList();
    _save();
  }

  /// Refill the cart from a past order (/track payload). Prices shown are the old ones until the
  /// server re-quotes at checkout.
  void orderAgain(Map t) {
    lines = [];
    hotelSlug = t['hotel_slug'];
    hotelName = t['hotel_name'];
    for (final i in (t['items'] as List).cast<Map>()) {
      final qty = i['quantity'] as int;
      lines.add(CartLine(
        i['product_id'],
        List<String>.from(i['option_ids'] ?? const []),
        i['name'],
        (i['options'] as List).join(', '),
        ((i['line_total'] as int) / qty).round(),
        qty,
      ));
    }
    mode = t['type'] ?? 'delivery';
    _save();
  }
}
