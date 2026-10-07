import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../store.dart';
import '../util.dart';
import 'track.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});
  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  late final Future<List> _rows = _load();

  Future<List> _load() async {
    final tokens = [for (final r in context.read<AppState>().recent) r['token']];
    if (tokens.isEmpty) return [];
    return (await apiPost('/track/history', {'tokens': tokens})) as List;
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('My orders')),
        body: FutureBuilder<List>(
          future: _rows,
          builder: (context, snap) {
            if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
            if (snap.hasError) return Center(child: Text('${snap.error}'));
            final rows = snap.data!.cast<Json>();
            if (rows.isEmpty) return const Center(child: Text('No orders yet'));
            return ListView.separated(
              itemCount: rows.length,
              separatorBuilder: (_, __) => const Divider(height: 1),
              itemBuilder: (_, i) {
                final r = rows[i];
                return ListTile(
                  title: Text('${r['hotel_name']} · ${r['code']}'),
                  subtitle: Text('${(r['items'] as List).join(', ')}\n${r['status']}'.replaceAll('_', ' ')),
                  isThreeLine: true,
                  trailing: Text(kes(r['till_amount'])),
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => TrackScreen(token: r['token']))),
                );
              },
            );
          },
        ),
      );
}
