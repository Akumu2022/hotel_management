import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../api.dart';
import '../../i18n.dart';
import '../../util.dart';
import '../session.dart';

const _periods = [('today', 'Today'), ('week', 'This week'), ('month', 'This month'), ('all', 'All time')];

class _Group {
  final String id, label;
  final Color bg, fg;
  const _Group(this.id, this.label, this.bg, this.fg);
}

const _groups = [
  _Group('delivered', 'Delivered', Color(0xFFDCFCE7), Color(0xFF15803D)),
  _Group('waiting', 'Pending pickup', Color(0xFFFEF3C7), Color(0xFFB45309)),
  _Group('on_the_way', 'On the way', Color(0xFFFFE4D6), brand),
  _Group('cancelled', 'Cancelled', Color(0xFFF4F4F5), Color(0xFF62626A)),
  _Group('failed', 'Failed', Color(0xFFFEE2E2), Color(0xFFB91C1C)),
];

_Group _groupOf(String id) => _groups.firstWhere((g) => g.id == id, orElse: () => _groups.last);

String _when(String iso) {
  final d = DateTime.tryParse(iso)?.toLocal();
  if (d == null) return '';
  const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return '${d.day} ${m[d.month - 1]}, ${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

/// Name, photo, status, online and rating.
class RiderProfileCard extends StatelessWidget {
  const RiderProfileCard({super.key});
  @override
  Widget build(BuildContext context) {
    final me = context.watch<RiderSession>().me ?? {};
    final online = me['is_online'] == true;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(children: [
          CircleAvatar(
            radius: 32,
            backgroundColor: const Color(0xFFFFE4D6),
            backgroundImage: me['photo_url'] == null ? null : NetworkImage(absUrl('${me['photo_url']}')),
            child: me['photo_url'] == null ? const Icon(Icons.person, size: 32, color: brand) : null,
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${me['name'] ?? ''}', style: kTitle, maxLines: 1, overflow: TextOverflow.ellipsis),
              Text('${me['phone'] ?? ''}', style: labelOf(context)),
              const SizedBox(height: 6),
              Wrap(spacing: 6, runSpacing: 6, children: [
                Pill(tr('Approved'), bg: const Color(0xFFDCFCE7), fg: const Color(0xFF15803D)),
                Pill(online ? tr('Online') : tr('Offline'), bg: online ? const Color(0xFFDCFCE7) : null, fg: online ? const Color(0xFF15803D) : mutedOf(context)),
                if (me['rating'] != null) Pill('${(me['rating'] as num).toStringAsFixed(1)} (${me['rating_count']})', icon: Icons.star_rounded, bg: const Color(0xFFFEF3C7), fg: const Color(0xFFB45309)),
              ]),
            ]),
          ),
        ]),
      ),
    );
  }
}

/// Period tabs, earned and owed, and outcome tiles. A tapped tile filters the list below.
class OrdersSummaryCard extends StatefulWidget {
  final String period;
  final String? only;
  final ValueChanged<String> onPeriod;
  final ValueChanged<String?> onOnly;
  const OrdersSummaryCard({super.key, required this.period, required this.only, required this.onPeriod, required this.onOnly});
  @override
  State<OrdersSummaryCard> createState() => _OrdersSummaryCardState();
}

class _OrdersSummaryCardState extends State<OrdersSummaryCard> {
  Json? _s;
  int? _owed;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 30), (_) => _load());
  }

  @override
  void didUpdateWidget(OrdersSummaryCard old) {
    super.didUpdateWidget(old);
    if (old.period != widget.period) _load();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final call = context.read<RiderSession>().call;
    final period = widget.period;
    try {
      final s = await call('GET', '/rider/summary?period=$period&limit=1') as Map;
      if (mounted && period == widget.period) setState(() => _s = Map<String, dynamic>.from(s));
      final e = await call('GET', '/rider/earnings') as Map;
      if (mounted) setState(() => _owed = e['owed'] as int?);
    } catch (_) {
      /* keep the last numbers */
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final counts = (_s?['counts'] as Map?) ?? const {};
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(tr('My orders'), style: kSection),
          const SizedBox(height: 10),
          SegmentedButton<String>(
            showSelectedIcon: false,
            style: const ButtonStyle(visualDensity: VisualDensity.compact, padding: WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 4))),
            segments: [for (final p in _periods) ButtonSegment(value: p.$1, label: Text(tr(p.$2), style: const TextStyle(fontSize: 12)))],
            selected: {widget.period},
            onSelectionChanged: (v) => widget.onPeriod(v.first),
          ),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(child: _Money(label: tr('Earned from deliveries'), value: _s == null ? '…' : kes(_s!['earned']), bg: const Color(0xFFDCFCE7), fg: const Color(0xFF15803D))),
            const SizedBox(width: 10),
            Expanded(child: _Money(label: tr('Owed to you'), value: _owed == null ? '…' : kes(_owed!), bg: cs.surfaceContainerHighest, fg: cs.onSurface)),
          ]),
          const SizedBox(height: 10),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final g in _groups)
              _Tile(
                width: (MediaQuery.of(context).size.width - 32 - 32 - 16) / 3,
                count: _s == null ? '–' : '${counts[g.id] ?? 0}',
                label: tr(g.label),
                bg: g.bg,
                fg: g.fg,
                selected: widget.only == g.id,
                onTap: () => widget.onOnly(widget.only == g.id ? null : g.id),
              ),
            _Tile(
              width: (MediaQuery.of(context).size.width - 32 - 32 - 16) / 3,
              count: _s == null ? '–' : '${_s!['open_now']}',
              label: tr('Open to take now'),
              bg: cs.surfaceContainerHighest,
              fg: mutedOf(context),
            ),
          ]),
        ]),
      ),
    );
  }
}

