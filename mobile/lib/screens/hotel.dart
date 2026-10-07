import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../util.dart';
import 'shell.dart';
import 'checkout.dart';

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
      appBar: AppBar(title: const Text('Menu', style: TextStyle(fontWeight: FontWeight.w800)), actions: [IconButton(icon: const Icon(Icons.home_outlined), tooltip: 'Home', onPressed: () => goHome(context))]),
      bottomNavigationBar: cart.count == 0
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: FilledButton(
                  style: fullWidthFilled,
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CheckoutScreen())),
                  child: Text('View cart · ${cart.count} items · ~${kes(cart.estimate)}'),
                ),
              ),
            ),
      body: FutureBuilder<Json>(
        future: _menu,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return ListView(padding: const EdgeInsets.all(16), children: [
              const Skel(130),
              for (var i = 0; i < 5; i++) ...const [SizedBox(height: 12), Skel(96)],
            ]);
          }
          if (snap.hasError) return Center(child: Text('${snap.error}'));
          final hotel = snap.data!['hotel'] as Json;
          final open = hotel['state'] == 'open' || hotel['state'] == 'closing_soon';
          final accent = accentOf(hotel['accent_color']);
          final cats = (snap.data!['categories'] as List).cast<Json>();
          return CustomScrollView(slivers: [
            SliverToBoxAdapter(
              child: Container(
                margin: const EdgeInsets.fromLTRB(16, 0, 16, 4),
                height: 130,
                clipBehavior: Clip.antiAlias,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(24),
                  gradient: LinearGradient(colors: [accent, Color.lerp(accent, Colors.black, .55)!]),
                ),
                child: Stack(fit: StackFit.expand, children: [
                  if (hotel['cover_url'] != null) NetImage(hotel['cover_url']),
                  const DecoratedBox(
                    decoration: BoxDecoration(gradient: LinearGradient(colors: [Colors.transparent, kMuted], begin: Alignment.center, end: Alignment.bottomCenter)),
                  ),
                  Positioned(
                    left: 16,
                    bottom: 12,
                    right: 16,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(hotel['name'], style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w800)),
                      Text(open ? 'Open · ~${hotel['prep_minutes']} min prep' : 'Not taking orders right now', style: const TextStyle(color: Colors.white70)),
                    ]),
                  ),
                ]),
              ),
            ),
            for (final c in cats) ...[
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
                  child: Text(c['name'], style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                ),
              ),
              SliverPadding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                sliver: SliverList.separated(
                  itemCount: (c['products'] as List).length,
                  separatorBuilder: (_, __) => const SizedBox(height: 10),
                  itemBuilder: (_, i) {
                    final p = (c['products'] as List)[i] as Json;
                    return _ProductTile(p, enabled: open && p['is_sold_out'] != true, onTap: () => _pick(hotel, p));
                  },
                ),
              ),
            ],
            const SliverToBoxAdapter(child: SizedBox(height: 32)),
          ]);
        },
      ),
    );
  }
}

class _ProductTile extends StatelessWidget {
  final Json p;
  final bool enabled;
  final VoidCallback onTap;
  const _ProductTile(this.p, {required this.enabled, required this.onTap});
  @override
  Widget build(BuildContext context) {
    final sold = p['is_sold_out'] == true;
    final img = (p['thumb_url'] ?? p['image_url']) as String?;
    final deal = p['discount_price'] != null;
    return Opacity(
      opacity: enabled ? 1 : .5,
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: enabled ? onTap : null,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Row(children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(14),
                child: NetImage(img, width: 76, height: 76, fallback: Container(color: const Color(0xFFFFEDE3), child: const Icon(Icons.restaurant, color: brand))),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(p['name'], maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  if ((p['description'] as String).isNotEmpty)
                    Text(p['description'], maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: kMuted, fontSize: 13)),
                  const SizedBox(height: 6),
                  sold
                      ? const Text('Sold out', style: TextStyle(color: kMuted, fontWeight: FontWeight.w700))
                      : Row(children: [
                          Text(kes(deal ? p['discount_price'] : p['price']), style: const TextStyle(fontWeight: FontWeight.w800, color: brand)),
                          if (deal) ...[
                            const SizedBox(width: 6),
                            Text(kes(p['price']), style: const TextStyle(decoration: TextDecoration.lineThrough, fontSize: 12, color: kMuted)),
                          ],
                        ]),
                ]),
              ),
              if (enabled)
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(12)),
                  child: const Icon(Icons.add, color: Colors.white),
                ),
            ]),
          ),
        ),
      ),
    );
  }
}
