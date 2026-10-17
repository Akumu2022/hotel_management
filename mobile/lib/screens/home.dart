import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../i18n.dart';
import '../util.dart';
import 'hotel.dart';
import 'age_gate.dart';
import 'safety.dart';
import 'server.dart';
import 'search.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<List> _hotels = _get(_hotelsPath);
  // Chakula (food hotels) or Drinks (liquor stores)
  String get _hotelsPath => context.read<AppState>().section == 'liquor' ? '/hotels?kind=liquor' : '/hotels';
  late Future<List> _offers = _offersOrEmpty();
  late Future<Json?> _banner = _bannerOrNull();
  Future<Json?> _bannerOrNull() async {
    try {
      final b = ((await apiGet('/config')) as Map)['banner'];
      return b is Map ? Map<String, dynamic>.from(b) : null;
    } catch (_) {
      return null;
    }
  }

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
      _hotels = _get(_hotelsPath);
      _offers = _offersOrEmpty();
      _banner = _bannerOrNull();
    });
    try {
      await _hotels;
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final st = context.watch<AppState>();
    final liquor = st.section == 'liquor';
    drinksVariant = liquor;
    return Scaffold(
      appBar: AppBar(
        // Press and hold the title to open the server address (for whoever sets the app up).
        title: GestureDetector(
          onLongPress: () async { if (await showServerDialog(context)) _refresh(); },
          child: Text(tr('Order food'), style: const TextStyle(fontWeight: FontWeight.w800)),
        ),
        actions: [
          const _LangToggle(),
          IconButton(
            icon: const Icon(Icons.support_agent_outlined),
            tooltip: tr('Help on WhatsApp'),
            onPressed: () => openWhatsApp(context, 'Hello Chakula, I need help with '),
          ),
          IconButton(
            icon: Icon(Theme.of(context).brightness == Brightness.dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined),
            tooltip: tr('Dark mode'),
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
                      child: Row(children: [
                        Icon(Icons.wifi_off, size: 18, color: Color(0xFF92400E)),
                        SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            tr("You're offline. Showing saved hotels; pull down to retry."),
                            style: TextStyle(color: Color(0xFF92400E), fontSize: 13, fontWeight: FontWeight.w600),
                          ),
                        ),
                      ]),
                    )
                  : const SizedBox.shrink(),
            ),
          ),
          SliverToBoxAdapter(
            child: FutureBuilder<Json?>(future: _banner, builder: (_, snap) => _Hero(liquor ? null : snap.data)),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 0),
              child: InkWell(
                borderRadius: BorderRadius.circular(16),
                onTap: () => showSafetySheet(context),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(color: const Color(0xFFDCFCE7), borderRadius: BorderRadius.circular(16)),
                  child: Row(children: [
                    const Icon(Icons.shield_outlined, color: Color(0xFF15803D)),
                    const SizedBox(width: 10),
                    Expanded(child: Text(tr("You pay the hotel's own M-Pesa Till directly. Tap to see how we keep you safe."), style: const TextStyle(color: Color(0xFF15803D), fontWeight: FontWeight.w700, fontSize: 13))),
                    const Icon(Icons.chevron_right, color: Color(0xFF15803D)),
                  ]),
                ),
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 14, 16, 0),
              child: SegmentedButton<String>(
                segments: [
                  ButtonSegment(value: 'hotel', label: Text(tr('Chakula'))),
                  ButtonSegment(value: 'liquor', label: Text(tr('Drinks'))),
                ],
                selected: {st.section},
                onSelectionChanged: (v) {
                  st.setSection(v.first);
                  setState(() => _hotels = _get(_hotelsPath));
                },
              ),
            ),
          ),
          SliverToBoxAdapter(
            child: FutureBuilder<List>(
              future: _offers,
              builder: (_, snap) {
                final offers = snap.data ?? const [];
                if (offers.isEmpty || liquor) return const SizedBox.shrink();
                return _Deals(offers.cast<Json>());
              },
            ),
          ),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 20, 16, 12),
              child: Row(children: [
                Expanded(child: Text(tr('Hotels near you'), style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800))),
                FilledButton.icon(
                  style: FilledButton.styleFrom(minimumSize: const Size(0, 40), padding: const EdgeInsets.symmetric(horizontal: 16)),
                  icon: const Icon(Icons.search, size: 20),
                  label: Text(tr('Search')),
                  onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => SearchScreen(kind: st.section))),
                ),
              ]),
            ),
          ),
          if (liquor && !st.ageOk)
            SliverToBoxAdapter(child: AgeGate(onYes: st.confirmAge, onNo: () => st.setSection('hotel')))
          else
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
                      OutlinedButton(onPressed: _refresh, child: Text(tr('Try again'))),
                      TextButton(onPressed: () async { if (await showServerDialog(context)) _refresh(); }, child: Text(tr('Server address'))),
                    ]),
                  ),
                );
              }
              final hotels = snap.data!.cast<Json>();
              if (hotels.isEmpty) {
                return SliverToBoxAdapter(child: Padding(padding: EdgeInsets.all(48), child: Center(child: Text(tr('No hotels are open right now')))));
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

/// EN | SW switch with the active language filled in orange.
class _LangToggle extends StatelessWidget {
  const _LangToggle();
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    Widget chip(String code, String label) {
      final on = lang.value == code;
      return GestureDetector(
        onTap: () => context.read<AppState>().setLang(code),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
          decoration: BoxDecoration(color: on ? brand : Colors.transparent, borderRadius: BorderRadius.circular(99)),
          child: Text(label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: on ? Colors.white : cs.onSurface)),
        ),
      );
    }

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 4),
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(color: cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(99), border: Border.all(color: cs.outlineVariant)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [chip('en', 'EN'), chip('sw', 'SW')]),
    );
  }
}

