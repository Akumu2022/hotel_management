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
                onPressed: canWithdraw ? () {} : null,
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