class _Money extends StatelessWidget {
  final String label, value;
  final Color bg, fg;
  const _Money({required this.label, required this.value, required this.bg, required this.fg});
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(16)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: labelOf(context).copyWith(fontSize: 12)),
          Text(value, style: TextStyle(fontSize: 19, fontWeight: FontWeight.w900, color: fg)),
        ]),
      );
}

class _Tile extends StatelessWidget {
  final double width;
  final String count, label;
  final Color bg, fg;
  final bool selected;
  final VoidCallback? onTap;
  const _Tile({required this.width, required this.count, required this.label, required this.bg, required this.fg, this.selected = false, this.onTap});
  @override
  Widget build(BuildContext context) => InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          width: width,
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(16), border: Border.all(color: selected ? fg : Colors.transparent, width: 2)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(count, style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900, color: fg)),
            Text(label, maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: fg)),
          ]),
        ),
      );
}

/// The orders behind the picked tile (delivered by default), ten a page with page numbers.
class RecentDeliveries extends StatefulWidget {
  final String period;
  final String? only;
  const RecentDeliveries({super.key, required this.period, required this.only});
  @override
  State<RecentDeliveries> createState() => _RecentDeliveriesState();
}

class _RecentDeliveriesState extends State<RecentDeliveries> {
  static const _size = 10;
  int _page = 0;
  Json? _s;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    _load();
    _poll = Timer.periodic(const Duration(seconds: 30), (_) => _load());
  }

  @override
  void didUpdateWidget(RecentDeliveries old) {
    super.didUpdateWidget(old);
    if (old.period != widget.period || old.only != widget.only) {
      _page = 0;
      _load();
    }
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final (period, only, page) = (widget.period, widget.only, _page);
    try {
      final r = await context.read<RiderSession>().call('GET', '/rider/summary?period=$period&limit=$_size&offset=${page * _size}${only == null ? '' : '&group=$only'}') as Map;
      if (mounted && period == widget.period && only == widget.only && page == _page) setState(() => _s = Map<String, dynamic>.from(r));
    } catch (_) {
      /* keep the last page */
    }
  }

  void _go(int p) {
    setState(() => _page = p);
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final s = _s;
    final counts = (s?['counts'] as Map?) ?? const {};
    final total = s == null ? 0 : (widget.only != null ? (counts[widget.only] as int? ?? 0) : counts.values.fold<int>(0, (a, b) => a + (b as int)));
    final pages = (total / _size).ceil().clamp(1, 100000);
    final first = (_page - 2).clamp(0, (pages - 5).clamp(0, pages));
    final numbers = [for (var i = 0; i < (pages < 5 ? pages : 5); i++) first + i];
    final label = widget.only == null ? tr('All orders') : tr(_groupOf(widget.only!).label);
    final rows = ((s?['orders'] as List?) ?? const []).cast<Json>();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(tr('Recent deliveries'), style: kSection)),
            Text('$label · $total', style: labelOf(context).copyWith(fontSize: 12)),
          ]),
          const SizedBox(height: 6),
          if (s == null) const Padding(padding: EdgeInsets.symmetric(vertical: 24), child: Center(child: CircularProgressIndicator(strokeWidth: 2.5))),
          if (s != null && rows.isEmpty) Padding(padding: const EdgeInsets.symmetric(vertical: 24), child: Center(child: Text(tr('No orders here for this time.'), style: TextStyle(color: mutedOf(context))))),
          for (final o in rows)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(children: [
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('#${o['code']} · ${o['hotel_name']}', style: kItem, maxLines: 1, overflow: TextOverflow.ellipsis),
                    Text(_when('${o['at']}'), style: labelOf(context).copyWith(fontSize: 12)),
                  ]),
                ),
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Pill(tr(_groupOf('${o['group']}').label), bg: _groupOf('${o['group']}').bg, fg: _groupOf('${o['group']}').fg),
                  if (o['group'] == 'delivered') Text(kes(o['rider_fee']), style: const TextStyle(color: Color(0xFF15803D), fontWeight: FontWeight.w800, fontSize: 12)),
                ]),
              ]),
            ),
          if (pages > 1) ...[
            const SizedBox(height: 8),
            Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              TextButton(onPressed: _page == 0 ? null : () => _go(_page - 1), child: Text(tr('Prev'))),
              for (final n in numbers)
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 2),
                  child: n == _page
                      ? FilledButton(style: FilledButton.styleFrom(minimumSize: const Size(38, 38), padding: EdgeInsets.zero), onPressed: null, child: Text('${n + 1}'))
                      : OutlinedButton(style: OutlinedButton.styleFrom(minimumSize: const Size(38, 38), padding: EdgeInsets.zero), onPressed: () => _go(n), child: Text('${n + 1}')),
                ),
              TextButton(onPressed: _page >= pages - 1 ? null : () => _go(_page + 1), child: Text(tr('Next'))),
            ]),
          ],
        ]),
      ),
    );
  }
}
