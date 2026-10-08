import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'api.dart';
import 'i18n.dart';

const brand = Color(0xFFDC4B12);
const brandDark = Color(0xFF7A1D00);
const ink = Color(0xFF18181B);
const kMuted = Color(0xFF8A8A8F); // secondary text that reads on both light and dark

// One set of text styles so every screen reads the same.
const kTitle = TextStyle(fontSize: 20, fontWeight: FontWeight.w800);
const kSection = TextStyle(fontSize: 16, fontWeight: FontWeight.w800);
const kItem = TextStyle(fontSize: 15, fontWeight: FontWeight.w700);
const kBody = TextStyle(fontSize: 14);
const kLabel = TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: kMuted); // only where context is unavailable

/// Secondary text colour with enough contrast on both the light and the dark theme.
Color mutedOf(BuildContext c) => Theme.of(c).brightness == Brightness.dark ? const Color(0xFFA8A8B0) : const Color(0xFF62626A);
TextStyle labelOf(BuildContext c) => TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: mutedOf(c));

/// A fitting emoji for a dish with no photo.
String foodEmoji(String name, [String category = '']) {
  final t = '$name $category'.toLowerCase();
  const map = {
    'pizza': '🍕', 'burger': '🍔', 'chicken': '🍗', 'wrap': '🌯', 'fish': '🐟', 'tilapia': '🐟', 'chips': '🍟', 'fries': '🍟',
    'rice': '🍚', 'pilau': '🍚', 'biryani': '🍚', 'ugali': '🍲', 'stew': '🍲', 'soup': '🍲', 'beef': '🥩', 'steak': '🥩', 'sausage': '🌭',
    'egg': '🍳', 'omelette': '🍳', 'coffee': '☕', 'tea': '☕', 'cappuccino': '☕', 'capucino': '☕', 'espresso': '☕', 'soda': '🥤', 'juice': '🧃',
    'shake': '🥤', 'water': '💧', 'salad': '🥗', 'cake': '🍰', 'mandazi': '🍩', 'donut': '🍩', 'chapati': '🫓', 'bread': '🍞', 'sandwich': '🥪',
    'pasta': '🍝', 'noodle': '🍜', 'samosa': '🥟', 'ice cream': '🍨', 'fruit': '🍎', 'dessert': '🍰', 'drink': '🥤', 'breakfast': '🍳',
  };
  for (final e in map.entries) {
    if (t.contains(e.key)) return e.value;
  }
  return '🍽️';
}

/// The picture area of a dish with no photo: a soft tint and a fitting emoji.
Widget dishFallback(String name, String category, double size) => Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      color: const Color(0xFFFFEDE3),
      child: Text(foodEmoji(name, category), style: TextStyle(fontSize: size * .5)),
    );

Future<void> callPhone(BuildContext context, String number) async {
  final ok = await launchUrl(Uri(scheme: 'tel', path: number));
  if (!ok && context.mounted) toast(context, tr('Could not open the dialler'));
}

String kes(num n) => 'KES ${n.round().toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => ',')}';

void toast(BuildContext c, String m) =>
    ScaffoldMessenger.of(c).showSnackBar(SnackBar(content: Text(m), behavior: SnackBarBehavior.floating));

/// Image URLs come back as server paths (e.g. /media/..); make them absolute.
String absUrl(String u) => u.startsWith('http') ? u : Uri.parse(apiBase).replace(path: u).toString();

Color accentOf(String? hex) {
  if (hex == null || hex.length < 6) return brand;
  final v = int.tryParse(hex.replaceFirst('#', ''), radix: 16);
  return v == null ? brand : Color(0xFF000000 | v);
}

/// Network image that decodes at display size (fast, low memory), fades in, and falls back quietly.
class NetImage extends StatelessWidget {
  final String? url;
  final double? width, height;
  final BoxFit fit;
  final Widget? fallback;
  const NetImage(this.url, {super.key, this.width, this.height, this.fit = BoxFit.cover, this.fallback});

  @override
  Widget build(BuildContext context) {
    final empty = fallback ?? ColoredBox(color: Colors.black.withValues(alpha: .06));
    if (url == null) return SizedBox(width: width, height: height, child: empty);
    final dpr = MediaQuery.devicePixelRatioOf(context);
    final w = width ?? MediaQuery.sizeOf(context).width;
    return CachedNetworkImage(
      imageUrl: absUrl(url!),
      width: width,
      height: height,
      fit: fit,
      memCacheWidth: (w * dpr).round(),
      fadeInDuration: const Duration(milliseconds: 220),
      placeholder: (_, __) => SizedBox(width: width, height: height, child: empty),
      errorWidget: (_, __, ___) => SizedBox(width: width, height: height, child: empty),
    );
  }
}

