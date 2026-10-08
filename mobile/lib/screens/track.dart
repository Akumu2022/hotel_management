import 'dart:async';
import 'package:flutter/services.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../i18n.dart';
import '../util.dart';
import 'rider_map.dart';
import 'safety.dart';
import 'shell.dart';

const _labels = {
  'awaiting_payment': 'Waiting for payment',
  'checking_payment': 'Checking payment',
  'paid': 'Payment received',
  'accepted': 'Hotel accepted',
  'preparing': 'Being prepared',
  'ready': 'Ready',
  'picked_up': 'Rider picked up',
  'on_the_way': 'On the way',
  'delivered': 'Delivered',
  'collected': 'Collected',
  'expired': 'Expired: not paid in time',
  'rejected': "The hotel couldn't take this order",
  'cancelled': 'Order cancelled',
  'failed_delivery': 'Delivery failed',
};
const _deliverySteps = ['paid', 'accepted', 'preparing', 'ready', 'picked_up', 'on_the_way', 'delivered'];
const _pickupSteps = ['paid', 'accepted', 'preparing', 'ready', 'collected'];
const _ended = ['expired', 'rejected', 'cancelled', 'failed_delivery'];

class TrackScreen extends StatefulWidget {
  final String token;
  const TrackScreen({super.key, required this.token});
  @override
  State<TrackScreen> createState() => _TrackScreenState();
}

