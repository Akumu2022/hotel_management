import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../util.dart';
import 'hotel.dart';
import 'search.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<List> _hotels = _get('/hotels');
  late Future<List> _offers = _offersOrEmpty();
  Future<List> _get(String path) async => (await apiGet(path)) as List;
  Future<List> _offersOrEmpty() async {
    try {
      return await _get('/offers');
    } catch (_) {
      return const [];
    }
  }

  Future<void> _refresh() async {
    setState(() {
      _hotels = _get('/hotels');
      _offers = _offersOrEmpty();
    });
    try {
      await _hotels;
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Order food', style: TextStyle(fontWeight: FontWeight.w800)),
        actions: [
          IconButton(
            icon: const Icon(Icons.support_agent_outlined),
            tooltip: 'Help on WhatsApp',
            onPressed: () => openWhatsApp(context, 'Hello Chakula, I need help with '),
          ),
          IconButton(
            icon: Icon(Theme.of(context).brightness == Brightness.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined),
            tooltip: 'Dark mode',
            onPressed: () => context.read<AppState>().setTheme(Theme.of(context).brightness == Brightness.dark ? ThemeMode.light : ThemeMode.dark),
          ),
        ],
      ),
      body: RefreshIndicator(
        color: brand,
        onRefresh: _refresh,
        child: CustomScrollView(slivers: [
          SliverToBoxAdapter(
            child: ValueListenableBuilder<bool>(
              valueListenable: offline,
              builder: (_, off, __) => off
                  ? Container(
                      margin: const EdgeInsets.fromLTRB(16, 0, 16, 10),
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(color: const Color(0xFFFEF3C7), borderRadius: BorderRadius.circular(14)),
                      child: const Row(children: [
                        Icon(Icons.wifi_off, size: 18, color: Color(0xFF92400E)),
                        SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            "You're offline. Showing saved hotels; pull down to retry.",
                            style: TextStyle(color: Color(0xFF92400E), fontSize: 13, fontWeight: FontWeight.w600),
                          ),
                        ),
                      ]),
                    )
                  : const SizedBox.shrink(),
            ),
          ),
          const SliverToBoxAdapter(child: _Hero()),
          SliverToBoxAdapter(
            child: FutureBuilder<List>(
              future: _offers,
              builder: (_, snap) {
                final offers = snap.data ?? const [];
                if (offers.isEmpty) return const SizedBox.shrink();
                return _Deals(offers.cast<Json>());
              },
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 20, 16, 12),
              child: Row(children: [
                const Expanded(child: Text('Hotels near you', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800))),
                FilledButton.icon(
                  style: FilledButton.styleFrom(minimumSize: const Size(0, 40), padding: const EdgeInsets.symmetric(horizontal: 16)),
                  icon: const Icon(Icons.search, size: 20),
                  label: const Text('Search'),
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SearchScreen())),
                ),
              ]),
            ),
          ),
          FutureBuilder<List>(
            future: _hotels,
            builder: (_, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return SliverPadding(
                  padding: const EdgeInsets.symmetric(horizontal: 16),
                  sliver: SliverList.separated(itemCount: 3, separatorBuilder: (_, __) => const SizedBox(height: 14), itemBuilder: (_, __) => const Skel(230)),
                );
              }
              if (snap.hasError) {
                return SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.all(32),
                    child: Column(children: [
                      Text('${snap.error}', textAlign: TextAlign.center),
                      const SizedBox(height: 12),
                      OutlinedButton(onPressed: _refresh, child: const Text('Try again')),
                    ]),
                  ),
                );
              }
              final hotels = snap.data!.cast<Json>();
              if (hotels.isEmpty) {
                return const SliverToBoxAdapter(child: Padding(padding: EdgeInsets.all(48), child: Center(child: Text('No hotels are open right now'))));
              }
              return SliverPadding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 32),
                sliver: SliverList.separated(
                  itemCount: hotels.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 14),
                  itemBuilder: (_, i) => _HotelCard(hotels[i]),
                ),
              );
            },
          ),
        ]),
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero();
  @override
  Widget build(BuildContext context) => Container(
        margin: const EdgeInsets.fromLTRB(16, 4, 16, 0),
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(24)),
        child: const Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Karibu!', style: TextStyle(color: Colors.white70, fontWeight: FontWeight.w600)),
              SizedBox(height: 4),
              Text('Hot food from local hotels, delivered or ready for pickup.',
                  style: TextStyle(color: Colors.white, fontSize: 19, height: 1.2, fontWeight: FontWeight.w800)),
            ]),
          ),
          SizedBox(width: 8),
          Text('🍲', style: TextStyle(fontSize: 54)),
        ]),
      );
}

