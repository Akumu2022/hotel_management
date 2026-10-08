import 'package:flutter/material.dart';
import '../i18n.dart';
import '../util.dart';

/// A short, plain explanation of how a customer's money and food are protected.
void showSafetySheet(BuildContext context) {
  final points = [
    (Icons.account_balance_wallet_outlined, tr("Your money goes straight to the hotel's own M-Pesa Till. Chakula never holds it, and never asks you to send money to a personal number.")),
    (Icons.badge_outlined, tr('Before you enter your PIN, M-Pesa shows who you are paying. It must match the name shown on your order. If it does not, stop and call the hotel.')),
    (Icons.verified_user_outlined, tr('Hotels with a green "Checked by Chakula" badge have been visited and checked by our team.')),
    (Icons.restaurant_outlined, tr("The hotel only starts cooking once its Till has received your payment.")),
    (Icons.lock_outline, tr('Your 4-digit PIN protects your food. Give it to the hotel or rider only when you are holding your order.')),
    (Icons.public, tr('Only use the official Chakula app or website. Never pay someone who contacts you privately.')),
  ];
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Icon(Icons.shield_outlined, color: Color(0xFF16A34A)),
            const SizedBox(width: 8),
            Text(tr('How we keep your money safe'), style: kTitle),
          ]),
          const SizedBox(height: 14),
          Flexible(
            child: ListView(shrinkWrap: true, children: [
              for (final p in points)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Icon(p.$1, size: 22, color: brand),
                    const SizedBox(width: 12),
                    Expanded(child: Text(p.$2, style: kBody)),
                  ]),
                ),
            ]),
          ),
          FilledButton(style: fullWidthFilled, onPressed: () => Navigator.pop(ctx), child: Text(tr('Got it'))),
        ]),
      ),
    ),
  );
}

/// The green "Checked by Chakula" pill.
Widget verifiedPill() => Pill(tr('Checked by Chakula'), icon: Icons.verified_user, bg: const Color(0xFFDCFCE7), fg: const Color(0xFF15803D));