class _TrackScreenState extends State<TrackScreen> {
  Json? t;
  String? error;
  Timer? _timer;
  final _code = TextEditingController();
  bool busy = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = await apiGet('/track/${widget.token}') as Json;
      final before = t?['status'];
      if (mounted) setState(() { t = r; error = null; });
      // Tell the customer when their order moves along while they are looking at it.
      if (before != null && before != r['status'] && mounted) {
        HapticFeedback.mediumImpact();
        toast(context, tr(_labels[r['status']] ?? '${r['status']}'));
      }
    } on ApiError catch (e) {
      if (mounted && t == null) setState(() => error = e.message);
    }
  }

  Future<void> _act(Future<dynamic> Function() f, {String? ok}) async {
    setState(() => busy = true);
    try {
      final r = await f();
      if (!mounted) return;
      final msg = r is Map && r['message'] != null ? '${r['message']}' : ok;
      if (msg != null) toast(context, msg);
      await _load();
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _rate() async {
    final needsRider = t!['type'] == 'delivery' && t!['rider_name'] != null;
    var hotel = 5, rider = 5;
    final comment = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, set) => AlertDialog(
          title: Text(tr('Rate your order')),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            _Stars(tr('Hotel'), hotel, (v) => set(() => hotel = v)),
            if (needsRider) _Stars(tr('Rider'), rider, (v) => set(() => rider = v)),
            TextField(controller: comment, decoration: InputDecoration(hintText: tr('Comment (optional)'))),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Later'))),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Send'))),
          ],
        ),
      ),
    );
    if (ok == true) {
      await _act(() => apiPost('/track/${widget.token}/rating', {
            'hotel_stars': hotel,
            'rider_stars': needsRider ? rider : null,
            'comment': comment.text.trim().isEmpty ? null : comment.text.trim(),
          }), ok: tr('Thanks for rating!'));
      // Rated = order finished: back to the hotels after a moment to read the thanks.
      Future.delayed(const Duration(milliseconds: 1800), () {
        if (mounted) goHome(context);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final o = t;
    if (o == null) {
      return Scaffold(
        appBar: AppBar(title: Text(tr('Your order')), actions: [_homeButton(context)]),
        body: error != null
            ? Center(child: Text(error!))
            : ListView(padding: const EdgeInsets.all(16), children: const [Skel(40), SizedBox(height: 14), Skel(90), SizedBox(height: 14), Skel(200)]),
      );
    }
    final status = o['status'] as String;
    final steps = o['type'] == 'delivery' ? _deliverySteps : _pickupSteps;
    final idx = steps.indexOf(status);
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('Order {code}', {'code': o['code']})),
        actions: [_homeButton(context)],
        bottom: busy ? const PreferredSize(preferredSize: Size.fromHeight(3), child: LinearProgressIndicator(minHeight: 3)) : null,
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(padding: const EdgeInsets.all(16), children: [
          Text(o['hotel_name'], style: kTitle),
          const SizedBox(height: 4),
          const SizedBox(height: 4),
          Wrap(children: [
            Pill(tr(_labels[status] ?? status),
                bg: _ended.contains(status) ? const Color(0xFFFEE2E2) : const Color(0xFFFFE4D6),
                fg: _ended.contains(status) ? const Color(0xFFB91C1C) : brand),
          ]),
          if (!_ended.contains(status) && idx >= 0) _progress(steps, idx),
          if (o['reason'] != null) Text('${o['reason']}'),
          const SizedBox(height: 12),
          if (status == 'awaiting_payment') _payCard(o),
          if (status == 'checking_payment')
            Card(
              child: ListTile(
                leading: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5)),
                title: Text(tr('We are checking your payment')),
              ),
            ),
          if (o['delivery_code'] != null && (status == 'on_the_way' || status == 'picked_up'))
            Card(
              child: ListTile(
                leading: const Icon(Icons.pin),
                title: Text(tr('Give the rider this code: {code}', {'code': o['delivery_code']})),
              ),
            ),
          if (o['type'] != 'delivery' && o['delivery_code'] != null && !_ended.contains(status) && !const ['awaiting_payment', 'checking_payment', 'collected'].contains(status))
            _pinCard(o),
          if (o['live'] != null && o['rider_name'] != null && (status == 'on_the_way' || status == 'picked_up'))
            Padding(padding: const EdgeInsets.only(bottom: 12), child: RiderMap(token: widget.token, live: o['live'] as Json, riderName: '${o['rider_name']}')),
          if (o['rider_name'] != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(children: [
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: const Icon(Icons.delivery_dining),
                    title: Text('${o['rider_name']}', style: kItem),
                    subtitle: Text(tr('Your rider')),
                  ),
                  ContactRow(o['rider_phone'] as String?, message: 'Hi ${o['rider_name']}, about my order #${o['code']}.'),
                ]),
              ),
            ),
          if (o['fee_question'] == true)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(children: [
                  Text(tr('Did you pay the rider the delivery fee in cash?')),
                  Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                    TextButton(onPressed: busy ? null : () => _act(() => apiPost('/track/${widget.token}/rider-fee-answer', {'paid': false})), child: Text(tr('No'))),
                    FilledButton(onPressed: busy ? null : () => _act(() => apiPost('/track/${widget.token}/rider-fee-answer', {'paid': true})), child: Text(tr('Yes'))),
                  ]),
                ]),
              ),
            ),
          if (!_ended.contains(status) && idx >= 0)
            for (var i = 0; i < steps.length; i++)
              ListTile(
                dense: true,
                leading: Icon(i <= idx ? Icons.check_circle : Icons.radio_button_unchecked, color: i <= idx ? Colors.green : Colors.grey),
                title: Text(tr(_labels[steps[i]]!), style: TextStyle(fontWeight: i == idx ? FontWeight.bold : null)),
              ),
          const Divider(),
          for (final i in (o['items'] as List).cast<Json>())
            ListTile(
              dense: true,
              title: Text('${i['quantity']}× ${i['name']}', style: kItem),
              subtitle: (i['options'] as List).isEmpty ? null : Text((i['options'] as List).join(', ')),
              trailing: Text(kes(i['line_total'])),
            ),
          ListTile(dense: true, title: Text(tr('Total paid via till')), trailing: Text(kes(o['till_amount']), style: const TextStyle(fontWeight: FontWeight.bold))),
          if ((o['rider_fee_cash'] as int) > 0)
            ListTile(dense: true, title: Text(tr('Cash to rider')), trailing: Text(kes(o['rider_fee_cash']))),
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: ContactRow(o['hotel_phone'] as String?, message: 'Hello ${o['hotel_name']}, about my order #${o['code']}.'),
          ),
          const SizedBox(height: 8),
          if (o['can_cancel'] == true)
            OutlinedButton(
              onPressed: busy ? null : () => _act(() => apiPost('/track/${widget.token}/cancel'), ok: tr('Order cancelled')),
              child: Text(tr('Cancel order')),
            ),
          if (o['can_rate'] == true && o['rated'] != true) FilledButton(style: fullWidthFilled, onPressed: _rate, child: Text(tr('Rate this order'))),
          if ((o['items'] as List).isNotEmpty && o['hotel_slug'] != null && (status == 'delivered' || status == 'collected' || _ended.contains(status)))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: OutlinedButton.icon(
                icon: const Icon(Icons.replay),
                label: Text(tr('Order again')),
                onPressed: () {
                  context.read<AppState>().orderAgain(o);
                  tabIndex.value = 2; // Cart tab
                  Navigator.of(context).popUntil((r) => r.isFirst);
                  toast(context, tr('Your order is back in the basket'));
                },
              ),
            ),
          HelpButton('Hello Chakula, I need help with order #${o['code']} from ${o['hotel_name']}.'),
          const SizedBox(height: 24),
        ]),
      ),
    );
  }

