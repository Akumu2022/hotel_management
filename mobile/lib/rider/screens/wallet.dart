import 'dart:math';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../api.dart';
import '../../i18n.dart';
import '../../util.dart';
import '../session.dart';

const _green = Color(0xFF16A34A);

/// Rider wallet: one big number, three plain steps, and what was added. Shown only when the
/// payments module is on (RiderHome checks `enabled` before adding the tab).
class WalletTab extends StatefulWidget {
  const WalletTab({super.key, required this.initial});
  final Json initial;
  @override
  State<WalletTab> createState() => _WalletTabState();
}

class _WalletTabState extends State<WalletTab> {
  late Json _w = widget.initial;

  Future<void> _refresh() async {
    final w = await context.read<RiderSession>().call('GET', '/rider/wallet') as Json;
    if (mounted && w['enabled'] == true) setState(() => _w = w);
  }

  Future<void> _withdraw() async {
    final done = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _WithdrawSheet(w: _w),
    );
    if (done == true) await _refresh();
  }

  String _day(DateTime d) {
    final now = DateTime.now();
    final diff = DateTime(now.year, now.month, now.day).difference(DateTime(d.year, d.month, d.day)).inDays;
    if (diff == 0) return tr('Today');
    if (diff == 1) return tr('Yesterday');
    const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return '${d.day} ${m[d.month - 1]}';
  }

  String _time(DateTime d) {
    final h = d.hour % 12 == 0 ? 12 : d.hour % 12;
    return '$h:${d.minute.toString().padLeft(2, '0')} ${d.hour < 12 ? 'am' : 'pm'}';
  }

  Widget _tile(BuildContext context, IconData icon, Color tint, String big, String small) => Expanded(
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(width: 36, height: 36, decoration: BoxDecoration(color: tint.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)), child: Icon(icon, size: 20, color: tint)),
              const SizedBox(height: 8),
              Text(big, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900)),
              Text(small, style: labelOf(context)),
            ]),
          ),
        ),
      );

  Widget _step(BuildContext context, IconData icon, int n, String title, String text) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          Container(width: 44, height: 44, decoration: BoxDecoration(color: const Color(0xFFFFF1EA), borderRadius: BorderRadius.circular(14)), child: Icon(icon, color: brand)),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('$n. $title', style: const TextStyle(fontWeight: FontWeight.w800)),
              Text(text, style: labelOf(context)),
            ]),
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final available = (_w['available'] as num).toInt();
    final minPayout = (_w['min_payout'] as num).toInt();
    final canWithdraw = _w['can_withdraw'] == true && available >= minPayout;
    final activity = (_w['activity'] as List).cast<Json>();
    final rows = <Widget>[];
    String? lastDay;
    for (final a in activity) {
      final at = DateTime.parse('${a['at']}').toLocal();
      final day = _day(at);
      if (day != lastDay) {
        rows.add(Padding(padding: const EdgeInsets.fromLTRB(4, 12, 0, 6), child: Text(day, style: labelOf(context))));
        lastDay = day;
      }
      rows.add(Card(
        child: ListTile(
          leading: Container(width: 40, height: 40, decoration: const BoxDecoration(color: Color(0xFFECFDF3), shape: BoxShape.circle), child: const Icon(Icons.south_west, color: _green, size: 20)),
          title: Text('${a['hotel'] ?? tr('Delivery')}', style: kItem, maxLines: 1, overflow: TextOverflow.ellipsis),
          subtitle: Text('${a['code'] != null ? '#${a['code']} · ' : ''}${_time(at)}'),
          trailing: Text('+${kes(a['amount'] as num)}', style: const TextStyle(color: _green, fontWeight: FontWeight.w900, fontSize: 16)),
        ),
      ));
    }
    return RefreshIndicator(
      color: brand,
      onRefresh: _refresh,
      child: ListView(padding: const EdgeInsets.all(16), children: [
        if (_w['practice'] == true)
          Container(
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: const Color(0xFFFFF7ED), borderRadius: BorderRadius.circular(16)),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Icon(Icons.science_outlined, color: Color(0xFFC2410C)),
              const SizedBox(width: 10),
              Expanded(child: Text(tr('Practice mode. You can see how your wallet will work. No real money is paid out yet.'), style: const TextStyle(color: Color(0xFFC2410C), fontWeight: FontWeight.w600))),
            ]),
          ),
        Container(
          padding: const EdgeInsets.all(20),
          decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(24)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              const Icon(Icons.account_balance_wallet_outlined, color: Colors.white70, size: 18),
              const SizedBox(width: 6),
              Text(tr('Your money'), style: const TextStyle(color: Colors.white70, fontWeight: FontWeight.w700)),
            ]),
            const SizedBox(height: 4),
            Text(kes(available), style: const TextStyle(color: Colors.white, fontSize: 38, fontWeight: FontWeight.w900)),
            const SizedBox(height: 4),
            Text(
              available > 0
                  ? tr('Goes to your M-Pesa 0•••• {last4} tonight at {time}.', {'last4': _w['mpesa_last4'], 'time': _w['payout_time']})
                  : tr('Finish a delivery and your fee appears here.'),
              style: const TextStyle(color: Colors.white70),
            ),
            const SizedBox(height: 16),
            SizedBox(
              width: double.infinity,
              height: 48,
              child: FilledButton(
                style: FilledButton.styleFrom(backgroundColor: Colors.white, foregroundColor: brand, disabledBackgroundColor: Colors.white54, disabledForegroundColor: brand),
                onPressed: canWithdraw ? _withdraw : null,
                child: Text(
                  _w['can_withdraw'] == true ? (available < minPayout ? tr('Need {amount} to withdraw', {'amount': kes(minPayout)}) : tr('Withdraw now')) : tr('Withdraw now · coming soon'),
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
              ),
            ),
          ]),
        ),
        const SizedBox(height: 12),
        Row(children: [
          _tile(context, Icons.check_circle_outline, _green, kes(_w['paid'] as num), tr('Already sent to M-Pesa')),
          const SizedBox(width: 12),
          _tile(context, Icons.schedule, brand, '${_w['payout_time']}', tr('Daily payout. Minimum {amount}.', {'amount': kes(minPayout)})),
        ]),
        const SizedBox(height: 12),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('How you get paid'), style: kTitle),
              const SizedBox(height: 6),
              _step(context, Icons.key_outlined, 1, tr('Deliver'), tr("Enter the customer's 4-digit code.")),
              _step(context, Icons.account_balance_wallet_outlined, 2, tr('Money lands here'), tr('Your fee shows up at once.')),
              _step(context, Icons.smartphone, 3, tr('Paid to M-Pesa'), tr('Sent to your phone every night.')),
            ]),
          ),
        ),
        const SizedBox(height: 16),
        Text(tr('Money in'), style: kTitle),
        if (activity.isEmpty)
          Padding(
            padding: const EdgeInsets.all(28),
            child: Center(child: Text(tr('Nothing yet. Your first delivery will show up here.'), textAlign: TextAlign.center, style: TextStyle(color: mutedOf(context)))),
          )
        else
          ...rows,
      ]),
    );
  }
}


