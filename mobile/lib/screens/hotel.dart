import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../i18n.dart';
import '../util.dart';
import 'safety.dart';
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
                    Padding(padding: const EdgeInsets.only(top: 12), child: Text('${g.key} · ${tr('optional')}', style: const TextStyle(fontWeight: FontWeight.w600))),
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
                FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Add · {amount}', {'amount': kes((base + extra) * qty)}))),
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
    if (state.add(hotel['slug'], hotel['name'], line)) {
      HapticFeedback.lightImpact();
      toast(context, tr('{qty}× {name} added to cart', {'qty': line.quantity, 'name': line.name}));
      return;
    }
    {
      final clear = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: Text(tr('Start a new cart?')),
          content: Text(tr('Your cart has items from {hotel}. You can order from one hotel at a time.', {'hotel': state.hotelName ?? ''})),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Keep cart'))),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Clear and add'))),
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
      appBar: AppBar(title: Text(tr('Menu'), style: TextStyle(fontWeight: FontWeight.w800)), actions: [IconButton(icon: const Icon(Icons.home_outlined), tooltip: tr('Home'), onPressed: () => goHome(context))]),
      bottomNavigationBar: cart.count == 0
          ? null
          : SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: FilledButton(
                  style: fullWidthFilled,
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CheckoutScreen())),
                  child: Text(tr(cart.count == 1 ? 'View cart · {n} item · ~{amount}' : 'View cart · {n} items · ~{amount}', {'n': cart.count, 'amount': kes(cart.estimate)})),
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
          return _MenuBody(hotel: hotel, cats: cats, open: open, accent: accent, onPick: (p) => _pick(hotel, p));
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
    return SizedBox(
      height: _tileH,
      child: Opacity(
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
                child: NetImage(img, width: 76, height: 76, fallback: dishFallback('${p['name']}', '', 76)),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(p['name'], maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
                  if ((p['description'] as String).isNotEmpty)
                    Text(p['description'], maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: mutedOf(context), fontSize: 13)),
                  const SizedBox(height: 6),
                  sold
                      ? Text(tr('Sold out'), style: TextStyle(color: mutedOf(context), fontWeight: FontWeight.w700))
                      : Row(children: [
                          Text(kes(deal ? p['discount_price'] : p['price']), style: const TextStyle(fontWeight: FontWeight.w800, color: brand)),
                          if (deal) ...[
                            const SizedBox(width: 6),
                            Text(kes(p['price']), style: TextStyle(decoration: TextDecoration.lineThrough, fontSize: 12, color: mutedOf(context))),
                          ],
                        ]),
                ]),
              ),
              if (enabled)
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(12)),
                  child: const Icon(Icons.add, color: Colors.white),
                ),
            ]),
          ),
        ),
      ),
    ));
  }
}

const double _tileH = 104; // fixed so a category chip can scroll to an exact offset
const double _gap = 10;
const double _headH = 52;
const double _coverH = 134; // cover only; the contact row below it changes the offset (see _contactH)
const double _contactH = 58;

/// Menu list with a search box and category chips that jump to a section.
class _MenuBody extends StatefulWidget {
  final Json hotel;
  final List<Json> cats;
  final bool open;
  final Color accent;
  final void Function(Json product) onPick;
  const _MenuBody({required this.hotel, required this.cats, required this.open, required this.accent, required this.onPick});
  @override
  State<_MenuBody> createState() => _MenuBodyState();
}

