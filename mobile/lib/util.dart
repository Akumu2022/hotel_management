import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'api.dart';

const brand = Color(0xFFDC4B12);
const brandDark = Color(0xFF7A1D00);
const ink = Color(0xFF18181B);
const kMuted = Color(0xFF8A8A8F); // secondary text that reads on both light and dark

// One set of text styles so every screen reads the same.
const kTitle = TextStyle(fontSize: 20, fontWeight: FontWeight.w800);
const kSection = TextStyle(fontSize: 16, fontWeight: FontWeight.w800);
const kItem = TextStyle(fontSize: 15, fontWeight: FontWeight.w700);
const kBody = TextStyle(fontSize: 14);
const kLabel = TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: kMuted);

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
    return Image.network(
      absUrl(url!),
      width: width,
      height: height,
      fit: fit,
      cacheWidth: (w * dpr).round(),
      gaplessPlayback: true,
      frameBuilder: (_, child, frame, sync) =>
          sync ? child : AnimatedOpacity(opacity: frame == null ? 0 : 1, duration: const Duration(milliseconds: 250), child: child),
      errorBuilder: (_, __, ___) => SizedBox(width: width, height: height, child: empty),
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
class Skel extends StatelessWidget {
  final double height;
  const Skel(this.height, {super.key});
  @override
  Widget build(BuildContext context) => Container(
        height: height,
        decoration: BoxDecoration(color: Theme.of(context).colorScheme.onSurface.withValues(alpha: .07), borderRadius: BorderRadius.circular(20)),
      );
}

/// WhatsApp number for help, set by the admin (empty hides every help button). Cached for offline use.
Future<String> supportNumber() async {
  try {
    return '${((await apiGet('/config')) as Map)['support_whatsapp'] ?? ''}';
  } catch (_) {
    return '';
  }
}

Future<void> openWhatsApp(BuildContext context, String message) async {
  final number = await supportNumber();
  if (!context.mounted) return;
  if (number.isEmpty) return toast(context, 'Help chat is not set up yet');
  final ok = await launchUrl(Uri.parse('https://wa.me/$number?text=${Uri.encodeComponent(message)}'), mode: LaunchMode.externalApplication);
  if (!ok && context.mounted) toast(context, 'Could not open WhatsApp');
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
                  label: const Text('Chat with us on WhatsApp'),
                ),
              ),
      );
}

/// Filled button that spans the full width (use only where the width is bounded, never inside a Row).
final ButtonStyle fullWidthFilled = FilledButton.styleFrom(minimumSize: const Size.fromHeight(52));