class Pill extends StatelessWidget {
  final String text;
  final IconData? icon;
  final Color? bg, fg;
  const Pill(this.text, {super.key, this.icon, this.bg, this.fg});
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final f = fg ?? cs.onSurface;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(color: bg ?? cs.surfaceContainerHighest, borderRadius: BorderRadius.circular(99)),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icon != null) ...[Icon(icon, size: 14, color: f), const SizedBox(width: 4)],
        Text(text, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: f)),
      ]),
    );
  }
}

/// Grey placeholder block shown while data loads.
class Skel extends StatefulWidget {
  final double height;
  const Skel(this.height, {super.key});
  @override
  State<Skel> createState() => _SkelState();
}

class _SkelState extends State<Skel> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1100))..repeat(reverse: true);
  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final base = Theme.of(context).colorScheme.onSurface;
    return AnimatedBuilder(
      animation: _c,
      builder: (_, __) => Container(
        height: widget.height,
        decoration: BoxDecoration(color: base.withValues(alpha: .05 + .06 * _c.value), borderRadius: BorderRadius.circular(20)),
      ),
    );
  }
}

/// WhatsApp number for help, set by the admin (empty hides every help button). Cached for offline use.
Future<String> supportNumber() async {
  try {
    return '${((await apiGet('/config')) as Map)['support_whatsapp'] ?? ''}';
  } catch (_) {
    return '';
  }
}

/// 0712 345 678 / +254 712 345 678 / 254712345678 -> 254712345678, or null if it isn't a Kenyan number.
String? kenyanNumber(String? raw) {
  if (raw == null) return null;
  final d = raw.replaceAll(RegExp(r'[\s\-()+]'), '');
  if (RegExp(r'^0[17]\d{8}$').hasMatch(d)) return '254${d.substring(1)}';
  if (RegExp(r'^254[17]\d{8}$').hasMatch(d)) return d;
  if (RegExp(r'^[17]\d{8}$').hasMatch(d)) return '254$d';
  return null;
}

Future<void> whatsAppTo(BuildContext context, String number, String message) async {
  final ok = await launchUrl(Uri.parse('https://wa.me/$number?text=${Uri.encodeComponent(message)}'), mode: LaunchMode.externalApplication);
  if (!ok && context.mounted) toast(context, tr('Could not open WhatsApp'));
}

/// Chakula's own help line (the platform number set by the super admin).
Future<void> openWhatsApp(BuildContext context, String message) async {
  final number = await supportNumber();
  if (!context.mounted) return;
  if (number.isEmpty) return toast(context, tr('Help chat is not set up yet'));
  await whatsAppTo(context, number, message);
}

/// Call and WhatsApp buttons for a hotel or rider's own number (whatever the hotel admin or the
/// rider entered). Hidden when there is no usable number, so nothing ever dials a blank.
class ContactRow extends StatelessWidget {
  final String? phone;
  final String message;
  const ContactRow(this.phone, {super.key, required this.message});
  @override
  Widget build(BuildContext context) {
    final n = kenyanNumber(phone);
    if (n == null) return const SizedBox.shrink();
    return Row(children: [
      Expanded(
        child: OutlinedButton.icon(
          onPressed: () => callPhone(context, '+$n'),
          icon: const Icon(Icons.call, size: 18),
          label: Text(tr('Call')),
        ),
      ),
      const SizedBox(width: 10),
      Expanded(
        child: OutlinedButton.icon(
          onPressed: () => whatsAppTo(context, n, message),
          icon: const Icon(Icons.chat_bubble_outline, size: 18, color: Color(0xFF16A34A)),
          label: const Text('WhatsApp'),
        ),
      ),
    ]);
  }
}

/// "Chat with us on WhatsApp"; hidden until the admin has set a number.
class HelpButton extends StatefulWidget {
  final String message;
  const HelpButton(this.message, {super.key});
  @override
  State<HelpButton> createState() => _HelpButtonState();
}

class _HelpButtonState extends State<HelpButton> {
  late final Future<String> _number = supportNumber();
  @override
  Widget build(BuildContext context) => FutureBuilder<String>(
        future: _number,
        builder: (_, snap) => (snap.data ?? '').isEmpty
            ? const SizedBox.shrink()
            : Padding(
                padding: const EdgeInsets.only(top: 12),
                child: OutlinedButton.icon(
                  onPressed: () => openWhatsApp(context, widget.message),
                  icon: const Icon(Icons.chat_bubble_outline, color: Color(0xFF16A34A)),
                  label: Text(tr('Chat with us on WhatsApp')),
                ),
              ),
      );
}

/// Filled button that spans the full width (use only where the width is bounded, never inside a Row).
final ButtonStyle fullWidthFilled = FilledButton.styleFrom(minimumSize: const Size.fromHeight(52));
