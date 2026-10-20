import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api.dart';
import '../i18n.dart';
import '../store.dart';
import '../util.dart';

/// Promo codes the hotel chose to show to everyone: tap Claim and checkout applies the code.
class PromoStrip extends StatefulWidget {
  final String slug;
  const PromoStrip({super.key, required this.slug});
  @override
  State<PromoStrip> createState() => _PromoStripState();
}

class _PromoStripState extends State<PromoStrip> {
  List<Json> _promos = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = (await apiGet('/hotels/${widget.slug}/promos') as List).cast<Json>();
      if (mounted) setState(() => _promos = r);
    } catch (_) {
      /* no coupon cards is fine: the code can still be typed at checkout */
    }
  }

  String _until(String? iso) {
    final d = iso == null ? null : DateTime.tryParse(iso)?.toLocal();
    if (d == null) return '';
    const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return ' · ${tr('until')} ${d.day} ${m[d.month - 1]}';
  }

  @override
  Widget build(BuildContext context) {
    if (_promos.isEmpty) return const SizedBox.shrink();
    final s = context.watch<AppState>();
    return SizedBox(
      height: 84,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
        itemCount: _promos.length,
        separatorBuilder: (_, _) => const SizedBox(width: 10),
        itemBuilder: (_, i) {
          final p = _promos[i];
          final code = '${p['code']}';
          final mine = s.promo == code;
          return Container(
            width: 290,
            padding: const EdgeInsets.fromLTRB(14, 8, 10, 8),
            decoration: BoxDecoration(
              color: brand.withValues(alpha: 0.07),
              border: Border.all(color: brand.withValues(alpha: 0.5), width: 1.5),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Row(children: [
              const Text('🎟', style: TextStyle(fontSize: 22)),
              const SizedBox(width: 10),
              Expanded(
                child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${p['worth']}', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14)),
                  Text('${tr('Code')} $code${_until(p['ends_at'] as String?)}', maxLines: 1, overflow: TextOverflow.ellipsis, style: labelOf(context).copyWith(fontSize: 12)),
                ]),
              ),
              const SizedBox(width: 6),
              mine
                  ? Pill(tr('Claimed'), icon: Icons.check, bg: const Color(0xFFDCFCE7), fg: const Color(0xFF15803D))
                  : FilledButton(
                      style: FilledButton.styleFrom(minimumSize: const Size(0, 38), padding: const EdgeInsets.symmetric(horizontal: 14)),
                      onPressed: () {
                        s.setPromo(code);
                        toast(context, tr("Code {code} saved. We'll apply it at checkout.", {'code': code}));
                      },
                      child: Text(tr('Claim')),
                    ),
            ]),
          );
        },
      ),
    );
  }
}