class _Hero extends StatelessWidget {
  final Json? banner;
  const _Hero(this.banner);
  @override
  Widget build(BuildContext context) {
    // A const widget would keep the old language when the toggle flips, so listen to it here.
    return ValueListenableBuilder<String>(valueListenable: lang, builder: (_, __, ___) => _body());
  }

  String _pick(String key, String fallback) {
    final v = '${banner?[key] ?? ''}'.trim();
    return v.isEmpty ? fallback : v;
  }

  Color _color(String key, Color fallback) {
    final v = '${banner?[key] ?? ''}'.trim();
    if (!RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(v)) return fallback;
    return Color(int.parse('FF${v.substring(1)}', radix: 16));
  }

  Widget _body() {
    final img = banner?['image_url'] as String?;
    final fg = _color('text_color', Colors.white);
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 0),
      constraints: const BoxConstraints(minHeight: 150),
      decoration: BoxDecoration(color: _color('bg_color', brand), borderRadius: BorderRadius.circular(24)),
      clipBehavior: Clip.antiAlias,
      child: Stack(children: [
        // Banner colour holds the left half, then melts away so the photo takes over on the right.
        if (img != null)
          Positioned.fill(
            child: Align(
              alignment: Alignment.centerRight,
              child: FractionallySizedBox(
                widthFactor: .62,
                heightFactor: 1,
                child: ShaderMask(
                  blendMode: BlendMode.dstIn,
                  shaderCallback: (r) => const LinearGradient(colors: [Colors.transparent, Colors.transparent, Colors.black], stops: [0, .18, .6]).createShader(r),
                  child: NetImage(img, width: 400, fit: BoxFit.cover),
                ),
              ),
            ),
          ),
        Padding(
          padding: const EdgeInsets.all(20),
          child: Row(children: [
            Expanded(
              flex: 11,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(_pick('greeting', tr('Karibu!')), style: TextStyle(color: fg.withValues(alpha: .9), fontSize: 20, fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                Text(_pick('title', tr('Hot food from local hotels, delivered or ready for pickup.')),
                    style: TextStyle(color: fg, fontSize: 19, height: 1.2, fontWeight: FontWeight.w800)),
                if (_pick('note', '').isNotEmpty) ...[
                  const SizedBox(height: 6),
                  Text(_pick('note', ''), style: TextStyle(color: fg.withValues(alpha: .9), fontSize: 13, fontWeight: FontWeight.w600)),
                ],
              ]),
            ),
            Expanded(flex: 9, child: img == null ? Center(child: Text(_pick('emoji', '🍲'), style: const TextStyle(fontSize: 54))) : const SizedBox()),
          ]),
        ),
      ]),
    );
  }
}

class _Deals extends StatelessWidget {
  final List<Json> offers;
  const _Deals(this.offers);
  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: EdgeInsets.fromLTRB(16, 20, 16, 10),
          child: Row(children: [
            Icon(Icons.local_fire_department, color: brand),
            SizedBox(width: 6),
            Text(tr("Today's deals"), style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
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
              Text(tr('Order now  →'), style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13)),
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
              if (h['cover_url'] == null) Center(child: Opacity(opacity: .25, child: Text(foodEmoji(h['name']), style: const TextStyle(fontSize: 84)))),
              if (h['cover_url'] != null) Opacity(opacity: open ? 1 : .5, child: NetImage(h['cover_url'])),
              const DecoratedBox(
                decoration: BoxDecoration(gradient: LinearGradient(colors: [Colors.transparent, Colors.black54], begin: Alignment.center, end: Alignment.bottomCenter)),
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
                  if (h['verified'] == true) verifiedPill(),
                  Pill(tr(_labels[h['state']] ?? ''),
                      bg: open ? const Color(0xFFDCFCE7) : const Color(0xFFF1F1F1), fg: open ? const Color(0xFF15803D) : mutedOf(context)),
                  if (rating != null) Pill('${(rating as num).toStringAsFixed(1)} (${h['rating_count']})', icon: Icons.star_rounded),
                  if (h['kind'] != 'liquor') Pill('${h['prep_minutes']} min', icon: Icons.timer_outlined),
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
