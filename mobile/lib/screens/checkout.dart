import 'dart:convert';
import 'dart:math';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../i18n.dart';
import '../util.dart';
import 'package:latlong2/latlong.dart';
import 'pin_picker.dart';
import 'shell.dart';
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

  late String type = s.mode; // delivery | pickup | eat_in
  String feeMode = 'cash'; // always cash: the customer pays the rider directly (hotels never handle rider money)
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
        throw tr('Allow location access to drop your delivery pin');
      }
      final p = await Geolocator.getCurrentPosition(locationSettings: const LocationSettings(accuracy: LocationAccuracy.high))
          .timeout(const Duration(seconds: 15), onTimeout: () => throw tr('Could not get your location. Turn on GPS and try again'));
      lat = p.latitude;
      lng = p.longitude;
      await _requote();
    } catch (e) {
      if (mounted) toast(context, '$e');
    } finally {
      if (mounted) setState(() => locating = false);
    }
  }

  Future<void> _pickOnMap() async {
    final picked = await Navigator.push<LatLng>(
      context,
      MaterialPageRoute(builder: (_) => PinPickerScreen(start: lat == null ? null : LatLng(lat!, lng!), hotelSlug: s.hotelSlug)),
    );
    if (picked == null || !mounted) return;
    setState(() {
      lat = picked.latitude;
      lng = picked.longitude;
    });
    _requote();
  }

  Future<void> _place({int? expected}) async {
    final q = quote;
    if (q == null) return;
    if (_name.text.trim().length < 2) return toast(context, tr('Enter your name'));
    if (_phone.text.trim().length < 9) return toast(context, tr('Enter your phone number'));
    if (type == 'delivery' && (lat == null || _landmark.text.trim().length < 3)) {
      return toast(context, tr('Drop a pin and describe the delivery spot'));
    }
    setState(() {
      placing = true;
      error = null;
    });
    try {
      // The same checkout (same cart, details and total) keeps the same key, even after leaving the
      // screen or a timeout, so a retry returns the first order instead of creating a second one.
      final base = {
        ..._base,
        'name': _name.text.trim(),
        'phone': _phone.text.trim(),
        'payment_method': payment,
        'landmark': type == 'delivery' ? _landmark.text.trim() : null,
        'expected_total': expected ?? q['till_amount'],
      };
      final sig = jsonEncode(base);
      var pend = s.pending;
      if (pend == null || pend['sig'] != sig) {
        pend = {
          'sig': sig,
          'key': '${DateTime.now().microsecondsSinceEpoch}-${Random().nextInt(0x7fffffff)}',
          'arrive': type == 'eat_in' ? DateTime.now().add(Duration(minutes: arriveIn)).toUtc().toIso8601String() : null,
        };
        s.setPending(pend);
      }
      final placed = await apiPost('/orders', {...base, 'arrive_at': pend['arrive']}, {'Idempotency-Key': '${pend['key']}'}) as Json;
      s.setPending(null);
      s.saveProfile(_name.text.trim(), _phone.text.trim(), _landmark.text.trim(), lat, lng);
      s.remember(placed['tracking_token'], placed['code'], s.hotelName ?? '');
      s.clear();
      if (!mounted) return;
      tabIndex.value = 0; // back from the order page lands on Home, like the web
      Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => TrackScreen(token: placed['tracking_token'])), (r) => r.isFirst);
    } on ApiError catch (e) {
      if (e.code == 'price_changed' && e.extra['quote'] is Map) {
        final nq = Map<String, dynamic>.from(e.extra['quote'] as Map);
        setState(() => quote = nq);
        if (!mounted) return;
        final ok = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            title: Text(tr('Price changed')),
            content: Text(tr('The total is now {amount}. Continue?', {'amount': kes(nq['till_amount'])})),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
              FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Continue'))),
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
      return Scaffold(
        appBar: AppBar(title: Text(tr('Cart'), style: TextStyle(fontWeight: FontWeight.w800)), actions: [if (Navigator.canPop(context)) IconButton(icon: const Icon(Icons.home_outlined), onPressed: () => goHome(context))]),
        body: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('🧺', style: TextStyle(fontSize: 56)),
            const SizedBox(height: 8),
            Text(tr('Your cart is empty'), style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 64, vertical: 16),
              child: OutlinedButton(onPressed: () => goHome(context), child: Text(tr('Browse hotels'))),
            ),
          ]),
        ),
      );
    }
    final q = quote;
    return Scaffold(
      appBar: AppBar(
        title: Text('${tr('Cart')} · ${cart.hotelName ?? ''}', style: const TextStyle(fontWeight: FontWeight.w800)),
        actions: [if (Navigator.canPop(context)) IconButton(icon: const Icon(Icons.home_outlined), tooltip: tr('Home'), onPressed: () => goHome(context))],
        bottom: quoting || locating ? const PreferredSize(preferredSize: Size.fromHeight(3), child: LinearProgressIndicator(minHeight: 3)) : null,
      ),
      // Always visible, never hidden behind the phone's gesture bar or the bottom nav.
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
          child: FilledButton(
            style: fullWidthFilled,
            onPressed: placing || quoting || q == null || q['too_far'] == true ? null : () => _place(),
            child: placing
                ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                : Text(q == null ? tr('Place order') : tr('Place order · pay {amount}', {'amount': kes(q['till_amount'])})),
          ),
        ),
      ),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        for (final l in cart.lines)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(l.name, style: kItem),
            subtitle: l.optionsLabel.isEmpty ? null : Text(l.optionsLabel, style: labelOf(context)),
            trailing: Row(mainAxisSize: MainAxisSize.min, children: [
              IconButton(icon: const Icon(Icons.remove_circle_outline), onPressed: () { cart.setQty(l, l.quantity - 1); _requote(); }),
              Text('${l.quantity}'),
              IconButton(icon: Icon(Icons.add_circle_outline), onPressed: () { cart.setQty(l, l.quantity + 1); _requote(); }),
            ]),
          ),
        Divider(),
        SegmentedButton<String>(
          segments: [
            ButtonSegment(value: 'delivery', label: Text(tr('Delivery')), icon: Icon(Icons.delivery_dining)),
            ButtonSegment(value: 'pickup', label: Text(tr('Pickup')), icon: Icon(Icons.storefront)),
            ButtonSegment(value: 'eat_in', label: Text(tr('Eat in')), icon: Icon(Icons.restaurant)),
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
        TextField(controller: _name, decoration: InputDecoration(labelText: tr('Your name'), border: OutlineInputBorder())),
        const SizedBox(height: 12),
        TextField(
          controller: _phone,
          keyboardType: TextInputType.phone,
          decoration: InputDecoration(labelText: tr('Phone (07..)'), border: OutlineInputBorder()),
          onEditingComplete: _requote,
        ),
        if (type == 'delivery') ...[
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: OutlinedButton.icon(
                onPressed: locating ? null : _locate,
                icon: locating ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.my_location, size: 20),
                label: Text(tr('My location')),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _pickOnMap,
                icon: const Icon(Icons.map_outlined, size: 20),
                label: Text(tr('Pick on map')),
              ),
            ),
          ]),
          if (lat != null)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(children: [
                const Icon(Icons.check_circle, size: 16, color: Color(0xFF16A34A)),
                const SizedBox(width: 6),
                Text(tr('Delivery spot set'), style: labelOf(context).copyWith(color: const Color(0xFF16A34A))),
              ]),
            ),
          if (s.places.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(spacing: 8, children: [
              for (final p in s.places)
                InputChip(
                  avatar: Icon(p['label'] == 'Home' ? Icons.home_outlined : p['label'] == 'Work' ? Icons.work_outline : Icons.place_outlined, size: 18),
                  label: Text(tr('${p['label']}')),
                  onPressed: () {
                    setState(() {
                      lat = (p['lat'] as num).toDouble();
                      lng = (p['lng'] as num).toDouble();
                      _landmark.text = '${p['landmark']}';
                    });
                    _requote();
                  },
                  onDeleted: () => setState(() => s.removePlace('${p['label']}')),
                ),
            ]),
          ],
          const SizedBox(height: 12),
          TextField(
            controller: _landmark,
            decoration: InputDecoration(labelText: tr('Describe the spot (gate colour, building)'), border: OutlineInputBorder()),
          ),
          if (lat != null && _landmark.text.trim().length >= 3) ...[
            const SizedBox(height: 8),
            Row(children: [
              Text(tr('Save this spot as'), style: TextStyle(color: mutedOf(context), fontSize: 13)),
              const SizedBox(width: 8),
              for (final l in const ['Home', 'Work', 'Other'])
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ActionChip(
                    label: Text(tr(l)),
                    visualDensity: VisualDensity.compact,
                    onPressed: () {
                      setState(() => s.savePlace(l, lat!, lng!, _landmark.text.trim()));
                      toast(context, tr('Saved as {label}', {'label': tr(l)}));
                    },
                  ),
                ),
            ]),
          ],
          const SizedBox(height: 12),
          Text(tr('Rider fee'), style: kSection),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: q != null && q['option_b_allowed'] == false ? const Color(0xFFFEF2F2) : const Color(0xFFDCFCE7), borderRadius: BorderRadius.circular(12)),
            child: Text(
              q != null && q['option_b_allowed'] == false
                  ? tr('Delivery is not available for this number. Choose pickup or contact support.')
                  : tr('You pay the rider the delivery fee yourself when the food arrives. The hotel never handles it.'),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        ],
        if (type == 'eat_in') ...[
          const SizedBox(height: 12),
          DropdownButtonFormField<int>(
            initialValue: arriveIn,
            decoration: InputDecoration(labelText: tr('I will arrive in'), border: OutlineInputBorder()),
            items: [for (final m in [15, 30, 45, 60, 90]) DropdownMenuItem(value: m, child: Text(tr('{n} minutes', {'n': m})))],
            onChanged: (v) => setState(() => arriveIn = v ?? 30),
          ),
        ],
        if (type != 'delivery') ...[
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: const Color(0xFFDCFCE7), borderRadius: BorderRadius.circular(14)),
            child: Row(children: [
              const Icon(Icons.phone_android, size: 20, color: Color(0xFF15803D)),
              const SizedBox(width: 10),
              Expanded(child: Text(tr('Pay with M-Pesa first. The hotel starts cooking once your payment arrives.'), style: const TextStyle(color: Color(0xFF15803D), fontWeight: FontWeight.w600, fontSize: 13))),
            ]),
          ),
        ],
        const SizedBox(height: 12),
        TextField(
          controller: _promo,
          textCapitalization: TextCapitalization.characters,
          decoration: InputDecoration(
            labelText: tr('Promo code (optional)'),
            border: const OutlineInputBorder(),
            suffixIcon: TextButton(onPressed: _requote, child: Text(tr('Apply'))),
          ),
        ),
        const SizedBox(height: 16),
        if (q != null) _Totals(q, type),
        if (q?['too_far'] == true)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(tr('Too far for delivery: {km} km away (max {max} km). Choose Pickup or a closer spot.', {'km': q!['distance_km'], 'max': q['max_delivery_km']}), style: const TextStyle(color: Colors.red)),
          ),
        if (q?['promo_error'] != null) Text('${q!['promo_error']}', style: const TextStyle(color: Colors.red)),
        if (error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(error!, style: const TextStyle(color: Colors.red))),
        HelpButton('Hello Chakula, I need help ordering from ${cart.hotelName ?? "a hotel"}.'),
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
          Text(l, style: bold ? kSection : kBody),
          const Spacer(),
          Text('${minus ? '-' : ''}${kes(v)}', style: bold ? kTitle.copyWith(color: brand) : kBody.copyWith(fontWeight: FontWeight.w600)),
        ]),
      );

  @override
  Widget build(BuildContext context) => Column(children: [
        row('Items', q['items_total']),
        if ((q['order_discount'] as int) > 0) row('Discount', q['order_discount'], minus: true),
        if ((q['platform_bonus'] as int) > 0) row('Bonus', q['platform_bonus'], minus: true),
        row('Service fee', q['service_fee']),
        if (type == 'delivery') row(q['rider_fee_estimated'] == true ? 'Rider fee, you pay the rider (from)' : 'Rider fee, you pay the rider', q['rider_fee']),
        const Divider(),
        row('Pay now', q['till_amount'], bold: true),
      ]);
}
