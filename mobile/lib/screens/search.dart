import 'dart:async';
import 'package:flutter/material.dart';
import '../api.dart';
import '../util.dart';
import 'hotel.dart';

/// Keyword search across every hotel's menu (e.g. "pizza").
class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key});
  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  Timer? _debounce;
  Future<List>? _hits;
  String _term = '';

  void _changed(String v) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 250), () {
      final t = v.trim();
      setState(() {
        _term = t;
        _hits = t.isEmpty ? null : apiGet('/search?q=${Uri.encodeQueryComponent(t)}').then((r) => r as List);
      });
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: TextField(
          autofocus: true,
          onChanged: _changed,
          decoration: const InputDecoration(hintText: 'Search food, e.g. pizza', border: InputBorder.none),
        ),
      ),
      body: _hits == null
          ? const SizedBox.shrink()
          : FutureBuilder<List>(
              future: _hits,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
                if (snap.hasError) return Center(child: Text('${snap.error}'));
                final hits = snap.data!.cast<Json>();
                if (hits.isEmpty) return Center(child: Text('No dish matches "$_term"'));
                return ListView.separated(
                  itemCount: hits.length,
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemBuilder: (_, i) {
                    final h = hits[i];
                    final thumb = h['thumb_url'] as String?;
                    return ListTile(
                      leading: ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: SizedBox(
                          width: 52,
                          height: 52,
                          child: NetImage(thumb, width: 52, height: 52, fallback: Container(color: const Color(0xFFFFEDE3), child: const Icon(Icons.restaurant, color: brand))),
                        ),
                      ),
                      title: Text(h['name']),
                      subtitle: Text('${h['hotel_name']} · ${h['category']}'),
                      trailing: Text(h['is_sold_out'] == true ? 'Sold out' : kes(h['price'])),
                      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => HotelScreen(slug: h['hotel_slug']))),
                    );
                  },
                );
              },
            ),
    );
  }
}