/// Confirm with your password; a second withdrawal in a day shows its charge first.
class _WithdrawSheet extends StatefulWidget {
  const _WithdrawSheet({required this.w});
  final Json w;
  @override
  State<_WithdrawSheet> createState() => _WithdrawSheetState();
}

class _WithdrawSheetState extends State<_WithdrawSheet> {
  // One key per sheet: a double tap or a retry after a bad connection is still one payout.
  final _key = List.generate(16, (_) => Random.secure().nextInt(256).toRadixString(16).padLeft(2, '0')).join();
  final _password = TextEditingController();
  Json? _charge; // {charge, you_get} once the server says a second withdrawal costs money
  Json? _done;
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _password.dispose();
    super.dispose();
  }

  Future<void> _send(bool accept) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await context.read<RiderSession>().call('POST', '/rider/wallet/withdraw', body: {'password': _password.text, 'accept_charge': accept}, headers: {'Idempotency-Key': _key}) as Json;
      if (mounted) setState(() => _done = r);
    } on ApiError catch (e) {
      if (!mounted) return;
      if (e.code == 'charge_needed') {
        setState(() => _charge = {'charge': e.extra['charge'] ?? widget.w['extra_charge'], 'you_get': e.extra['you_get'] ?? 0});
      } else {
        setState(() => _error = e.message);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final w = widget.w;
    final available = (w['available'] as num).toInt();
    final last4 = '${w['mpesa_last4']}';
    Widget body;
    if (_done != null) {
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(width: 56, height: 56, decoration: BoxDecoration(color: const Color(0xFFECFDF3), borderRadius: BorderRadius.circular(18)), child: const Icon(Icons.check_circle, color: _green, size: 32)),
        const SizedBox(height: 12),
        Text(kes(_done!['amount'] as num), style: const TextStyle(fontSize: 32, fontWeight: FontWeight.w900)),
        Text(tr('is being sent to your M-Pesa 0•••• {last4}. You will get the M-Pesa message in a moment.', {'last4': last4}), style: TextStyle(color: mutedOf(context))),
        const SizedBox(height: 20),
        SizedBox(width: double.infinity, height: 50, child: FilledButton(onPressed: () => Navigator.pop(context, true), child: Text(tr('Done')))),
      ]);
    } else if (_charge != null) {
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: const Color(0xFFFFF7ED), borderRadius: BorderRadius.circular(16)),
          child: Text(tr("You already took money out today, so this one costs {amount}. Waiting until tonight's payout is free.", {'amount': kes(_charge!['charge'] as num)}), style: const TextStyle(color: Color(0xFFC2410C), fontWeight: FontWeight.w600)),
        ),
        const SizedBox(height: 14),
        _line(tr('You have'), kes(available)),
        _line(tr('Charge'), '− ${kes(_charge!['charge'] as num)}'),
        _line(tr('You get'), kes(_charge!['you_get'] as num), strong: true),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w700))),
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: OutlinedButton(onPressed: _busy ? null : () => Navigator.pop(context, false), child: Text(tr('Wait for tonight')))),
          const SizedBox(width: 12),
          Expanded(child: FilledButton(onPressed: _busy ? null : () => _send(true), child: Text(tr('Pay and withdraw')))),
        ]),
      ]);
    } else {
      body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(tr("You'll receive"), style: labelOf(context)),
        Text(kes(available), style: const TextStyle(fontSize: 32, fontWeight: FontWeight.w900)),
        Text(tr('to your M-Pesa 0•••• {last4}. The first one each day is free.', {'last4': last4}), style: TextStyle(color: mutedOf(context))),
        const SizedBox(height: 16),
        TextField(
          controller: _password,
          obscureText: true,
          autofillHints: const [AutofillHints.password],
          onChanged: (_) => setState(() {}),
          decoration: InputDecoration(labelText: tr('Type your password to confirm'), border: const OutlineInputBorder()),
        ),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: const TextStyle(color: Colors.red, fontWeight: FontWeight.w700))),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          height: 50,
          child: FilledButton(
            onPressed: _busy || _password.text.isEmpty ? null : () => _send(false),
            child: _busy ? const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.white)) : Text('${tr('Withdraw now')} · ${kes(available)}'),
          ),
        ),
      ]);
    }
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, MediaQuery.of(context).viewInsets.bottom + 24),
      child: SingleChildScrollView(child: body),
    );
  }

  Widget _line(String k, String v, {bool strong = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(k, style: TextStyle(fontWeight: strong ? FontWeight.w800 : FontWeight.w500)),
          Text(v, style: TextStyle(fontWeight: FontWeight.w800, fontSize: strong ? 18 : 15, color: strong ? _green : null)),
        ]),
      );
}
