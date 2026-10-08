import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../i18n.dart';
import '../util.dart';
import 'shell.dart';
import 'track.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});
  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  late Future<List> _rows = _load();

  Future<List> _load() async {
    final tokens = [for (final r in context.read<AppState>().recent) r['token']];
    if (tokens.isEmpty) return [];
    return (await apiPost('/track/history', {'tokens': tokens})) as List;
  }

  Future<void> _again(Json r) async {
    try {
      final t = await apiGet('/track/${r['token']}') as Json;
      if (!mounted) return;
      context.read<AppState>().orderAgain(t);
      tabIndex.value = 2;
      toast(context, tr('Your order is back in the basket'));
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message);
    }
  }

  static const _done = ['delivered', 'collected'];
  static const _bad = ['expired', 'rejected', 'cancelled', 'failed_delivery'];

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(tr('My orders'), style: TextStyle(fontWeight: FontWeight.w800))),
        body: RefreshIndicator(
          color: brand,
          onRefresh: () async {
            setState(() => _rows = _load());
            await _rows;
          },
          child: FutureBuilder<List>(
            future: _rows,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return ListView(padding: const EdgeInsets.all(16), children: [
                  for (var i = 0; i < 4; i++) ...const [Skel(92), SizedBox(height: 12)],
                ]);
              }
              if (snap.hasError) return ListView(children: [const SizedBox(height: 120), Center(child: Text('${snap.error}'))]);
              final rows = snap.data!.cast<Json>();
              if (rows.isEmpty) {
                return ListView(children: [
                  const SizedBox(height: 120),
                  const Center(child: Text('🧾', style: TextStyle(fontSize: 56))),
                  const SizedBox(height: 8),
                  Center(child: Text(tr('No orders yet'), style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800))),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 48, vertical: 16),
                    child: OutlinedButton(onPressed: () => tabIndex.value = 0, child: Text(tr('Find something tasty'))),
                  ),
                ]);
              }
              return ListView.separated(
                padding: const EdgeInsets.all(16),
                itemCount: rows.length,
                separatorBuilder: (_, __) => const SizedBox(height: 12),
                itemBuilder: (_, i) {
                  final r = rows[i];
                  final status = '${r['status']}';
                  final ok = _done.contains(status), bad = _bad.contains(status);
                  return Card(
                    clipBehavior: Clip.antiAlias,
                    child: InkWell(
                      onTap: () async {
                        await Navigator.push(context, MaterialPageRoute(builder: (_) => TrackScreen(token: r['token'])));
                        if (mounted) setState(() => _rows = _load());
                      },
                      child: Padding(
                        padding: const EdgeInsets.all(14),
                        child: Row(children: [
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text('${r['hotel_name']} · ${r['code']}', style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
                              const SizedBox(height: 2),
                              Text((r['items'] as List).join(', '), maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: mutedOf(context), fontSize: 13)),
                              const SizedBox(height: 8),
                              Pill(tr(status.replaceAll('_', ' ')),
                                  bg: ok ? const Color(0xFFDCFCE7) : bad ? const Color(0xFFFEE2E2) : const Color(0xFFFFE4D6),
                                  fg: ok ? const Color(0xFF15803D) : bad ? const Color(0xFFB91C1C) : brand),
                            ]),
                          ),
                          const SizedBox(width: 8),
                          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                            Text(kes(r['till_amount']), style: const TextStyle(fontWeight: FontWeight.w800)),
                            if (ok || bad) TextButton.icon(onPressed: () => _again(r), icon: const Icon(Icons.replay, size: 16), label: Text(tr('Again'))),
                          ]),
                        ]),
                      ),
                    ),
                  );
                },
              );
            },
          ),
        ),
      );
}