class _MenuBodyState extends State<_MenuBody> {
  final _scroll = ScrollController();
  final _query = TextEditingController();
  int _active = 0;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_track);
  }

  @override
  void dispose() {
    _scroll.dispose();
    _query.dispose();
    super.dispose();
  }

  /// Categories (and their dishes) that match the search; everything when it is empty.
  List<Json> get _cats {
    final q = _query.text.trim().toLowerCase();
    if (q.isEmpty) return widget.cats;
    final out = <Json>[];
    for (final c in widget.cats) {
      final hit = (c['name'] as String).toLowerCase().contains(q);
      final ps = (c['products'] as List).cast<Json>().where((p) => hit || '${p['name']} ${p['description']}'.toLowerCase().contains(q)).toList();
      if (ps.isNotEmpty) out.add({...c, 'products': ps});
    }
    return out;
  }

  List<double> _offsets(List<Json> cats) {
    final out = <double>[];
    var y = _coverH + (kenyanNumber(widget.hotel['phone'] as String?) != null ? _contactH : 0);
    for (final c in cats) {
      out.add(y);
      y += _headH + (c['products'] as List).length * (_tileH + _gap);
    }
    return out;
  }

  void _track() {
    final offs = _offsets(_cats);
    var i = 0;
    for (var k = 0; k < offs.length; k++) {
      if (_scroll.offset >= offs[k] - 40) i = k;
    }
    if (i != _active) setState(() => _active = i);
  }

  void _jump(int i) {
    final offs = _offsets(_cats);
    final max = _scroll.position.maxScrollExtent;
    _scroll.animateTo(offs[i].clamp(0, max), duration: const Duration(milliseconds: 350), curve: Curves.easeOutCubic);
    setState(() => _active = i);
  }

  @override
  Widget build(BuildContext context) {
    final cats = _cats;
    final h = widget.hotel;
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        child: TextField(
          controller: _query,
          onChanged: (_) => setState(() {
            _active = 0;
            if (_scroll.hasClients) _scroll.jumpTo(0);
          }),
          decoration: InputDecoration(
            hintText: tr('Search dishes'),
            prefixIcon: const Icon(Icons.search),
            suffixIcon: _query.text.isEmpty ? null : IconButton(icon: const Icon(Icons.close), onPressed: () => setState(() => _query.clear())),
            isDense: true,
            contentPadding: const EdgeInsets.symmetric(vertical: 12),
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(99)),
            enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(99), borderSide: BorderSide(color: Theme.of(context).dividerColor)),
          ),
        ),
      ),
      if (cats.length > 1)
        SizedBox(
          height: 44,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            itemCount: cats.length,
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemBuilder: (_, i) => ChoiceChip(
              label: Text('${cats[i]['name']}'),
              selected: i == _active,
              showCheckmark: false,
              selectedColor: brand,
              labelStyle: TextStyle(fontWeight: FontWeight.w700, color: i == _active ? Colors.white : null),
              shape: const StadiumBorder(),
              onSelected: (_) => _jump(i),
            ),
          ),
        ),
      Expanded(
        child: cats.isEmpty
            ? ListView(controller: _scroll, children: [
                const SizedBox(height: 80),
                const Center(child: Text('🔎', style: TextStyle(fontSize: 48))),
                Center(child: Padding(padding: const EdgeInsets.all(12), child: Text(tr('No dish matches "{q}"', {'q': _query.text.trim()}), style: kItem))),
                Center(child: TextButton(onPressed: () => setState(_query.clear), child: Text(tr('Clear search')))),
              ])
            : CustomScrollView(controller: _scroll, slivers: [
                SliverToBoxAdapter(child: _Cover(hotel: h, open: widget.open, accent: widget.accent)),
                if (kenyanNumber(h['phone'] as String?) != null)
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
                      child: ContactRow(h['phone'] as String?, message: 'Hello ${h['name']}, I have a question about your menu.'),
                    ),
                  ),
                for (final c in cats) ...[
                  SliverToBoxAdapter(
                    child: SizedBox(
                      height: _headH,
                      child: Padding(padding: const EdgeInsets.fromLTRB(16, 20, 16, 8), child: Text(c['name'], style: kSection.copyWith(fontSize: 18), maxLines: 1, overflow: TextOverflow.ellipsis)),
                    ),
                  ),
                  SliverPadding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    sliver: SliverFixedExtentList(
                      itemExtent: _tileH + _gap,
                      delegate: SliverChildBuilderDelegate(
                        childCount: (c['products'] as List).length,
                        (_, i) {
                          final p = (c['products'] as List)[i] as Json;
                          return Padding(
                            padding: const EdgeInsets.only(bottom: _gap),
                            child: _ProductTile(p, enabled: widget.open && p['is_sold_out'] != true, onTap: () => widget.onPick(p)),
                          );
                        },
                      ),
                    ),
                  ),
                ],
                const SliverToBoxAdapter(child: SizedBox(height: 32)),
              ]),
      ),
    ]);
  }
}

class _Cover extends StatelessWidget {
  final Json hotel;
  final bool open;
  final Color accent;
  const _Cover({required this.hotel, required this.open, required this.accent});
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.fromLTRB(16, 4, 16, 0),
        height: _coverH - 4,
        clipBehavior: Clip.antiAlias,
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(24), gradient: LinearGradient(colors: [accent, Color.lerp(accent, Colors.black, .55)!])),
        child: Stack(fit: StackFit.expand, children: [
          if (hotel['cover_url'] != null) NetImage(hotel['cover_url']),
          const DecoratedBox(decoration: BoxDecoration(gradient: LinearGradient(colors: [Colors.transparent, Colors.black54], begin: Alignment.center, end: Alignment.bottomCenter))),
          if (hotel['verified'] == true) Positioned(top: 10, right: 10, child: verifiedPill()),
          Positioned(
            left: 16,
            bottom: 12,
            right: 16,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(hotel['name'], style: const TextStyle(color: Colors.white, fontSize: 24, fontWeight: FontWeight.w800)),
              Text(open ? tr('Open · ~{min} min prep', {'min': hotel['prep_minutes']}) : tr('Not taking orders right now'), style: const TextStyle(color: Colors.white70)),
            ]),
          ),
        ]),
      );
}