class _Deals extends StatelessWidget {
  final List<Json> offers;
  const _Deals(this.offers);
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Padding(
          padding: EdgeInsets.fromLTRB(16, 20, 16, 10),
          child: Row(children: [
            Icon(Icons.local_fire_department, color: brand),
            SizedBox(width: 6),
            Text("Today's deals", style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
          ]),
        ),
        SizedBox(
          height: 176,
          child: PageView.builder(
            controller: PageController(viewportFraction: .9),
            padEnds: false,
            itemCount: offers.length,
            itemBuilder: (_, i) => Padding(
              padding: EdgeInsets.only(left: i == 0 ? 16 : 6, right: 6),
              child: _OfferBanner(offers[i]),
            ),
          ),
        ),
      ]);
}

class _OfferBanner extends StatelessWidget {
  final Json o;
  const _OfferBanner(this.o);
  @override
  Widget build(BuildContext context) {
    final parts = (o['title'] as String).split('\n');
    final head = parts.first.trim();
    final sub = parts.skip(1).join(' ').trim();
    final img = o['image_url'] as String?;
    return GestureDetector(
      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => HotelScreen(slug: o['hotel_slug']))),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(24),
        child: Stack(fit: StackFit.expand, children: [
          const DecoratedBox(
            decoration: BoxDecoration(gradient: LinearGradient(colors: [brand, brandDark], begin: Alignment.topLeft, end: Alignment.bottomRight)),
          ),
          if (img != null)
            Align(
              alignment: Alignment.centerRight,
              child: FractionallySizedBox(
                widthFactor: .68,
                child: ShaderMask(
                  blendMode: BlendMode.dstIn,
                  shaderCallback: (r) => const LinearGradient(colors: [Colors.transparent, Colors.black], stops: [0, .38]).createShader(r),
                  child: NetImage(img, width: 260),
                ),
              ),
            ),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
              Pill(o['hotel_name'], bg: Colors.white, fg: ink),
              SizedBox(
                width: 175,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(head.toUpperCase(),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: Colors.white, fontSize: 20, height: 1.05, fontWeight: FontWeight.w900)),
                  if (sub.isNotEmpty) ...[
                    const SizedBox(height: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(color: const Color(0xFFFCD34D), borderRadius: BorderRadius.circular(8)),
                      child: Text(sub, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: ink, fontSize: 12, fontWeight: FontWeight.w800)),
                    ),
                  ],
                ]),
              ),
              const Text('Order now  →', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _HotelCard extends StatelessWidget {
  final Json h;
  const _HotelCard(this.h);

  static const _labels = {
    'open': 'Open now',
    'closing_soon': 'Closing soon',
    'closed': 'Closed',
    'paused': 'Not taking orders',
    'not_accepting': 'Not taking orders',
  };

  @override
  Widget build(BuildContext context) {
    final open = h['state'] == 'open' || h['state'] == 'closing_soon';
    final accent = accentOf(h['accent_color']);
    final rating = h['rating'];
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => HotelScreen(slug: h['slug']))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          AspectRatio(
            aspectRatio: 16 / 9,
            child: Stack(fit: StackFit.expand, children: [
              DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(colors: [accent, Color.lerp(accent, Colors.black, .55)!], begin: Alignment.topLeft, end: Alignment.bottomRight),
                ),
              ),
              if (h['cover_url'] != null) Opacity(opacity: open ? 1 : .5, child: NetImage(h['cover_url'])),
              const DecoratedBox(
                decoration: BoxDecoration(gradient: LinearGradient(colors: [Colors.transparent, kMuted], begin: Alignment.center, end: Alignment.bottomCenter)),
              ),
              Positioned(
                left: 14,
                bottom: 12,
                right: 14,
                child: Text(h['name'], maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800)),
              ),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.all(14),
            child: Row(children: [
              Expanded(
                child: Wrap(spacing: 6, runSpacing: 6, children: [
                  Pill(_labels[h['state']] ?? '',
                      bg: open ? const Color(0xFFDCFCE7) : const Color(0xFFF1F1F1), fg: open ? const Color(0xFF15803D) : kMuted),
                  if (rating != null) Pill('${(rating as num).toStringAsFixed(1)} (${h['rating_count']})', icon: Icons.star_rounded),
                  Pill('${h['prep_minutes']} min', icon: Icons.timer_outlined),
                ]),
              ),
              const SizedBox(width: 8),
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(color: brand, borderRadius: BorderRadius.circular(12)),
                child: const Icon(Icons.arrow_forward, color: Colors.white, size: 20),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}
