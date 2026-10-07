import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import 'hotel.dart';
import 'checkout.dart';
import 'orders.dart';

/// Image URLs come back as server paths (e.g. /media/..); make them absolute.
String absUrl(String u) => u.startsWith('http') ? u : Uri.parse(apiBase).replace(path: u).toString();

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});
  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late Future<List> _hotels = _load();
  Future<List> _load() async => (await apiGet('/hotels')) as List;

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(title: const Text('Order food'), actions: [
        IconButton(
          icon: const Icon(Icons.receipt_long),
          tooltip: 'My orders',
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const OrdersScreen())),
        ),
        IconButton(
          icon: Badge(isLabelVisible: cart.count > 0, label: Text('${cart.count}'), child: const Icon(Icons.shopping_basket)),
          tooltip: 'Cart',
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CheckoutScreen())),
        ),
      ]),
      body: RefreshIndicator(
        onRefresh: () async => setState(() => _hotels = _load()),
        child: FutureBuilder<List>(
          future: _hotels,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
            if (snap.hasError) {
              return ListView(children: [
                const SizedBox(height: 120),
                Center(child: Text('${snap.error}')),
                TextButton(onPressed: () => setState(() => _hotels = _load()), child: const Text('Try again')),
              ]);
            }
            final hotels = snap.data!;
            if (hotels.isEmpty) return ListView(children: const [SizedBox(height: 120), Center(child: Text('No hotels yet'))]);
            return ListView.builder(
              padding: const EdgeInsets.all(12),
              itemCount: hotels.length,
              itemBuilder: (_, i) => _HotelCard(hotels[i] as Json),
            );
          },
        ),
      ),
    );
  }
}

class _HotelCard extends StatelessWidget {
  final Json h;
  const _HotelCard(this.h);

  static const _labels = {
    'open': 'Open',
    'closing_soon': 'Closing soon',
    'closed': 'Closed',
    'paused': 'Paused',
    'not_accepting': 'Not taking orders',
  };

  @override
  Widget build(BuildContext context) {
    final open = h['state'] == 'open' || h['state'] == 'closing_soon';
    final cover = h['cover_url'] as String?;
    final rating = h['rating'];
    return Card(
      clipBehavior: Clip.antiAlias,
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => HotelScreen(slug: h['slug']))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(
            height: 130,
            width: double.infinity,
            child: cover == null
                ? Container(color: Colors.orange.shade100, child: const Icon(Icons.restaurant, size: 40))
                : Opacity(
                    opacity: open ? 1 : .5,
                    child: Image.network(absUrl(cover), fit: BoxFit.cover, errorBuilder: (_, __, ___) => Container(color: Colors.orange.shade100)),
                  ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(h['name'], style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: 2),
                  Text(
                    [
                      if (rating != null) '★ ${(rating as num).toStringAsFixed(1)} (${h['rating_count']})',
                      '~${h['prep_minutes']} min',
                    ].join(' · '),
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ]),
              ),
              Chip(
                label: Text(_labels[h['state']] ?? ''),
                backgroundColor: open ? Colors.green.shade100 : Colors.grey.shade300,
                visualDensity: VisualDensity.compact,
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}