/// Pickup and eat-in: the customer reads this PIN to the hotel, who only hand over the food once
  /// it matches. It stops someone else collecting your order.
  Widget _pinCard(Json o) {
    final eatIn = o['type'] == 'eat_in';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Icon(Icons.lock_outline, color: brand),
            const SizedBox(width: 8),
            Text(tr(eatIn ? 'Eat-in PIN' : 'Pickup PIN'), style: kSection),
          ]),
          const SizedBox(height: 4),
          Text(tr('Tell the hotel this PIN when you get there. They only hand over your food once you give it.'), style: labelOf(context)),
          const SizedBox(height: 12),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            for (final d in '${o['delivery_code']}'.split(''))
              Container(
                width: 52,
                height: 64,
                margin: const EdgeInsets.symmetric(horizontal: 5),
                alignment: Alignment.center,
                decoration: BoxDecoration(color: const Color(0xFFFFE4D6), borderRadius: BorderRadius.circular(14)),
                child: Text(d, style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w900, color: brand)),
              ),
          ]),
        ]),
      ),
    );
  }

  Widget _homeButton(BuildContext context) => IconButton(icon: const Icon(Icons.home_outlined), tooltip: tr('Home'), onPressed: () => goHome(context));

  /// "Step 3 of 7" with a bar that fills as the order moves along.
  Widget _progress(List<String> steps, int idx) => Padding(
        padding: const EdgeInsets.only(top: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tr('Step {n} of {total}', {'n': idx + 1, 'total': steps.length}), style: TextStyle(color: mutedOf(context), fontSize: 13, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          TweenAnimationBuilder<double>(
            tween: Tween(end: (idx + 1) / steps.length),
            duration: const Duration(milliseconds: 600),
            builder: (_, v, __) => ClipRRect(borderRadius: BorderRadius.circular(99), child: LinearProgressIndicator(value: v, minHeight: 8, backgroundColor: const Color(0xFFFFE4D6))),
          ),
        ]),
      );

  Widget _payCard(Json o) {
    final cs = Theme.of(context).colorScheme;
    final till = '${o['till_number']}';
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
          child: Row(children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(color: const Color(0xFF16A34A), borderRadius: BorderRadius.circular(14)),
              child: const Icon(Icons.smartphone, color: Colors.white),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(tr('Pay with M-Pesa'), style: labelOf(context)),
                Text(kes(o['till_amount']), style: kTitle.copyWith(fontSize: 26)),
              ]),
            ),
            if (o['expires_at'] != null) _Countdown(DateTime.parse('${o['expires_at']}')),
          ]),
        ),
        const Divider(height: 1),
        Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(16)),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(tr('BUY GOODS TILL NUMBER'), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: mutedOf(context), letterSpacing: .6)),
                    const SizedBox(height: 2),
                    Text(till, style: const TextStyle(fontSize: 32, fontWeight: FontWeight.w900, letterSpacing: 3)),
                    o['till_name'] != null
                        ? Text(tr('M-Pesa will show: {name}', {'name': o['till_name']}), style: kItem.copyWith(fontSize: 14))
                        : Text('${o['hotel_name']}', style: labelOf(context)),
                  ]),
                ),
                IconButton.filledTonal(
                  tooltip: tr('Copy till number'),
                  icon: const Icon(Icons.copy_rounded),
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: till));
                    toast(context, tr('Till number copied'));
                  },
                ),
              ]),
            ),
            if (o['till_name'] != null)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(top: 10),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: const Color(0xFFDCFCE7), borderRadius: BorderRadius.circular(14)),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Icon(Icons.shield_outlined, size: 20, color: Color(0xFF15803D)),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      tr("Before you enter your PIN, check that M-Pesa shows this name. If it shows a different name, don't pay: call the hotel."),
                      style: const TextStyle(color: Color(0xFF15803D), fontWeight: FontWeight.w600, fontSize: 13),
                    ),
                  ),
                ]),
              ),
            TextButton(onPressed: () => showSafetySheet(context), child: Text(tr('How we keep your money safe'))),
            const SizedBox(height: 4),
            for (final (i, step) in [tr('Open M-Pesa → Lipa na M-Pesa → Buy Goods and Services'), tr('Till {till}, amount {amount} exactly', {'till': till, 'amount': kes(o['till_amount'])}), tr('Enter your PIN and keep the M-Pesa message')].indexed)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Container(
                    width: 24,
                    height: 24,
                    alignment: Alignment.center,
                    decoration: const BoxDecoration(color: brand, shape: BoxShape.circle),
                    child: Text('${i + 1}', style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w800)),
                  ),
                  const SizedBox(width: 10),
                  Expanded(child: Text(step, style: kBody)),
                ]),
              ),
            const SizedBox(height: 6),
            Text(tr('Then paste the M-Pesa transaction code'), style: kSection),
            const SizedBox(height: 8),
            TextField(
              controller: _code,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(hintText: tr('e.g. SJK3ABC123')),
            ),
            const SizedBox(height: 10),
            FilledButton(
              style: fullWidthFilled,
              onPressed: busy ? null : () => _act(() => apiPost('/track/${widget.token}/payment-code', {'code': _code.text.trim().toUpperCase()})),
              child: busy ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)) : Text(tr('Submit code')),
            ),
            const SizedBox(height: 10),
            Text(tr('This page updates by itself once the hotel confirms your payment.'), style: labelOf(context)),
            if ((o['rider_fee_cash'] as int) > 0)
              Container(
                width: double.infinity,
                margin: const EdgeInsets.only(top: 12),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: const Color(0xFFFEF3C7), borderRadius: BorderRadius.circular(12)),
                child: Text(tr('Also have {amount} cash ready for the rider.', {'amount': kes(o['rider_fee_cash'])}), style: const TextStyle(color: Color(0xFF92400E), fontWeight: FontWeight.w700)),
              ),
          ]),
        ),
      ]),
    );
  }
}

