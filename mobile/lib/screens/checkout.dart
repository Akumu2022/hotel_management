import 'dart:math';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../util.dart';
import 'track.dart';

class CheckoutScreen extends StatefulWidget {
  const CheckoutScreen({super.key});
  @override
  State<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends State<CheckoutScreen> {
  late final AppState s = context.read<AppState>();
  late final _name = TextEditingController(text: s.name);
  late final _phone = TextEditingController(text: s.phone);
  late final _landmark = TextEditingController(text: s.landmark);
  final _promo = TextEditingController();
  final _idem = '${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(1 << 32)}';

  String type = 'delivery'; // delivery | pickup | eat_in
  String feeMode = 'included'; // included | cash (delivery only)
  String payment = 'mpesa';
  int arriveIn = 30;
  double? lat, lng;
  Json? quote;
  String? error;
  bool quoting = false, placing = false, locating = false;
  int _quoteSeq = 0;

  @override
  void initState() {
    super.initState();
    lat = s.lat;
    lng = s.lng;
    _requote();
  }

  Json get _base => {
        'hotel_slug': s.hotelSlug,
        'lines': [for (final l in s.lines) {'product_id': l.productId, 'quantity': l.quantity, 'option_ids': l.optionIds}],
        'type': type,
        'rider_fee_mode': type == 'delivery' ? feeMode : 'none',
        if (_promo.text.trim().isNotEmpty) 'promo_code': _promo.text.trim(),
        if (_phone.text.trim().length >= 9) 'phone': _phone.text.trim(),
        if (type == 'delivery' && lat != null) ...{'lat': lat, 'lng': lng},
      };

  Future<void> _requote() async {
    if (s.lines.isEmpty) return;
    final seq = ++_quoteSeq;
    setState(() {
      quoting = true;
      error = null;
    });
    try {
      final q = await apiPost('/quotes', _base) as Json;
      if (seq != _quoteSeq || !mounted) return;
      setState(() {
        quote = q;
        if (type == 'delivery' && feeMode == 'cash' && q['option_b_allowed'] == false) feeMode = 'included';
        if (q['cash_allowed'] != true && payment == 'cash') payment = 'mpesa';
      });
    } on ApiError catch (e) {
      if (seq == _quoteSeq && mounted) setState(() => error = e.message);
    } finally {
      if (seq == _quoteSeq && mounted) setState(() => quoting = false);
    }
  }

  Future<void> _locate() async {
    setState(() => locating = true);
    try {
      var perm = await Geolocator.checkPermission();
      if (perm == LocationPermission.denied) perm = await Geolocator.requestPermission();
      if (perm == LocationPermission.denied || perm == LocationPermission.deniedForever) {
        throw 'Allow location access to drop your delivery pin';
      }
      final p = await Geolocator.getCurrentPosition(locationSettings: const LocationSettings(accuracy: LocationAccuracy.high));
      lat = p.latitude;
      lng = p.longitude;
      await _requote();
    } catch (e) {
      if (mounted) toast(context, '$e');
    } finally {
      if (mounted) setState(() => locating = false);
    }
  }

  Future<void> _place({int? expected}) async {
    final q = quote;
    if (q == null) return;
    if (_name.text.trim().length < 2) return toast(context, 'Enter your name');
    if (_phone.text.trim().length < 9) return toast(context, 'Enter your phone number');
    if (type == 'delivery' && (lat == null || _landmark.text.trim().length < 3)) {
      return toast(context, 'Drop a pin and describe the delivery spot');
    }
    setState(() {
      placing = true;
      error = null;
    });
    try {
      final placed = await apiPost(
        '/orders',
        {
          ..._base,
          'name': _name.text.trim(),
          'phone': _phone.text.trim(),
          'payment_method': payment,
          'landmark': type == 'delivery' ? _landmark.text.trim() : null,
          'arrive_at': type == 'eat_in'
              ? DateTime.now().add(Duration(minutes: arriveIn)).toUtc().toIso8601String()
              : null,
          'expected_total': expected ?? q['till_amount'],
        },
        {'Idempotency-Key': _idem},
      ) as Json;
      s.saveProfile(_name.text.trim(), _phone.text.trim(), _landmark.text.trim(), lat, lng);
      s.remember(placed['tracking_token'], placed['code'], s.hotelName ?? '');
      s.clear();
      if (!mounted) return;
      Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => TrackScreen(token: placed['tracking_token'])));
    } on ApiError catch (e) {
      if (e.code == 'price_changed' && e.extra['quote'] is Map) {
        final nq = Map<String, dynamic>.from(e.extra['quote'] as Map);
        setState(() => quote = nq);
        if (!mounted) return;
        final ok = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: const Text('Price changed'),
            content: Text('The total is now ${kes(nq['till_amount'])}. Continue?'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Continue')),
            ],
          ),
        );
        if (ok == true) return _place(expected: nq['till_amount']);
      } else {
        setState(() => error = e.message);
      }
    } finally {
      if (mounted) setState(() => placing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<AppState>();
    if (cart.lines.isEmpty) {
      return Scaffold(appBar: AppBar(title: const Text('Cart')), body: const Center(child: Text('Your cart is empty')));
    }
    final q = quote;
    return Scaffold(
      appBar: AppBar(title: Text('Cart · ${cart.hotelName ?? ''}')),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        for (final l in cart.lines)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(l.name),
            subtitle: l.optionsLabel.isEmpty ? null : Text(l.optionsLabel),
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: () { cart.setQty(l, l.quantity - 1); _requote(); }),
              Text('${l.quantity}'),
              IconButton(icon: const Icon(Icons.add_circle_outline), onPressed: () { cart.setQty(l, l.quantity + 1); _requote(); }),
            ]),
          ),
        const Divider(),
        SegmentedButton<String>(
          segments: const [
            ButtonSegment(value: 'delivery', label: Text('Delivery'), icon: Icon(Icons.delivery_dining)),
            ButtonSegment(value: 'pickup', label: Text('Pickup'), icon: Icon(Icons.storefront)),
            ButtonSegment(value: 'eat_in', label: Text('Eat in'), icon: Icon(Icons.restaurant)),
          ],
          selected: {type},
          onSelectionChanged: (v) {
            setState(() {
              type = v.first;
              if (type != 'pickup') payment = 'mpesa';
            });
            _requote();
          },
        ),
        const SizedBox(height: 12),
        TextField(controller: _name, decoration: const InputDecoration(labelText: 'Your name', border: OutlineInputBorder())),
        const SizedBox(height: 12),
        TextField(
          controller: _phone,
          keyboardType: TextInputType.phone,
          decoration: const InputDecoration(labelText: 'Phone (07..)', border: OutlineInputBorder()),
          onEditingComplete: _requote,
        ),
        if (type == 'delivery') ...[
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: locating ? null : _locate,
            icon: const Icon(Icons.my_location),
            label: Text(lat == null ? 'Use my current location' : 'Location set · tap to refresh'),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _landmark,
            decoration: const InputDecoration(labelText: 'Describe the spot (gate colour, building)', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 12),
          const Text('Rider fee', style: TextStyle(fontWeight: FontWeight.w600)),
          RadioListTile<String>(
            contentPadding: EdgeInsets.zero,
            value: 'included',
            groupValue: feeMode,
            title: const Text('Pay it now with the order'),
            onChanged: (v) { setState(() => feeMode = v!); _requote(); },
          ),
          RadioListTile<String>(
            contentPadding: EdgeInsets.zero,
            value: 'cash',
            groupValue: feeMode,
            title: const Text('Pay the rider cash at the door'),
            onChanged: q != null && q['option_b_allowed'] == false ? null : (v) { setState(() => feeMode = v!); _requote(); },
          ),
        ],
        if (type == 'eat_in') ...[
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            initialValue: arriveIn,
            decoration: const InputDecoration(labelText: 'I will arrive in', border: OutlineInputBorder()),
            items: [for (final m in [15, 30, 45, 60, 90]) DropdownMenuItem(value: m, child: Text('$m minutes'))],
            onChanged: (v) => setState(() => arriveIn = v ?? 30),
          ),
        ],
        if (type == 'pickup' && q?['cash_allowed'] == true) ...[
          const SizedBox(height: 8),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Pay cash at pickup'),
            value: payment == 'cash',
            onChanged: (v) => setState(() => payment = v ? 'cash' : 'mpesa'),
          ),
        ],
        const SizedBox(height: 12),
        TextField(
          controller: _promo,
          textCapitalization: TextCapitalization.characters,
          decoration: InputDecoration(
            labelText: 'Promo code (optional)',
            border: const OutlineInputBorder(),
            suffixIcon: TextButton(onPressed: _requote, child: const Text('Apply')),
          ),
        ),
        const SizedBox(height: 16),
        if (q != null) _Totals(q, type),
        if (q?['too_far'] == true)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('Too far for delivery (max ${q!['max_delivery_km']} km)', style: const TextStyle(color: Colors.red)),
          ),
        if (q?['promo_error'] != null) Text('${q!['promo_error']}', style: const TextStyle(color: Colors.red)),
        if (error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(error!, style: const TextStyle(color: Colors.red))),
        const SizedBox(height: 16),
        FilledButton(
          onPressed: placing || quoting || q == null || q['too_far'] == true ? null : () => _place(),
          child: placing
              ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
              : Text(q == null ? 'Place order' : (payment == 'cash' ? 'Place order · pay at pickup' : 'Place order · pay ${kes(q['till_amount'])}')),
        ),
        const SizedBox(height: 24),
      ]),
    );
  }
}

class _Totals extends StatelessWidget {
  final Json q;
  final String type;
  const _Totals(this.q, this.type);

  Widget row(String l, num v, {bool bold = false, bool minus = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Text(l, style: TextStyle(fontWeight: bold ? FontWeight.bold : null)),
          const Spacer(),
          Text('${minus ? '-' : ''}${kes(v)}', style: TextStyle(fontWeight: bold ? FontWeight.bold : null)),
        ]),
      );

  @override
  Widget build(BuildContext context) => Column(children: [
        row('Items', q['items_total']),
        if ((q['order_discount'] as int) > 0) row('Discount', q['order_discount'], minus: true),
        if ((q['platform_bonus'] as int) > 0) row('Bonus', q['platform_bonus'], minus: true),
        row('Service fee', q['service_fee']),
        if (type == 'delivery') row(q['rider_fee_estimated'] == true ? 'Rider fee (from)' : 'Rider fee', q['rider_fee']),
        if ((q['rider_fee_cash'] as int) > 0) row('  of which cash to rider', q['rider_fee_cash']),
        const Divider(),
        row('Pay now', q['till_amount'], bold: true),
      ]);
}
