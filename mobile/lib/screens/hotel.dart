import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../util.dart';
import 'checkout.dart';
import 'home.dart' show absUrl;

class HotelScreen extends StatefulWidget {
  final String slug;
  const HotelScreen({super.key, required this.slug});
  @override
  State<HotelScreen> createState() => _HotelScreenState();
}

class _HotelScreenState extends State<HotelScreen> {
  late final Future<Json> _menu = apiGet('/hotels/${widget.slug}/menu').then((v) => v as Json);

  Future<void> _pick(Json hotel, Json p) async {
    final opts = (p['options'] as List).cast<Json>();
    final chosen = <String>{};
    var qty = 1;
    final ok = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(builder: (ctx, set) {
        final groups = <String, List<Json>>{};
        for (final o in opts) {
          groups.putIfAbsent(o['group_name'], () => []).add(o);
        }
        final extra = opts.where((o) => chosen.contains(o['id'])).fold<int>(0, (n, o) => n + (o['price_delta'] as int));
        final base = (p['discount_price'] ?? p['price']) as int;
        return SafeArea(
          child: Padding(
            padding: EdgeInsets.fromLTRB(16, 16, 16, 16 + MediaQuery.of(ctx).viewInsets.bottom),
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(p['name'], style: Theme.of(ctx).textTheme.titleLarge),
              if ((p['description'] as String).isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(p['description'])),
              Flexible(
                child: ListView(shrinkWrap: true, children: [
                  for (final g in groups.entries) ...[
                    Padding(padding: const EdgeInsets.only(top: 12), child: Text('${g.key} · optional', style: const TextStyle(fontWeight: FontWeight.w600))),
                    for (final o in g.value)
                      CheckboxListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        value: chosen.contains(o['id']),
                        onChanged: (v) => set(() => v == true ? chosen.add(o['id']) : chosen.remove(o['id'])),
                        title: Text(o['name']),
                        secondary: (o['price_delta'] as int) > 0 ? Text('+${kes(o['price_delta'])}') : null,
                      ),
                  ],
                ]),
              ),
              Row(children: [
                IconButton(onPressed: qty > 1 ? () => set(() => qty--) : null, icon: const Icon(Icons.remove_circle_outline)),
                Text('$qty', style: Theme.of(ctx).textTheme.titleMedium),
                IconButton(onPressed: qty < 20 ? () => set(() => qty++) : null, icon: const Icon(Icons.add_circle_outline)),
                const Spacer(),
                FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text('Add · ${kes((base + extra) * qty)}')),
              ]),
            ]),
          ),
        );
      }),
    );
    if (ok != true || !mounted) return;
    final state = context.read<AppState>();
    final chosenOpts = opts.where((o) => chosen.contains(o['id'])).toList();
    final line = CartLine(
      p['id'],
      [for (final o in chosenOpts) o['id'] as String],
      p['name'],
      chosenOpts.map((o) => o['name']).join(', '),
      ((p['discount_price'] ?? p['price']) as int) + chosenOpts.fold<int>(0, (n, o) => n + (o['price_delta'] as int)),
      qty,
    );
    if (!state.add(hotel['slug'], hotel['name'], line)) {
      final clear = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Start a new cart?'),
          content: Text('Your cart has items from ${state.hotelName}. You can order from one hotel at a time.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep cart')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Clear and add')),
          ],
        ),
      );
      if (clear == true) {
        state.clear();
        state.add(hotel['slug'], hotel['name'], line);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(title: const Text('Menu')),
      bottomNavigationBar: cart.count == 0
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: FilledButton(
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CheckoutScreen())),
                  child: Text('View cart · ${cart.count} items · ~${kes(cart.estimate)}'),
                ),
              ),
            ),
      body: FutureBuilder<Json>(
        future: _menu,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
          if (snap.hasError) return Center(child: Text('${snap.error}'));
          final hotel = snap.data!['hotel'] as Json;
          final open = hotel['state'] == 'open' || hotel['state'] == 'closing_soon';
          return ListView(children: [
            ListTile(
              title: Text(hotel['name'], style: Theme.of(context).textTheme.headlineSmall),
              subtitle: Text(open ? 'Open · ~${hotel['prep_minutes']} min prep' : 'Not taking orders right now'),
            ),
            for (final c in (snap.data!['categories'] as List).cast<Json>()) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
                child: Text(c['name'], style: Theme.of(context).textTheme.titleMedium),
              ),
              for (final p in (c['products'] as List).cast<Json>())
                Builder(builder: (_) {
                  final sold = p['is_sold_out'] == true;
                  final img = (p['thumb_url'] ?? p['image_url']) as String?;
                  return ListTile(
                    enabled: open && !sold,
                    leading: img == null
                        ? const SizedBox(width: 56, child: Icon(Icons.fastfood))
                        : ClipRRect(
                            borderRadius: BorderRadius.circular(8),
                            child: Image.network(absUrl(img), width: 56, height: 56, fit: BoxFit.cover,
                                errorBuilder: (_, __, ___) => const SizedBox(width: 56, child: Icon(Icons.fastfood))),
                          ),
                    title: Text(p['name']),
                    subtitle: Text(sold ? 'Sold out' : (p['description'] as String), maxLines: 2, overflow: TextOverflow.ellipsis),
                    trailing: p['discount_price'] != null
                        ? Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
                            Text(kes(p['discount_price']), style: const TextStyle(fontWeight: FontWeight.bold)),
                            Text(kes(p['price']), style: const TextStyle(decoration: TextDecoration.lineThrough, fontSize: 12)),
                          ])
                        : Text(kes(p['price']), style: const TextStyle(fontWeight: FontWeight.bold)),
                    onTap: () => _pick(hotel, p),
                  );
                }),
            ],
            const SizedBox(height: 24),
          ]);
        },
      ),
    );
  }
}