/// Time left to pay, ticking every second; turns red in the last 5 minutes.
class _Countdown extends StatefulWidget {
  final DateTime end;
  const _Countdown(this.end);
  @override
  State<_Countdown> createState() => _CountdownState();
}

class _CountdownState extends State<_Countdown> {
  late final Timer _t = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
  @override
  void dispose() {
    _t.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    _t; // start ticking
    final left = widget.end.difference(DateTime.now());
    if (left.isNegative) return const SizedBox.shrink();
    final urgent = left.inMinutes < 5;
    final text = '${left.inMinutes.toString().padLeft(2, '0')}:${(left.inSeconds % 60).toString().padLeft(2, '0')}';
    return Pill(text, icon: Icons.timer_outlined, bg: urgent ? const Color(0xFFFEE2E2) : null, fg: urgent ? const Color(0xFFB91C1C) : null);
  }
}

class _Stars extends StatelessWidget {
  final String label;
  final int value;
  final ValueChanged<int> onChanged;
  const _Stars(this.label, this.value, this.onChanged);
  @override
  Widget build(BuildContext context) => Row(children: [
        SizedBox(width: 56, child: Text(label)),
        for (var i = 1; i <= 5; i++)
          IconButton(
            visualDensity: VisualDensity.compact,
            onPressed: () => onChanged(i),
            icon: Icon(i <= value ? Icons.star : Icons.star_border, color: Colors.amber),
          ),
      ]);
}
